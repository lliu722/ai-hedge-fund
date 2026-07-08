"""
A2 — Single-Name Deep Dive (Equity L/S desk).

Pipeline (in order):
  1. Universe gate         — reject out-of-scope names immediately (B1)
  2. Screening context     — liquidity, quality, momentum, valuation, risk scores (B2)
  3. TradingAgents run     — 4 analysts + bull/bear debate + manager + trader (B5)
  4. Desk conclusion       — synthesises TA output + screening into desk view (LLM)
  5. Valuation view        — multiples, peer comp, upside/downside (LLM)
  6. Trade expression      — how to express the idea (LLM)
  7. Output verdict        — Long / Avoid / Monitor / Trim / Sell / Dig further / Watchlist

All intermediate outputs and the final report are saved to B4 (knowledge_base).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.desks.equity_ls.infrastructure.llm import get_llm as _llm


# ── Output types ──────────────────────────────────────────────────────────────

VERDICTS = {"Long", "Avoid", "Monitor", "Trim", "Sell", "Dig further", "Add to watchlist"}


@dataclass
class DeepDiveResult:
    ticker: str
    run_date: str
    tier: int | None = None

    # Section outputs
    screening_context: dict = field(default_factory=dict)
    screening_flags: list[str] = field(default_factory=list)   # any red flags from screening
    ta_result: object = None                                    # TradingAgentsResult from B5
    desk_conclusion: str = ""
    valuation_view: str = ""
    trade_expression: str = ""
    verdict: str = ""          # canonical — one of VERDICTS ("" if unparseable)
    verdict_detail: str = ""   # full verdict text incl. rationale

    # KB report id
    report_id: int | None = None
    # Decision History id (B4). Only set if this run became the ticker's
    # current_view — i.e. the ticker wasn't held. See decision_history.py
    # for the single-writer rule; A2 never overrides A4 on a held name.
    decision_id: int | None = None
    became_current_view: bool = False
    errors: dict = field(default_factory=dict)


# ── Step 1: Universe gate ─────────────────────────────────────────────────────

def _gate(ticker: str) -> tuple[bool, int | None, str]:
    """Returns (in_scope, tier, rejection_reason)."""
    from src.desks.equity_ls.infrastructure.b1_universe.universe import check
    meta = check(ticker)
    return meta.in_scope, meta.tier, meta.rejection_reason


# ── Step 2: Screening ────────────────────────────────────────────────────────

def _run_screening(ticker: str, tier: int):
    """Run the full 6-step screener. Returns ScreeningResult."""
    from src.desks.equity_ls.core.screener import screener
    return screener.run(ticker, tier=tier)


def _format_screening_for_prompt(sr) -> str:
    """Format ScreeningResult into LLM-ready block."""
    from src.desks.equity_ls.core.screener import screener
    return screener.format_for_prompt(sr)


# ── Step 4: Desk conclusion ───────────────────────────────────────────────────

def _run_desk_conclusion(
    ticker: str,
    screening_block: str,
    ta_result,
) -> str:
    prompt = f"""You are the Equity Long/Short desk analyst. You have just received:
1. A screening context showing key metrics and any red flags.
2. A full TradingAgents run (4 specialist analysts + bull/bear debate + research manager + trader).

Your job is to form the DESK'S OWN VIEW — not simply relay the TradingAgents output.
Critically assess where you agree and disagree with the TA view. The desk view is what matters.

{screening_block}

TRADINGAGENTS — INVESTMENT PLAN (Research Manager):
{ta_result.investment_plan}

TRADINGAGENTS — TRADER PROPOSAL:
{ta_result.trader_plan}

Produce the desk conclusion covering:
1. Do you agree with the TradingAgents direction? If not, where and why does your view diverge?
2. What does the screening context confirm or challenge about the TA view?
3. What is the desk's primary thesis in 2-3 sentences?
4. Key upside drivers (3 bullet points max)
5. Key risks / bear case (3 bullet points max)
6. Preliminary desk stance: Long / Avoid / Monitor / Trim / Sell / Dig further / Add to watchlist"""

    try:
        resp = _llm().invoke(prompt)
        return resp.content
    except Exception as e:
        return f"[Desk conclusion error: {e}]"


# ── Step 5: Valuation / Upside-Downside ──────────────────────────────────────

def _run_valuation_view(ticker: str, screening_block: str, desk_conclusion: str, sector: str = "") -> str:
    print(f"[A2] Fetching peer comparison for {ticker}...")
    from src.desks.equity_ls.core.a5_relative_value.peers import get_peer_comparison_table
    peer_table = get_peer_comparison_table(ticker, sector)

    prompt = f"""You are the valuation analyst for the Equity L/S desk.
You have real market data for {ticker} and its closest peers. Use the peer table as your primary
reference — do not invent multiples. Comment on where {ticker} sits vs each peer specifically.

{screening_block}

PEER COMPARISON (live data):
{peer_table}

DESK CONCLUSION:
{desk_conclusion}

Produce:
1. Valuation assessment — cheap / fair / rich / very rich, and vs which specific peers
2. Horizontal comparison — for each peer in the table, is {ticker}'s P/E / EV/EBITDA / FCF yield
   higher or lower, and is the premium or discount justified by the growth/quality difference?
3. Historical range — where do current multiples sit vs the name's own history?
4. Base case upside/downside — bull case price target and bear case price with rationale
5. Growth quality — is the growth durable or are there red flags?
6. Does the upside justify the risk vs peers? Answer clearly: Yes / No / Only on weakness"""

    try:
        resp = _llm().invoke(prompt)
        return resp.content
    except Exception as e:
        return f"[Valuation view error: {e}]"


# ── Step 6: Trade expression ──────────────────────────────────────────────────

def _run_trade_expression(
    ticker: str,
    desk_conclusion: str,
    valuation_view: str,
) -> str:
    prompt = f"""You are the trade structuring analyst for the Equity L/S desk.
Based on the desk conclusion and valuation view below, recommend how to express this idea.

DESK CONCLUSION:
{desk_conclusion}

VALUATION VIEW:
{valuation_view}

Expression options:
- single_stock  — direct long or short in {ticker}
- etf           — express via sector/thematic ETF (lower idiosyncratic risk)
- pair_trade    — long {ticker} vs short a named peer (hedged beta)
- basket        — combine {ticker} with 2-3 related names for theme exposure
- option        — use calls/puts for asymmetric payoff (specify which and why)
- avoid         — not worth expressing in any form right now

Recommend:
1. Preferred expression type (one of the above)
2. Rationale — why this is the best vehicle for the thesis
3. If pair_trade: name the short leg and explain the pair logic
4. If option: specify direction, rough tenor, and why options vs stock
5. Risk to the expression choice (e.g. pair trade correlation breaks, option decay)"""

    try:
        resp = _llm().invoke(prompt)
        return resp.content
    except Exception as e:
        return f"[Trade expression error: {e}]"


# ── Step 7: Final verdict ─────────────────────────────────────────────────────

def _parse_verdict(text: str) -> str:
    """Extract the canonical verdict from LLM output. Checks the first line,
    then the whole text. Returns "" if nothing matches (caller treats as
    non-actionable rather than inventing a stance)."""
    lines = text.strip().split("\n")
    # Longest names first so "Add to watchlist" wins over any embedded "Long" etc.
    ordered = sorted(VERDICTS, key=len, reverse=True)
    for scope in (lines[0], text):
        for v in ordered:
            if v.lower() in scope.lower():
                return v
    return ""


def _run_verdict(
    desk_conclusion: str,
    valuation_view: str,
    trade_expression: str,
) -> tuple[str, str]:
    prompt = f"""Based on the three outputs below, give a single final verdict for the Equity L/S desk.

DESK CONCLUSION:
{desk_conclusion}

VALUATION VIEW:
{valuation_view}

TRADE EXPRESSION:
{trade_expression}

Output EXACTLY one of these verdicts (no other text on the first line):
Long | Avoid | Monitor | Trim | Sell | Dig further | Add to watchlist

Then on a new line, provide a one-sentence rationale (max 30 words).

Definitions:
- Long: ready to initiate or add to a position now
- Avoid: not investable — fundamental or valuation issue
- Monitor: thesis is forming but not ready to act yet
- Trim: existing holding, reduce size
- Sell: exit the position
- Dig further: incomplete picture — specific questions need answering first
- Add to watchlist: interesting but not urgent"""

    try:
        resp = _llm(temperature=0.1).invoke(prompt)
        text = resp.content.strip()
        return _parse_verdict(text), text
    except Exception as e:
        return "", f"[Verdict error: {e}]"


# ── Main entry point ──────────────────────────────────────────────────────────

def run(
    ticker: str,
    skip_ta: bool = False,
    debate_rounds: int = 2,
    save_to_kb: bool = True,
) -> DeepDiveResult:
    """
    Run a full single-name deep dive on a ticker.

    Args:
        ticker:        Ticker to analyse (e.g. "NVDA", "0700.HK").
        skip_ta:       If True, skip the TradingAgents run (faster, cheaper — for testing).
        debate_rounds: Bull/bear debate rounds passed to B5 (default 2).
        save_to_kb:    Save the full report to B4 knowledge_base.

    Returns:
        DeepDiveResult with all sections filled.
    """
    ticker = ticker.upper()
    run_date = datetime.now().strftime("%Y-%m-%d")
    result = DeepDiveResult(ticker=ticker, run_date=run_date)

    print(f"\n{'='*60}")
    print(f"A2 Deep Dive: {ticker}  [{run_date}]")
    print(f"{'='*60}")

    # ── 1. Universe gate ──────────────────────────────────────────────────────
    in_scope, tier, reason = _gate(ticker)
    if not in_scope:
        result.verdict = "Avoid"
        result.verdict_detail = f"Out of universe: {reason}"
        result.errors["gate"] = f"Out of universe: {reason}"
        print(f"[A2] REJECTED by universe gate: {reason}")
        return result

    result.tier = tier
    print(f"[A2] Universe gate: PASS (Tier {tier})")

    # ── 2. Screening ─────────────────────────────────────────────────────────
    print("[A2] Running screener (Steps 1–6)...")
    sr = _run_screening(ticker, tier)
    result.screening_context = sr.raw
    result.screening_flags = sr.flags
    screening_block = _format_screening_for_prompt(sr)
    print(f"[A2] Screener done. Score: {sr.composite_score}/100 | {sr.classification}")
    if sr.flags:
        for f in sr.flags:
            print(f"  ⚠️  {f}")

    # Hard filter fail inside screener (different from universe gate)
    if not sr.hard_pass:
        result.verdict = "Avoid"
        result.verdict_detail = f"Failed hard filter: {sr.hard_fail_reason}"
        result.errors["screener"] = sr.hard_fail_reason
        print(f"[A2] Hard filter failed: {sr.hard_fail_reason}")
        return result

    # ── 3. TradingAgents run ──────────────────────────────────────────────────
    if not skip_ta:
        print("[A2] Running B5 TradingAgents pipeline (this takes a few minutes)...")
        from src.desks.equity_ls.infrastructure.b5_trading_agents import pipeline as b5
        ta = b5.run(ticker, debate_rounds=debate_rounds, save_to_kb=save_to_kb)
        result.ta_result = ta
        print("[A2] TradingAgents run complete")
    else:
        print("[A2] Skipping TradingAgents run (skip_ta=True)")
        from src.desks.equity_ls.infrastructure.b5_trading_agents.pipeline import TradingAgentsResult
        result.ta_result = TradingAgentsResult(
            ticker=ticker,
            run_date=run_date,
            investment_plan="[TradingAgents skipped]",
            trader_plan="[TradingAgents skipped]",
        )

    # ── 4. Desk conclusion ────────────────────────────────────────────────────
    print("[A2] Forming desk conclusion...")
    result.desk_conclusion = _run_desk_conclusion(ticker, screening_block, result.ta_result)
    print(f"[A2] Desk conclusion: {len(result.desk_conclusion)} chars")

    # ── 5. Valuation view ─────────────────────────────────────────────────────
    print("[A2] Running valuation view...")
    sector = result.screening_context.get("sector", "")
    result.valuation_view = _run_valuation_view(ticker, screening_block, result.desk_conclusion, sector)
    print(f"[A2] Valuation view: {len(result.valuation_view)} chars")

    # ── 6. Trade expression ───────────────────────────────────────────────────
    print("[A2] Running trade expression...")
    result.trade_expression = _run_trade_expression(ticker, result.desk_conclusion, result.valuation_view)
    print(f"[A2] Trade expression: {len(result.trade_expression)} chars")

    # ── 7. Verdict ────────────────────────────────────────────────────────────
    print("[A2] Producing verdict...")
    result.verdict, result.verdict_detail = _run_verdict(
        result.desk_conclusion, result.valuation_view, result.trade_expression
    )
    print(f"[A2] Verdict: {result.verdict or '(unparsed)'}")

    # ── Save full report to B4 ────────────────────────────────────────────────
    if save_to_kb:
        try:
            from src.desks.equity_ls.infrastructure.b4_knowledge_base import knowledge_base as kb
            full_report = (
                f"# Deep Dive: {ticker} ({run_date})\n\n"
                f"**Tier:** {tier}\n\n"
                f"## Screening Context\n```\n{screening_block}\n```\n\n"
                f"## Desk Conclusion\n{result.desk_conclusion}\n\n"
                f"## Valuation / Upside-Downside\n{result.valuation_view}\n\n"
                f"## Trade Expression\n{result.trade_expression}\n\n"
                f"## Verdict\n{result.verdict_detail}"
            )
            result.report_id = kb.add_report(
                ticker,
                "deep_dive",
                f"Deep Dive {run_date}",
                full_report,
                source="a2_deep_dive",
            )
            print(f"[A2] Saved to B4 (report_id={result.report_id})")
        except Exception as e:
            result.errors["kb_save"] = str(e)

        # ── Decision History / single-writer current_view ──────────────────────
        # A2 owns current_view for tickers it doesn't hold; A4 owns held names.
        # If NVDA is held, this call raises and we fall back to logging A2's
        # output as an input for A4 to weigh — A2 never overrides the
        # portfolio-decision desk's stance on a name you actually own.
        if result.verdict:
            try:
                from src.desks.equity_ls.infrastructure.b4_knowledge_base import decision_history as dh
                try:
                    result.decision_id = dh.record_as_current_view(
                        ticker, "a2", result.verdict, result.verdict_detail,
                        triggered_by="a2_deep_dive",
                    )
                    result.became_current_view = True
                except dh.SingleWriterViolation:
                    result.decision_id = dh.record_decision(
                        ticker, "a2", result.verdict, result.verdict_detail,
                        triggered_by="a2_deep_dive",
                    )
                    result.became_current_view = False
                    print(f"[A2] {ticker} is held — logged as input for A4, did not set current_view")
            except Exception as e:
                result.errors["decision_history"] = str(e)

    print(f"[A2] Done. Errors: {result.errors or 'none'}")
    print(f"{'='*60}\n")
    return result
