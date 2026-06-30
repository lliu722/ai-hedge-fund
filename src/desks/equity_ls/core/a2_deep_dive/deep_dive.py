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

import os
from dataclasses import dataclass, field
from datetime import datetime

from langchain_deepseek import ChatDeepSeek


# ── Output types ──────────────────────────────────────────────────────────────

VERDICTS = {"Long", "Avoid", "Monitor", "Trim", "Sell", "Dig further", "Add to watchlist"}

EXPRESSION_TYPES = {
    "single_stock", "etf", "pair_trade", "basket", "option", "avoid"
}


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
    verdict: str = ""                                           # one of VERDICTS

    # KB report id
    report_id: int | None = None
    errors: dict = field(default_factory=dict)


# ── LLM ──────────────────────────────────────────────────────────────────────

def _llm(temperature: float = 0.2) -> ChatDeepSeek:
    return ChatDeepSeek(
        model="deepseek-chat",
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        temperature=temperature,
    )


# ── Step 1: Universe gate ─────────────────────────────────────────────────────

def _gate(ticker: str) -> tuple[bool, int | None, str]:
    """Returns (in_scope, tier, rejection_reason)."""
    from src.desks.equity_ls.infrastructure.b1_universe.universe import check
    meta = check(ticker)
    return meta.in_scope, meta.tier, meta.rejection_reason


# ── Step 2: Screening context ─────────────────────────────────────────────────
# Louis: add your extra screening checks here.
# Each check should append to `flags` if something is wrong.
# The full `data` dict is passed to the desk conclusion LLM as context.

def _build_screening_context(ticker: str) -> tuple[dict, list[str]]:
    """
    Pull key screening metrics from B2 and flag anything that fails a basic threshold.
    Returns (data_dict, flags_list).

    ADD YOUR EXTRA SCREENING CHECKS BELOW — there is a clearly marked section.
    """
    from src.desks.equity_ls.infrastructure.b2_data_source.data_sources import (
        get_market_data,
        get_internal_scores,
        get_earnings_dates,
    )

    data: dict = {}
    flags: list[str] = []

    # ── Market data ───────────────────────────────────────────────────────────
    md = get_market_data(ticker)
    if "_error" not in md:
        data.update({
            "price":             md.get("price"),
            "market_cap":        md.get("market_cap"),
            "avg_volume_10d":    md.get("avg_volume_10d"),
            "trailing_pe":       md.get("trailing_pe"),
            "forward_pe":        md.get("forward_pe"),
            "price_to_book":     md.get("price_to_book"),
            "ev_to_ebitda":      md.get("ev_to_ebitda"),
            "revenue_growth":    md.get("revenue_growth"),
            "gross_margins":     md.get("gross_margins"),
            "operating_margins": md.get("operating_margins"),
            "profit_margins":    md.get("profit_margins"),
            "free_cash_flow":    md.get("free_cash_flow"),
            "return_on_equity":  md.get("return_on_equity"),
            "debt_to_equity":    md.get("debt_to_equity"),
            "current_ratio":     md.get("current_ratio"),
            "short_percent_float": md.get("short_percent_float"),
            "beta":              md.get("beta"),
            "week52_high":       md.get("week52_high"),
            "week52_low":        md.get("week52_low"),
            "target_mean_price": md.get("target_mean_price"),
            "recommendation":    md.get("recommendation"),
            "analyst_count":     md.get("analyst_count"),
            "sector":            md.get("sector"),
            "industry":          md.get("industry"),
        })

        # Basic liquidity check
        cap = md.get("market_cap") or 0
        vol = md.get("avg_volume_10d") or 0
        if cap < 500_000_000:
            flags.append(f"Micro-cap: market cap ${cap/1e6:.0f}M — liquidity risk")
        if vol < 500_000:
            flags.append(f"Low volume: avg 10d volume {vol:,.0f} — liquidity risk")

        # Basic balance sheet check
        de = md.get("debt_to_equity")
        cr = md.get("current_ratio")
        if de is not None and de > 3.0:
            flags.append(f"High leverage: D/E = {de:.1f}")
        if cr is not None and cr < 0.8:
            flags.append(f"Weak liquidity: current ratio = {cr:.2f}")

        # Negative FCF flag
        fcf = md.get("free_cash_flow")
        if fcf is not None and fcf < 0:
            flags.append(f"Negative FCF: ${fcf/1e6:.0f}M")

    else:
        flags.append(f"Market data unavailable: {md['_error']}")

    # ── Quant scores ──────────────────────────────────────────────────────────
    scores = get_internal_scores(ticker)
    if "_error" not in scores:
        data.update({
            "momentum":        scores.get("momentum"),
            "rsi":             scores.get("rsi"),
            "composite_score": scores.get("composite_score"),
            "quality_score":   scores.get("quality_score"),
            "valuation_score": scores.get("valuation_score"),
            "risk_score":      scores.get("risk_score"),
            "signal":          scores.get("signal"),
        })

        rsi = scores.get("rsi")
        if rsi is not None and rsi > 80:
            flags.append(f"Overbought RSI: {rsi:.1f}")
        if rsi is not None and rsi < 25:
            flags.append(f"Oversold RSI: {rsi:.1f} (potential opportunity or falling knife)")

        risk = scores.get("risk_score")
        if risk is not None and risk > 2.0:
            flags.append(f"High risk score (|beta| proxy): {risk:.2f}")

    # ── Earnings proximity ────────────────────────────────────────────────────
    try:
        earn = get_earnings_dates(ticker)
        next_earnings = earn.get("next_earnings_date")
        if next_earnings:
            data["next_earnings"] = str(next_earnings)
            # Warn if earnings within 2 weeks
            try:
                days_to = (datetime.strptime(str(next_earnings)[:10], "%Y-%m-%d") - datetime.now()).days
                if 0 <= days_to <= 14:
                    flags.append(f"Earnings in {days_to} days — binary event risk")
                data["days_to_earnings"] = days_to
            except Exception:
                pass
    except Exception:
        pass

    # ═════════════════════════════════════════════════════════════════════════
    # ADD YOUR EXTRA SCREENING CHECKS HERE
    # ═════════════════════════════════════════════════════════════════════════
    # Pattern:
    #   value = data.get("some_field")
    #   if value is not None and <condition>:
    #       flags.append("Description of the flag")
    # ═════════════════════════════════════════════════════════════════════════

    return data, flags


def _format_screening_for_prompt(ticker: str, tier: int, data: dict, flags: list[str]) -> str:
    """Format screening context as a readable block for LLM prompts."""
    flag_block = "\n".join(f"⚠️  {f}" for f in flags) if flags else "None"
    return f"""SCREENING CONTEXT — {ticker} (Tier {tier})

Financials:
  Market Cap: ${(data.get('market_cap') or 0)/1e9:.2f}B | Avg Vol 10d: {(data.get('avg_volume_10d') or 0):,.0f}
  P/E TTM: {data.get('trailing_pe', 'N/A')} | P/E Fwd: {data.get('forward_pe', 'N/A')} | EV/EBITDA: {data.get('ev_to_ebitda', 'N/A')}
  Rev Growth: {data.get('revenue_growth', 'N/A')} | Gross Margin: {data.get('gross_margins', 'N/A')} | Op Margin: {data.get('operating_margins', 'N/A')}
  ROE: {data.get('return_on_equity', 'N/A')} | FCF: ${(data.get('free_cash_flow') or 0)/1e6:.0f}M | D/E: {data.get('debt_to_equity', 'N/A')}

Quant Scores:
  Momentum: {data.get('momentum', 'N/A')} | RSI: {data.get('rsi', 'N/A')} | Quality: {data.get('quality_score', 'N/A')}
  Composite: {data.get('composite_score', 'N/A')} | Signal: {data.get('signal', 'N/A')}

Next Earnings: {data.get('next_earnings', 'N/A')} ({data.get('days_to_earnings', '?')} days)
Analyst rec: {data.get('recommendation', 'N/A')} (n={data.get('analyst_count', 0)}) | Target: ${data.get('target_mean_price', 'N/A')}
Short Float: {data.get('short_percent_float', 'N/A')} | Beta: {data.get('beta', 'N/A')}
Sector: {data.get('sector', 'N/A')} | Industry: {data.get('industry', 'N/A')}

Screening Flags:
{flag_block}"""


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

def _run_valuation_view(ticker: str, screening_block: str, desk_conclusion: str) -> str:
    prompt = f"""You are the valuation analyst for the Equity L/S desk. Based on the screening data
and desk conclusion below, produce a valuation and upside/downside view for {ticker}.

{screening_block}

DESK CONCLUSION:
{desk_conclusion}

Produce:
1. Current valuation assessment — cheap / fair / rich / very rich vs history and peers
2. Peer comparison — name 2-3 closest peers and how {ticker} compares on key multiples
3. Historical range — where do current multiples sit vs the name's own 3-5 year range?
4. Base case upside/downside — what is the bull case price target and bear case price?
5. Growth quality — is the growth durable, or are there red flags (one-time items, channel stuff)?
6. Does the upside justify the risk? Answer clearly: Yes / No / Only on weakness"""

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

def _run_verdict(
    desk_conclusion: str,
    valuation_view: str,
    trade_expression: str,
) -> str:
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
        # Extract verdict from first line
        first_line = text.split("\n")[0].strip()
        for v in VERDICTS:
            if v.lower() in first_line.lower():
                return text
        return text  # return as-is if no clean match
    except Exception as e:
        return f"[Verdict error: {e}]"


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
        result.errors["gate"] = f"Out of universe: {reason}"
        print(f"[A2] REJECTED by universe gate: {reason}")
        return result

    result.tier = tier
    print(f"[A2] Universe gate: PASS (Tier {tier})")

    # ── 2. Screening context ──────────────────────────────────────────────────
    print("[A2] Building screening context...")
    data, flags = _build_screening_context(ticker)
    result.screening_context = data
    result.screening_flags = flags
    screening_block = _format_screening_for_prompt(ticker, tier, data, flags)
    print(f"[A2] Screening done. Flags: {len(flags)}")
    if flags:
        for f in flags:
            print(f"  ⚠️  {f}")

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
    result.valuation_view = _run_valuation_view(ticker, screening_block, result.desk_conclusion)
    print(f"[A2] Valuation view: {len(result.valuation_view)} chars")

    # ── 6. Trade expression ───────────────────────────────────────────────────
    print("[A2] Running trade expression...")
    result.trade_expression = _run_trade_expression(ticker, result.desk_conclusion, result.valuation_view)
    print(f"[A2] Trade expression: {len(result.trade_expression)} chars")

    # ── 7. Verdict ────────────────────────────────────────────────────────────
    print("[A2] Producing verdict...")
    result.verdict = _run_verdict(result.desk_conclusion, result.valuation_view, result.trade_expression)
    print(f"[A2] Verdict: {result.verdict.split(chr(10))[0]}")

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
                f"## Verdict\n{result.verdict}"
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

    print(f"[A2] Done. Errors: {result.errors or 'none'}")
    print(f"{'='*60}\n")
    return result
