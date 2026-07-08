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
from src.desks.equity_ls.core.risk import checks as risk_checks
from src.desks.equity_ls.core.a3_catalyst_response import catalyst_response as a3
from src.desks.equity_ls.core.a5_relative_value import peers as a5_peers
from src.desks.equity_ls.core.a4_portfolio_decision import portfolio_decision as a4


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


# ── C risk layer: concentration / liquidity / data quality ────────────────────

class TestConcentrationCheck:
    def test_flags_position_over_threshold(self):
        holdings = [
            {"ticker": "AAA", "shares": 100},  # 100*30 = 3000 -> 75% of book
            {"ticker": "BBB", "shares": 100},  # 100*10 = 1000 -> 25% of book
        ]
        prices = {"AAA": 30.0, "BBB": 10.0}
        flags = risk_checks.scan_concentration(
            holdings, prices, warning_threshold=0.5, critical_threshold=0.7
        )
        tickers_flagged = {f.ticker for f in flags}
        assert "AAA" in tickers_flagged  # 75% > both thresholds
        assert "BBB" not in tickers_flagged  # 25% < warning_threshold 0.5
        assert flags[0].severity == "critical"  # 75% >= critical_threshold 0.7

    def test_currency_books_kept_separate(self):
        """A position that's tiny vs the combined USD+HKD portfolio but huge
        within its own currency book must still be flagged — mixing USD/HKD
        books was audit finding #12 (currency mixing silently understates risk).
        0700.HK here is <1% of combined USD+HKD value but 100% of the HKD book."""
        holdings = [
            {"ticker": "NVDA", "shares": 100_000},    # USD book: $19M
            {"ticker": "AAPL", "shares": 100_000},    # USD book: $21.5M — NVDA diluted to 47%
            {"ticker": "0700.HK", "shares": 10},      # HKD book: only position, 100% of it
        ]
        prices = {"NVDA": 190.0, "AAPL": 215.0, "0700.HK": 634.5}
        flags = risk_checks.scan_concentration(
            holdings, prices, warning_threshold=0.6, critical_threshold=0.9
        )
        flagged = {f.ticker: f for f in flags}
        assert "0700.HK" in flagged and flagged["0700.HK"].detail["currency"] == "HKD"
        assert flagged["0700.HK"].detail["weight"] == 1.0
        # NVDA/AAPL are ~47%/53% of the USD book — both under the 60% warning bar
        assert "NVDA" not in flagged and "AAPL" not in flagged

    def test_stale_price_flagged_not_hidden(self):
        """2026-07 finding: yfinance couldn't price Zhipu/2x-Hynix (your two
        biggest real concentration risks). Falling back to cost basis silently
        would understate weight for names that are up big. Must flag instead."""
        holdings = [{"ticker": "02513.HK", "shares": 200, "avg_cost": 459.80}]
        flags = risk_checks.scan_concentration(holdings, prices={})  # no live price
        assert len(flags) == 1
        assert flags[0].detail["stale_price"] is True
        assert "no live price" in flags[0].message

    def test_zero_share_positions_ignored(self):
        holdings = [{"ticker": "SOLD", "shares": 0, "avg_cost": 50}]
        assert risk_checks.scan_concentration(holdings, prices={"SOLD": 60.0}) == []


class TestLiquidityCheck:
    def test_within_threshold_no_flag(self):
        # 1M position / (100k shares * $20 = $2M ADV) = 0.5 days
        assert risk_checks.check_liquidity("X", 1_000_000, 100_000, 20.0) is None

    def test_over_threshold_warning(self):
        f = risk_checks.check_liquidity("X", 10_000_000, 50_000, 20.0)  # 10 days
        assert f.severity == "warning"

    def test_way_over_threshold_critical(self):
        f = risk_checks.check_liquidity("X", 30_000_000, 50_000, 20.0)  # 30 days
        assert f.severity == "critical"

    def test_missing_volume_data_flagged(self):
        f = risk_checks.check_liquidity("X", 1000, None, 20.0)
        assert f is not None and f.severity == "warning"


class TestDataQualityCheck:
    def test_error_in_market_data(self):
        f = risk_checks.check_data_quality("X", {"_error": "timeout"})
        assert f.severity == "critical"

    def test_missing_critical_field(self):
        f = risk_checks.check_data_quality("X", {"market_cap": 1e9})  # no price
        assert f.severity == "critical" and "price" in f.detail["missing"]

    def test_thin_scoring_fields_warns(self):
        f = risk_checks.check_data_quality("X", {"price": 10, "market_cap": 1e9})
        assert f.severity == "warning"

    def test_healthy_data_no_flag(self):
        healthy = {
            "price": 10, "market_cap": 1e9, "trailing_pe": 15, "forward_pe": 12,
            "ev_to_ebitda": 8, "revenue_growth": 0.1, "gross_margins": 0.4,
            "operating_margins": 0.2, "free_cash_flow": 1e8, "return_on_equity": 0.15,
        }
        assert risk_checks.check_data_quality("X", healthy) is None


class TestRunMinimalChecks:
    def test_combines_data_quality_and_liquidity(self):
        flags = risk_checks.run_minimal_checks(
            "X", market_data={"market_cap": 1e9}, position_value=1000,
        )
        # missing price -> data_quality critical; liquidity skipped (no market_data avg_volume)
        assert any(f.check == "data_quality" for f in flags)

    def test_no_position_value_skips_liquidity(self):
        healthy = {
            "price": 10, "market_cap": 1e9, "trailing_pe": 15, "forward_pe": 12,
            "ev_to_ebitda": 8, "revenue_growth": 0.1, "gross_margins": 0.4,
            "operating_margins": 0.2, "free_cash_flow": 1e8, "return_on_equity": 0.15,
        }
        assert risk_checks.run_minimal_checks("X", healthy, position_value=None) == []


# ── A5: shared peer map ────────────────────────────────────────────────────────

class TestA5Peers:
    def test_explicit_map_wins_over_sector(self):
        assert a5_peers.get_peers("NVDA") == ["AMD", "INTC", "AVGO", "QCOM", "TSM"]

    def test_sector_fallback_for_unmapped_ticker(self):
        peers = a5_peers.get_peers("SOMEUNKNOWNCO", sector="Technology")
        assert peers == a5_peers.SECTOR_FALLBACK["Technology"]

    def test_no_map_no_sector_returns_empty(self):
        assert a5_peers.get_peers("SOMEUNKNOWNCO", sector="") == []

    def test_limit_respected(self):
        assert len(a5_peers.get_peers("NVDA", limit=2)) == 2


# ── A3: catalyst response ──────────────────────────────────────────────────────

class TestA3DedupeAndBudget:
    def test_not_processed_initially(self, tmp_dbs):
        assert a3._recently_processed("NVDA", "earnings_preview", 1) is False

    def test_processed_within_window_detected(self, tmp_dbs):
        dh.record_decision("NVDA", "a3", "Monitor", "x", triggered_by="earnings_preview")
        assert a3._recently_processed("NVDA", "earnings_preview", 1) is True

    def test_different_event_type_not_deduped(self, tmp_dbs):
        dh.record_decision("NVDA", "a3", "Monitor", "x", triggered_by="earnings_preview")
        assert a3._recently_processed("NVDA", "catalyst", 1) is False

    def test_budget_tracks_only_reruns(self, tmp_dbs):
        dh.record_decision("NVDA", "a3", "Monitor", "x", triggered_by="earnings_preview")  # not a rerun
        assert a3._reruns_today() == 0
        dh.record_decision("MU", "a3", "Deep Dive", "x", triggered_by="rerun:earnings_review")
        assert a3._reruns_today() == 1

    def test_budget_remaining_decreases(self, tmp_dbs):
        dh.record_decision("MU", "a3", "Deep Dive", "x", triggered_by="rerun:earnings_review")
        assert a3.budget_remaining(daily_budget=5) == 4
        assert a3.budget_remaining(daily_budget=1) == 0


class TestA3Wiring:
    """A3's full run() with every LLM/network call mocked — verifies the
    control flow: dedupe -> judge -> read-through -> rerun-if-material,
    budget-capped -> always record_decision (never current_view)."""

    @staticmethod
    def _patches(judge_return, deep_dive_run=None):
        from unittest.mock import patch

        class _FakeScreen:
            sector = "Technology"

        patches = [
            patch.object(a3, "_get_current_thesis", return_value="Long thesis"),
            patch.object(a3, "_get_news_context", return_value="no news"),
            patch.object(a3, "_get_price_reaction", return_value="$100 (0%)"),
            patch.object(a3, "_get_earnings_context", return_value={}),
            patch.object(a3, "_judge_event", return_value=judge_return),
            patch("src.desks.equity_ls.core.screener.screener.run", return_value=_FakeScreen()),
        ]
        if deep_dive_run is not None:
            from src.desks.equity_ls.core.a2_deep_dive import deep_dive
            patches.append(patch.object(deep_dive, "run", return_value=deep_dive_run))
        return patches

    def test_unknown_event_type_skipped(self, tmp_dbs):
        result = a3.run("NVDA", "not_a_real_type")
        assert result.skipped and "Unknown event_type" in result.skip_reason

    def test_out_of_universe_skipped(self, tmp_dbs):
        result = a3.run("FOO.XX", "catalyst", force=True)
        assert result.skipped and "Out of universe" in result.skip_reason

    def test_dedupe_skips_without_force(self, tmp_dbs):
        dh.record_decision("NVDA", "a3", "Monitor", "x", triggered_by="earnings_preview")
        result = a3.run("NVDA", "earnings_preview", force=False)
        assert result.skipped and "Already processed" in result.skip_reason

    def test_force_bypasses_dedupe(self, tmp_dbs):
        dh.record_decision("NVDA", "a3", "Monitor", "x", triggered_by="earnings_preview")
        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in self._patches(("confirmed", "Confirms", "Hold")):
                stack.enter_context(p)
            result = a3.run("NVDA", "earnings_preview", force=True)
        assert result.skipped is False

    def test_confirms_does_not_trigger_rerun(self, tmp_dbs):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in self._patches(("solid quarter", "Confirms", "Hold")):
                stack.enter_context(p)
            result = a3.run("NVDA", "earnings_review", "beat", force=True)
        assert result.thesis_impact == "Confirms"
        assert result.deep_dive_triggered is False
        assert dh.get_current_view("NVDA") is None  # a3 never sets current_view

    def test_breaks_triggers_rerun_within_budget(self, tmp_dbs):
        class _FakeDD:
            verdict = "Sell"
        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in self._patches(("bad quarter", "Breaks", "Deep Dive"), deep_dive_run=_FakeDD()):
                stack.enter_context(p)
            result = a3.run("MU", "earnings_review", "missed badly", force=True)
        assert result.thesis_impact == "Breaks"
        assert result.deep_dive_triggered is True
        assert result.decision_id is not None
        history = dh.get_decision_history("MU")
        assert history[0]["triggered_by"] == "rerun:earnings_review"

    def test_breaks_blocked_by_exhausted_budget(self, tmp_dbs):
        dh.record_decision("PRIOR", "a3", "Deep Dive", "x", triggered_by="rerun:earnings_review")
        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in self._patches(("bad quarter", "Breaks", "Deep Dive")):
                stack.enter_context(p)
            result = a3.run("MU", "earnings_review", "missed", force=True, daily_rerun_budget=1)
        assert result.deep_dive_triggered is False
        assert "budget" in result.errors

    def test_read_through_uses_shared_peer_map(self, tmp_dbs):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in self._patches(("ok", "Confirms", "Hold")):
                stack.enter_context(p)
            result = a3.run("NVDA", "catalyst", "some news", force=True)
        assert result.read_through == a5_peers.get_peers("NVDA")

    def test_always_records_decision_never_current_view(self, tmp_dbs):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in self._patches(("ok", "Confirms", "Hold")):
                stack.enter_context(p)
            a3.run("NVDA", "catalyst", "some news", force=True)
        assert len(dh.get_decision_history("NVDA", source="a3")) == 1
        assert dh.get_current_view("NVDA") is None


# ── A4: portfolio decision support ──────────────────────────────────────────────

class TestA4PositionReview:
    """A4 owns current_view for held tickers (the other side of the
    single-writer rule from TestA2DecisionHistoryWiring). Hard boundary:
    PositionReview has no size/weight field — direction only."""

    def test_refuses_non_held_ticker(self, tmp_dbs):
        result = a4.review_position("NOTHELD")
        assert result.skipped is True and "not currently held" in result.skip_reason
        assert result.is_held is False

    def test_refuses_zero_share_holding(self, tmp_dbs):
        portfolio_db.upsert_holding("SOLD", shares=0, avg_cost=50)
        result = a4.review_position("SOLD")
        assert result.skipped is True

    def test_reviews_held_position_and_sets_current_view(self, tmp_dbs):
        from unittest.mock import patch
        portfolio_db.upsert_holding("NVDA", shares=100, avg_cost=150.0, sector="Technology")

        class _FakeScreen:
            composite_score = 65.0
            classification = "Neutral"

        with patch(
            "src.desks.equity_ls.infrastructure.b2_data_source.data_sources.get_market_data",
            return_value={"price": 190.0},
        ), patch(
            "src.desks.equity_ls.core.screener.screener.run", return_value=_FakeScreen()
        ), patch.object(a4, "_judge_position", return_value=("Thesis intact", "Hold")):
            result = a4.review_position("NVDA", save_to_kb=False)

        assert result.is_held is True
        assert result.holding_snapshot["pnl_pct"] == pytest.approx(26.667, abs=0.01)
        assert result.direction == "Hold"
        assert result.became_current_view is True
        assert dh.get_current_view("NVDA")["source"] == "a4"

    def test_direction_must_be_one_of_defined_set(self, tmp_dbs):
        assert a4.DIRECTIONS == {"Hold", "Add", "Trim", "Sell", "Rotate", "Deep Dive Further"}

    def test_position_review_has_no_sizing_field(self):
        """Structural enforcement of the hard boundary (audit finding #4):
        there must be no field on PositionReview a caller could mistake for
        a size, weight, or share-count recommendation."""
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(a4.PositionReview)}
        forbidden = {"shares_to_trade", "size", "weight", "target_weight", "dollar_amount", "position_size"}
        assert not (field_names & forbidden)


class TestA4PortfolioReview:
    def test_empty_portfolio(self, tmp_dbs):
        result = a4.review_portfolio()
        assert result.total_positions == 0

    def test_reviews_multi_currency_portfolio(self, tmp_dbs):
        from unittest.mock import patch
        portfolio_db.upsert_holding("NVDA", shares=100, avg_cost=150, sector="Technology")
        portfolio_db.upsert_holding("JPM", shares=50, avg_cost=200, sector="Financials")
        portfolio_db.upsert_holding("0700.HK", shares=200, avg_cost=600, sector="AI-Apps")

        fake_prices = {"NVDA": {"price": 190.0}, "JPM": {"price": 250.0}, "0700.HK": {"price": 634.5}}

        with patch(
            "src.desks.equity_ls.infrastructure.b2_data_source.data_sources.get_market_data",
            side_effect=lambda t: fake_prices.get(t, {"_error": "no data"}),
        ), patch.object(a4, "_synthesize_strategy", return_value="fake strategy note"):
            result = a4.review_portfolio()

        assert result.total_positions == 3
        assert set(result.currency_exposure) == {"USD", "HKD"}
        assert result.currency_exposure["USD"] + result.currency_exposure["HKD"] == pytest.approx(1.0)
        assert result.strategy_note == "fake strategy note"

    def test_portfolio_review_never_touches_current_view(self, tmp_dbs):
        from unittest.mock import patch
        portfolio_db.upsert_holding("NVDA", shares=100, avg_cost=150, sector="Technology")
        with patch(
            "src.desks.equity_ls.infrastructure.b2_data_source.data_sources.get_market_data",
            return_value={"price": 190.0},
        ), patch.object(a4, "_synthesize_strategy", return_value=""):
            a4.review_portfolio()
        assert dh.get_current_view("NVDA") is None  # read-only scan, per-name review is separate
