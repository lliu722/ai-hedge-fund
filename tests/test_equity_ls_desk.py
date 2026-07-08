"""
Unit tests for the Equity L/S desk (src/desks/equity_ls/).

Network-free by design: pure-logic functions are tested directly, and the
SQLite modules are pointed at temp DBs via monkeypatched _DB_PATH so the
real desk data is never touched.
"""
import pytest

from src.desks.equity_ls.core.a2_deep_dive import deep_dive
from src.desks.equity_ls.core.screener import cadence, screener
from src.desks.equity_ls.core.monitor import monitor
from src.desks.equity_ls.infrastructure.b1_universe import exclusion_db, universe
from src.desks.equity_ls.infrastructure.b3_portfolio import portfolio_db
from src.desks.equity_ls.infrastructure.b4_knowledge_base import knowledge_base as kb
from src.desks.equity_ls.infrastructure.b5_trading_agents.pipeline import _extract_signal
from src.desks.equity_ls.infrastructure.b2_data_source import data_sources
from src.desks.equity_ls.infrastructure.b4_knowledge_base import decision_history as dh


# ── Fixtures: point every DB at a temp file ───────────────────────────────────

@pytest.fixture
def tmp_dbs(tmp_path, monkeypatch):
    monkeypatch.setattr(exclusion_db, "_DB_PATH", tmp_path / "exclusion.db")
    monkeypatch.setattr(portfolio_db, "_DB_PATH", tmp_path / "portfolio.db")
    monkeypatch.setattr(kb, "_DB_PATH", tmp_path / "kb.db")
    monkeypatch.setattr(dh, "_DB_PATH", tmp_path / "kb.db")
    monkeypatch.setattr(monitor, "_STATE_DB", tmp_path / "monitor_state.db")
    return tmp_path


# ── B2: data source unit normalization ────────────────────────────────────────

class _FakeYFTicker:
    """Minimal stand-in for yfinance.Ticker — only what _yf_fetch touches."""
    def __init__(self, info: dict):
        self.info = info
        self.quarterly_financials = None
        self.quarterly_cashflow = None


class TestDataSourceUnits:
    def test_debt_to_equity_normalized_to_true_ratio(self, monkeypatch):
        """2026-07 audit fix: yfinance reports debtToEquity in percentage-point
        form (KO=124.9 means a 1.25x ratio, not a 124.9x ratio). Every screener
        threshold assumes a true ratio, so data_sources.py must normalize once
        at the source rather than let every caller get it wrong."""
        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", lambda ticker: _FakeYFTicker({"debtToEquity": 124.9}))
        result = data_sources._yf_fetch("KO")
        assert result["debt_to_equity"] == pytest.approx(1.249)

    def test_debt_to_equity_none_passthrough(self, monkeypatch):
        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", lambda ticker: _FakeYFTicker({"debtToEquity": None}))
        result = data_sources._yf_fetch("XYZ")
        assert result["debt_to_equity"] is None

    def test_low_debt_name_no_longer_reads_as_high_leverage(self, monkeypatch):
        """The false-positive this bug caused: NVDA's raw debtToEquity=6.555
        (a true ratio of 0.066x) used to blow past the screener's de>3.0
        'high leverage' threshold because nobody divided by 100."""
        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", lambda ticker: _FakeYFTicker({"debtToEquity": 6.555}))
        result = data_sources._yf_fetch("NVDA")
        assert result["debt_to_equity"] < 0.3  # screener's "low leverage" bucket


# ── B1: universe gate + tiers ─────────────────────────────────────────────────

class TestUniverse:
    def test_us_ticker_in_scope(self, tmp_dbs):
        meta = universe.check("XYZ")
        assert meta.in_scope and meta.tier == 4

    def test_hk_ticker_in_scope(self, tmp_dbs):
        assert universe.check("0700.HK").in_scope

    def test_unknown_suffix_rejected(self, tmp_dbs):
        meta = universe.check("FOO.XX")
        assert not meta.in_scope and meta.rejection_reason == "region not eligible"

    def test_excluded_ticker_rejected(self, tmp_dbs):
        exclusion_db.add("BADCO", "test block")
        meta = universe.check("BADCO")
        assert not meta.in_scope and meta.rejection_reason == "excluded"

    def test_tier_priority_holding_beats_leader(self, tmp_dbs):
        portfolio_db.upsert_holding("NVDA", shares=10, avg_cost=100)
        assert universe.check("NVDA").tier == 0  # holding wins over T2 leader

    def test_watchlist_is_t1(self, tmp_dbs):
        portfolio_db.add_to_watchlist("SNOW")
        assert universe.check("SNOW").tier == 1

    def test_sector_leader_is_t2(self, tmp_dbs):
        assert universe.check("AAPL").tier == 2

    def test_disallowed_instrument_type(self, tmp_dbs):
        meta = universe.check("XYZ", instrument_type="etf", allowed_types={"single_stock"})
        assert not meta.in_scope

    def test_get_sector_leaders_returns_copy(self, tmp_dbs):
        leaders = universe.get_sector_leaders()
        leaders.clear()
        assert "AAPL" in universe.get_sector_leaders()


# ── B1: exclusion DB ──────────────────────────────────────────────────────────

class TestExclusionDb:
    def test_add_remove_roundtrip(self, tmp_dbs):
        exclusion_db.add("EVIL", "sanctions")
        assert exclusion_db.is_excluded("evil")  # case-insensitive
        exclusion_db.remove("EVIL")
        assert not exclusion_db.is_excluded("EVIL")

    def test_add_updates_reason(self, tmp_dbs):
        exclusion_db.add("EVIL", "old reason")
        exclusion_db.add("EVIL", "new reason")
        entries = {e["ticker"]: e["reason"] for e in exclusion_db.list_all()}
        assert entries["EVIL"] == "new reason"


# ── B3: portfolio DB ──────────────────────────────────────────────────────────

class TestPortfolioDb:
    def test_holding_crud(self, tmp_dbs):
        portfolio_db.upsert_holding("NVDA", name="NVIDIA", sector="Tech", shares=10, avg_cost=100)
        assert portfolio_db.is_holding("nvda")
        assert portfolio_db.get_holding("NVDA")["shares"] == 10
        portfolio_db.remove_holding("NVDA")
        assert not portfolio_db.is_holding("NVDA")

    def test_zero_share_holding_not_held(self, tmp_dbs):
        portfolio_db.upsert_holding("SOLD", shares=0, avg_cost=50)
        assert not portfolio_db.is_holding("SOLD")
        assert portfolio_db.get_holdings() == []

    def test_sector_exposure_weights(self, tmp_dbs):
        portfolio_db.upsert_holding("A", sector="Tech", shares=10, avg_cost=30)    # 300
        portfolio_db.upsert_holding("B", sector="Energy", shares=10, avg_cost=10)  # 100
        exp = portfolio_db.sector_exposure()
        assert exp["Tech"] == 0.75 and exp["Energy"] == 0.25

    def test_trade_journal_order(self, tmp_dbs):
        portfolio_db.log_trade("NVDA", "buy", shares=5, price=100)
        portfolio_db.log_trade("NVDA", "trim", shares=2, price=120)
        trades = portfolio_db.get_trades("NVDA")
        assert trades[0]["action"] == "trim"  # newest first, same-second safe


# ── B4: knowledge base ────────────────────────────────────────────────────────

class TestKnowledgeBase:
    def test_report_roundtrip_and_fts(self, tmp_dbs):
        rid = kb.add_report("NVDA", "deep_dive", "Test", "unique xylophone content")
        assert len(kb.search_reports("xylophone")) == 1
        kb.delete_report(rid)
        assert kb.search_reports("xylophone") == []       # FTS synced on delete
        assert kb.get_reports("NVDA") == []

    def test_malformed_fts_query_returns_empty(self, tmp_dbs):
        kb.add_report("NVDA", "other", "T", "body")
        assert kb.search_reports("AND OR NOT((") == []

    def test_unknown_report_type_coerced(self, tmp_dbs):
        kb.add_report("NVDA", "not_a_type", "T", "body")
        assert kb.get_reports("NVDA")[0]["report_type"] == "other"

    def test_thesis_versioning(self, tmp_dbs):
        assert kb.save_thesis("NVDA", "v1 thesis") == 1
        assert kb.save_thesis("NVDA", "v2 thesis") == 2
        assert kb.get_current_thesis("NVDA") == "v2 thesis"
        assert len(kb.get_thesis_history("NVDA")) == 2

    def test_latest_agent_output_same_second(self, tmp_dbs):
        # 8 inserts in the same second — id tiebreaker must pick the last one
        for name in ["a", "b", "c", "trader"]:
            kb.add_agent_output("NVDA", name, "BUY", "r")
        assert kb.get_latest_agent_output("NVDA")["agent_name"] == "trader"

    def test_pdf_filename_parsing(self):
        from pathlib import Path
        cases = {
            "NVDA_deep_dive_2025Q2.pdf": ("NVDA", "deep_dive"),
            "TSMC_earnings_note_Q1.pdf": ("TSMC", "earnings_note"),
            "GS_trade_review_exit.pdf":  ("GS", "trade_review"),
            "random_report.pdf":         ("RANDOM", "other"),
        }
        for fname, expected in cases.items():
            assert kb._parse_pdf_filename(Path(fname)) == expected


# ── B4: decision history + single-writer current_view ─────────────────────────

class TestDecisionHistory:
    """2026-07 audit fix #3: A2/A3/A4 all want to write the desk's official
    stance on a name. This is the resolution — held tickers are owned by a4,
    not-held tickers by a2, enforced in code via SingleWriterViolation."""

    def test_owner_flips_on_holding_status(self, tmp_dbs):
        assert dh.owner_for("NVDA") == "a2"
        portfolio_db.upsert_holding("NVDA", shares=10, avg_cost=100)
        assert dh.owner_for("NVDA") == "a4"

    def test_owning_source_can_set_current_view(self, tmp_dbs):
        did = dh.record_as_current_view("NVDA", "a2", "Long", "strong momentum")
        assert dh.get_current_view("NVDA")["verdict"] == "Long"
        assert dh.get_current_view("NVDA")["decision_id"] == did

    def test_non_owning_source_rejected(self, tmp_dbs):
        with pytest.raises(dh.SingleWriterViolation):
            dh.record_as_current_view("NVDA", "a4", "Trim", "nope")  # not held -> a2 owns

    def test_a3_and_a5_never_own_current_view(self, tmp_dbs):
        for source in ("a1", "a3", "a5"):
            with pytest.raises(dh.SingleWriterViolation):
                dh.record_as_current_view("NVDA", source, "Trim", "nope")

    def test_record_decision_never_touches_current_view(self, tmp_dbs):
        dh.record_as_current_view("NVDA", "a2", "Long", "initial view")
        dh.record_decision("NVDA", "a3", "Trim", "earnings miss", triggered_by="catalyst")
        assert dh.get_current_view("NVDA")["verdict"] == "Long"
        assert len(dh.get_decision_history("NVDA")) == 2

    def test_new_owner_supersedes_old_current_view(self, tmp_dbs):
        old_id = dh.record_as_current_view("NVDA", "a2", "Long", "not held yet")
        portfolio_db.upsert_holding("NVDA", shares=10, avg_cost=100)
        new_id = dh.record_as_current_view("NVDA", "a4", "Hold", "now held")
        history = {h["id"]: h for h in dh.get_decision_history("NVDA")}
        assert history[old_id]["superseded_by"] == new_id
        assert dh.get_current_view("NVDA")["decision_id"] == new_id

    def test_invalid_source_rejected(self, tmp_dbs):
        with pytest.raises(ValueError):
            dh.record_decision("NVDA", "not_a_real_source", "Long", "x")


class TestA2DecisionHistoryWiring:
    """A2 must set current_view for non-held tickers, and must NOT override
    A4's stance on held tickers — verified through the real deep_dive.run()
    call with every LLM/network call mocked out."""

    @staticmethod
    def _run_mocked(ticker: str, tier: int, verdict: str = "Long"):
        from unittest.mock import patch

        class _FakeScreen:
            hard_pass = True
            hard_fail_reason = ""
            composite_score = 55.0
            classification = "Neutral"
            flags: list = []
            raw = {"sector": "Technology"}

        with patch.object(deep_dive, "_gate", return_value=(True, tier, "")), \
             patch.object(deep_dive, "_run_screening", return_value=_FakeScreen()), \
             patch.object(deep_dive, "_format_screening_for_prompt", return_value="fake"), \
             patch.object(deep_dive, "_run_desk_conclusion", return_value="fake conclusion"), \
             patch.object(deep_dive, "_run_valuation_view", return_value="fake valuation"), \
             patch.object(deep_dive, "_run_trade_expression", return_value="fake expression"), \
             patch.object(deep_dive, "_run_verdict", return_value=(verdict, f"{verdict}\nfake rationale")):
            return deep_dive.run(ticker, skip_ta=True, save_to_kb=True)

    def test_a2_sets_current_view_for_non_held(self, tmp_dbs):
        result = self._run_mocked("TESTX", tier=4, verdict="Long")
        assert result.became_current_view is True
        assert dh.get_current_view("TESTX")["verdict"] == "Long"

    def test_a2_does_not_override_held_ticker(self, tmp_dbs):
        portfolio_db.upsert_holding("TESTX", shares=5, avg_cost=10)
        dh.record_as_current_view("TESTX", "a4", "Hold", "a4's existing stance")
        result = self._run_mocked("TESTX", tier=0, verdict="Sell")
        assert result.became_current_view is False
        assert dh.get_current_view("TESTX")["verdict"] == "Hold"  # unchanged by A2
        # But A2's output IS logged — A4 can see it next time it reviews the name
        history = dh.get_decision_history("TESTX", source="a2")
        assert len(history) == 1 and history[0]["verdict"] == "Sell"


# ── B5: signal extraction ─────────────────────────────────────────────────────

class TestSignalExtraction:
    def test_action_line_preferred(self):
        assert _extract_signal("The buyback continues.\nAction: SELL") == "SELL"

    def test_word_boundary(self):
        assert _extract_signal("BUYBACK announced, nothing else") == "HOLD"

    def test_first_word_match_fallback(self):
        assert _extract_signal("We recommend to AVOID this") == "AVOID"

    def test_default_hold(self):
        assert _extract_signal("no signal at all") == "HOLD"


# ── Screener: pure logic ──────────────────────────────────────────────────────

class TestScreenerLogic:
    def test_classification_bands(self):
        assert screener._classify(85)[0].startswith("Deep-Dive")
        assert screener._classify(70)[0].startswith("Watchlist")
        assert screener._classify(55)[0].startswith("Neutral")
        assert screener._classify(40)[0].startswith("Weak")
        assert screener._classify(20)[0].startswith("Remove")

    def test_hard_filters(self):
        ok, _ = screener._step1_hard_filters("X", {"market_cap": 1e9, "avg_volume_10d": 1e6, "price": 50, "revenue": 1e9})
        assert ok
        bad, reason = screener._step1_hard_filters("X", {"market_cap": 1e8, "avg_volume_10d": 1e6, "price": 50})
        assert not bad and "Market cap" in reason

    def test_relative_strength(self):
        assert screener._relative_strength(10.0, 4.0) == 6.0
        assert screener._relative_strength(None, 4.0) is None

    def test_component_score_pct(self):
        assert screener.ComponentScore(10, 20).pct == 0.5
        assert screener.ComponentScore(0, 0).pct == 0.0

    def test_composite_subtracts_risk(self):
        sr = screener.ScreeningResult(ticker="X", run_date="2026-01-01")
        sr.momentum = screener.ComponentScore(20, 25)
        sr.risk_penalty = screener.ComponentScore(5, 20)
        assert screener._composite(sr) == 15.0

    def test_handoff_low_score_avoid(self):
        trigger, _ = screener._handoff(20, None, tier=4)
        assert trigger == "Avoid Note Trigger"

    def test_handoff_agrees_with_cadence_single_authority(self):
        """2026-07 audit fix: _handoff() used to independently decide 'T0/T1
        always deep-dive' while cadence.py said 'T0 only on a major event' —
        two authorities, silently disagreeing. _handoff() must now delegate,
        so for every (tier, score, days_to_earnings) combination the two
        can never disagree."""
        cases = [
            (0, 50, None),   # T0, mid score, no event -> cadence: False (event-driven only)
            (0, 95, None),   # T0, high score, no event -> still False, T0 ignores score
            (0, 50, 3),      # T0, mid score, event in 3d -> True
            (1, 50, None),   # T1, mid score -> False (needs score>=80)
            (1, 85, None),   # T1, high score -> True
            (2, 85, None),   # T2, high score -> True
            (2, 50, 5),      # T2, event -> True (score-or-event tier)
            (4, 90, None),   # T4, high score -> True (promotion threshold 75)
        ]
        for tier, score, days in cases:
            has_event = cadence.is_major_event(days)
            expected = cadence.should_trigger_deep_dive(tier, score, has_event)
            trigger, _ = screener._handoff(score, days, tier)
            actual = trigger == "Deep Dive Trigger"
            assert actual == expected, f"tier={tier} score={score} days={days}: handoff={actual} cadence={expected}"


# ── Cadence ───────────────────────────────────────────────────────────────────

class TestCadence:
    def test_refresh_intervals(self):
        assert cadence.should_run_score_refresh(0, 7)
        assert not cadence.should_run_score_refresh(0, 3)
        assert cadence.should_run_score_refresh(3, 14)
        assert not cadence.should_run_score_refresh(4, 9999)   # initial_only never refreshes
        assert not cadence.should_run_score_refresh(99, 9999)  # unknown tier = restricted

    def test_deep_dive_triggers(self):
        assert cadence.should_trigger_deep_dive(0, 10, has_major_event=True)
        assert not cadence.should_trigger_deep_dive(0, 90, has_major_event=False)  # T0 = event-driven
        assert cadence.should_trigger_deep_dive(1, 85)
        assert not cadence.should_trigger_deep_dive(1, 75)
        assert cadence.should_trigger_deep_dive(2, 50, has_major_event=True)
        assert cadence.should_trigger_deep_dive(4, 76)  # T4 promotion threshold 75


# ── A2: verdict parsing ───────────────────────────────────────────────────────

class TestVerdictParsing:
    def test_first_line(self):
        assert deep_dive._parse_verdict("Long\nStrong setup.") == "Long"

    def test_markdown_wrapped(self):
        assert deep_dive._parse_verdict("**Add to watchlist**\nnot urgent") == "Add to watchlist"

    def test_longest_match_wins(self):
        # "Add to watchlist" contains no other verdict, but "Dig further" lines
        # must not be misread when another verdict word appears later
        assert deep_dive._parse_verdict("Dig further\nCould become a Long later") == "Dig further"

    def test_unparseable_returns_empty(self):
        assert deep_dive._parse_verdict("total nonsense") == ""


# ── Monitor: state tracking ───────────────────────────────────────────────────

class TestMonitorState:
    def test_never_run(self, tmp_dbs):
        assert monitor._days_since_last_run("NEWNAME") == monitor._NEVER_RUN

    def test_mark_and_check(self, tmp_dbs):
        monitor._mark_run("NVDA")
        assert monitor._days_since_last_run("nvda") == 0
