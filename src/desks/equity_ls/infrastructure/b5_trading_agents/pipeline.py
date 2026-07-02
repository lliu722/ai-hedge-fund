"""
B5 — TradingAgents pipeline (vendored from TauricResearch/TradingAgents, Apache-2.0).

Runs a full 7-agent analysis on a single ticker and returns a structured result:
  1. Fundamentals Analyst   — financial statements, ratios, quality
  2. Market Analyst         — technicals, momentum, trend
  3. News Analyst           — macro + company-specific news
  4. Sentiment Analyst      — news sentiment proxy (no Reddit/StockTwits dep)
  (analysts 1–4 run in parallel)
  5. Bull Researcher        — builds the long case from the 4 reports
  6. Bear Researcher        — builds the short/avoid case
  (bull/bear alternate for N rounds, default 2)
  7. Research Manager       — judges debate → investment plan
  8. Trader                 — converts plan to concrete proposal

All data comes from B2 (data_sources). Outputs saved to B4 (knowledge_base).

Attribution: prompts adapted from TauricResearch/TradingAgents (Apache-2.0).
https://github.com/TauricResearch/TradingAgents
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

from src.desks.equity_ls.infrastructure.llm import get_llm as _llm


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class TradingAgentsResult:
    ticker: str
    run_date: str

    # 4 analyst reports
    fundamentals_report: str = ""
    market_report: str = ""
    news_report: str = ""
    sentiment_report: str = ""

    # debate
    debate_history: str = ""
    bull_history: str = ""
    bear_history: str = ""

    # conclusions
    investment_plan: str = ""   # Research Manager output
    trader_plan: str = ""       # Trader output

    errors: dict = field(default_factory=dict)


# ── Data helpers (B2 adapters) ────────────────────────────────────────────────

def _get_market_context(ticker: str) -> str:
    """Pull price + valuation data from B2 and format for prompt."""
    try:
        from src.desks.equity_ls.infrastructure.b2_data_source.data_sources import get_market_data
        d = get_market_data(ticker)
        if "_error" in d:
            return f"[Market data unavailable: {d['_error']}]"
        return (
            f"Ticker: {ticker} ({d.get('name', '')})\n"
            f"Sector: {d.get('sector', 'N/A')} | Industry: {d.get('industry', 'N/A')}\n"
            f"Price: ${d.get('price', 'N/A')} | Change: {d.get('change_pct', 'N/A')}%\n"
            f"52W High: ${d.get('week52_high', 'N/A')} | 52W Low: ${d.get('week52_low', 'N/A')}\n"
            f"Market Cap: ${(d.get('market_cap') or 0):,.0f} | Beta: {d.get('beta', 'N/A')}\n"
            f"P/E (TTM): {d.get('trailing_pe', 'N/A')} | P/E (Fwd): {d.get('forward_pe', 'N/A')}\n"
            f"P/B: {d.get('price_to_book', 'N/A')} | P/S: {d.get('price_to_sales', 'N/A')}\n"
            f"EV/EBITDA: {d.get('ev_to_ebitda', 'N/A')} | EV/Rev: {d.get('ev_to_revenue', 'N/A')}\n"
            f"Revenue: ${(d.get('revenue') or 0):,.0f} | Rev Growth: {d.get('revenue_growth', 'N/A')}\n"
            f"Gross Margin: {d.get('gross_margins', 'N/A')} | Op Margin: {d.get('operating_margins', 'N/A')}\n"
            f"Net Margin: {d.get('profit_margins', 'N/A')} | EBITDA: ${(d.get('ebitda') or 0):,.0f}\n"
            f"FCF: ${(d.get('free_cash_flow') or 0):,.0f} | ROE: {d.get('return_on_equity', 'N/A')}\n"
            f"EPS (TTM): {d.get('eps_trailing', 'N/A')} | EPS (Fwd): {d.get('eps_forward', 'N/A')}\n"
            f"Debt/Equity: {d.get('debt_to_equity', 'N/A')} | Current Ratio: {d.get('current_ratio', 'N/A')}\n"
            f"Short Float: {d.get('short_percent_float', 'N/A')} | Analyst Target: ${d.get('target_mean_price', 'N/A')}\n"
            f"Recommendation: {d.get('recommendation', 'N/A')} (n={d.get('analyst_count', 0)})\n"
            f"Dividend Yield: {d.get('dividend_yield', 'N/A')}"
        )
    except Exception as e:
        return f"[Market data error: {e}]"


def _get_scores_context(ticker: str) -> str:
    """Pull internal quant scores from B2."""
    try:
        from src.desks.equity_ls.infrastructure.b2_data_source.data_sources import get_internal_scores
        s = get_internal_scores(ticker)
        if "_error" in s:
            return f"[Scores unavailable: {s['_error']}]"
        return (
            f"Momentum (12-1m): {s.get('momentum', 'N/A')}\n"
            f"RSI (14d): {s.get('rsi', 'N/A')}\n"
            f"Valuation Score: {s.get('valuation_score', 'N/A')}\n"
            f"Quality Score: {s.get('quality_score', 'N/A')}\n"
            f"Composite Score: {s.get('composite_score', 'N/A')}\n"
            f"Signal: {s.get('signal', 'N/A')}"
        )
    except Exception as e:
        return f"[Scores error: {e}]"


def _get_news_context(ticker: str, n: int = 8) -> str:
    """Pull recent news from B2."""
    try:
        from src.desks.equity_ls.infrastructure.b2_data_source.data_sources import get_news
        articles = get_news(ticker, days_back=7)[:n]
        if not articles:
            return "No recent news found."
        lines = []
        for a in articles:
            lines.append(f"• {a.get('title', '')}")
            snippet = (a.get("content") or "")[:200].strip()
            if snippet:
                lines.append(f"  {snippet}")
        return "\n".join(lines)
    except Exception as e:
        return f"[News error: {e}]"


def _get_sec_context(ticker: str) -> str:
    """Pull recent SEC filings from B2 (flat list of {form, filed, ...} dicts)."""
    try:
        from src.desks.equity_ls.infrastructure.b2_data_source.data_sources import get_sec_filings
        filings = get_sec_filings(ticker)
        if not filings:
            return "No filings found."
        if "_error" in filings[0]:
            return f"[SEC filings unavailable: {filings[0]['_error']}]"
        return "\n".join(
            f"{f.get('form', '?')}: filed {f.get('filed', '?')}" for f in filings[:6]
        )
    except Exception as e:
        return f"[SEC filings error: {e}]"


# ── Analyst runners ───────────────────────────────────────────────────────────

def _run_fundamentals_analyst(ticker: str, market_ctx: str, sec_ctx: str) -> str:
    """Prompt adapted from TauricResearch/TradingAgents fundamentals_analyst.py (Apache-2.0)."""
    prompt = f"""You are a researcher tasked with analyzing fundamental information about a company.
Write a comprehensive report covering financial documents, company profile, basic financials, and financial history.
Include as much detail as possible. Provide specific, actionable insights with supporting evidence.
Append a Markdown table at the end organizing key points.

COMPANY: {ticker}
DATE: {datetime.now().strftime('%Y-%m-%d')}

MARKET & VALUATION DATA:
{market_ctx}

RECENT SEC FILINGS:
{sec_ctx}

Analyze the fundamentals thoroughly. Focus on revenue quality, margin trends, balance sheet health,
free cash flow generation, and whether the current valuation is justified by fundamentals."""

    try:
        resp = _llm(temperature=0.2).invoke(prompt)
        return resp.content
    except Exception as e:
        return f"[Fundamentals analyst error: {e}]"


def _run_market_analyst(ticker: str, market_ctx: str, scores_ctx: str) -> str:
    """Prompt adapted from TauricResearch/TradingAgents market_analyst.py (Apache-2.0)."""
    prompt = f"""You are a trading assistant tasked with analyzing financial markets.
Analyze the technical picture for {ticker}. Evaluate momentum, trend direction, support/resistance,
and whether technical conditions are constructive or deteriorating.
Select the most relevant indicators and provide specific, actionable insights.
Append a Markdown table at the end organizing key points.

COMPANY: {ticker}
DATE: {datetime.now().strftime('%Y-%m-%d')}

MARKET DATA & PRICE ACTION:
{market_ctx}

INTERNAL QUANT SCORES:
{scores_ctx}

Write a detailed, nuanced report of the technical trends. Comment on:
- Trend direction and strength
- Momentum (RSI, composite score, 12-1m momentum)
- Valuation vs price action
- Short interest and positioning
- Whether technical setup supports a long, short, or neutral stance"""

    try:
        resp = _llm(temperature=0.2).invoke(prompt)
        return resp.content
    except Exception as e:
        return f"[Market analyst error: {e}]"


def _run_news_analyst(ticker: str, news_ctx: str) -> str:
    """Prompt adapted from TauricResearch/TradingAgents news_analyst.py (Apache-2.0)."""
    prompt = f"""You are a news researcher tasked with analyzing recent news and trends.
Write a comprehensive report on the current state of affairs relevant to trading {ticker}.
Provide specific, actionable insights with supporting evidence.
Append a Markdown table at the end organizing key points.

COMPANY: {ticker}
DATE: {datetime.now().strftime('%Y-%m-%d')}

RECENT NEWS (last 7 days):
{news_ctx}

Analyze:
- Key company-specific developments (earnings, guidance, deals, management changes)
- Sector/macro tailwinds or headwinds
- Regulatory or geopolitical risks
- Market sentiment around the name
- How the news changes (or confirms) the investment case"""

    try:
        resp = _llm(temperature=0.2).invoke(prompt)
        return resp.content
    except Exception as e:
        return f"[News analyst error: {e}]"


def _run_sentiment_analyst(ticker: str, news_ctx: str, market_ctx: str) -> str:
    """Prompt adapted from TauricResearch/TradingAgents sentiment_analyst.py (Apache-2.0).
    Uses news sentiment as proxy (no Reddit/StockTwits dependency)."""
    prompt = f"""You are a sentiment analyst. Based on recent news and market data, assess the sentiment
around {ticker} from multiple angles: institutional, retail, and market-implied.

COMPANY: {ticker}
DATE: {datetime.now().strftime('%Y-%m-%d')}

RECENT NEWS:
{news_ctx}

MARKET DATA (short interest, analyst rec, target):
{market_ctx}

Produce a sentiment report covering:
- Overall sentiment band: BULLISH / SLIGHTLY BULLISH / NEUTRAL / SLIGHTLY BEARISH / BEARISH
- Sentiment score: -1.0 (max bearish) to +1.0 (max bullish)
- Confidence: LOW / MEDIUM / HIGH
- Institutional sentiment (analyst upgrades/downgrades, target changes)
- News tone (positive/negative headline momentum)
- Short interest signal (crowded short = contrarian positive, or confirming negative)
- Key sentiment drivers

End with a Markdown table summarizing: Dimension | Signal | Confidence"""

    try:
        resp = _llm(temperature=0.2).invoke(prompt)
        return resp.content
    except Exception as e:
        return f"[Sentiment analyst error: {e}]"


# ── Bull / Bear debate ────────────────────────────────────────────────────────

def _run_bull_round(
    ticker: str,
    reports: dict,
    history: str,
    bear_argument: str,
) -> str:
    """Prompt adapted from TauricResearch/TradingAgents bull_researcher.py (Apache-2.0)."""
    prompt = f"""You are a Bull Analyst advocating for investing in {ticker}.
Build a strong, evidence-based case emphasising growth potential, competitive advantages, and positive indicators.
Counter the bear's arguments with specific data.

Resources:
Market report: {reports['market']}
Sentiment report: {reports['sentiment']}
News report: {reports['news']}
Fundamentals report: {reports['fundamentals']}
Debate history: {history}
Last bear argument: {bear_argument}

Deliver a compelling bull argument. Be specific and engage directly with the bear's points."""

    try:
        resp = _llm(temperature=0.5).invoke(prompt)
        return f"Bull Analyst: {resp.content}"
    except Exception as e:
        return f"Bull Analyst: [error: {e}]"


def _run_bear_round(
    ticker: str,
    reports: dict,
    history: str,
    bull_argument: str,
) -> str:
    """Prompt adapted from TauricResearch/TradingAgents bear_researcher.py (Apache-2.0)."""
    prompt = f"""You are a Bear Analyst arguing against investing in {ticker}.
Build a rigorous case highlighting risks, weaknesses, and negative indicators.
Counter the bull's arguments with specific data.

Resources:
Market report: {reports['market']}
Sentiment report: {reports['sentiment']}
News report: {reports['news']}
Fundamentals report: {reports['fundamentals']}
Debate history: {history}
Last bull argument: {bull_argument}

Deliver a compelling bear argument. Be specific and engage directly with the bull's points."""

    try:
        resp = _llm(temperature=0.5).invoke(prompt)
        return f"Bear Analyst: {resp.content}"
    except Exception as e:
        return f"Bear Analyst: [error: {e}]"


# ── Research Manager ──────────────────────────────────────────────────────────

def _run_research_manager(ticker: str, debate_history: str) -> str:
    """Prompt adapted from TauricResearch/TradingAgents research_manager.py (Apache-2.0)."""
    prompt = f"""As the Research Manager and debate facilitator for {ticker}, evaluate this debate
and deliver a clear, actionable investment plan for the trader.

Rating scale (use exactly one):
- Buy: Strong conviction in the bull thesis
- Overweight: Constructive; recommend gradually increasing exposure
- Hold: Balanced view; maintain current position
- Underweight: Cautious; recommend trimming
- Sell: Strong conviction in the bear thesis

Commit to a clear stance. Reserve Hold only when evidence is genuinely balanced.

Debate History:
{debate_history}

Produce:
1. Rating (one of the five above)
2. Key reasons for rating (3-5 bullet points)
3. Main risks to your view
4. Investment plan for the trader"""

    try:
        resp = _llm(temperature=0.2).invoke(prompt)
        return resp.content
    except Exception as e:
        return f"[Research manager error: {e}]"


# ── Trader ────────────────────────────────────────────────────────────────────

def _run_trader(ticker: str, investment_plan: str) -> str:
    """Prompt adapted from TauricResearch/TradingAgents trader.py (Apache-2.0)."""
    prompt = f"""You are a trading agent making a concrete investment decision on {ticker}.
Based on the investment plan below, produce a specific transaction proposal.

Investment Plan:
{investment_plan}

Your proposal must include:
1. Action: BUY / SELL / HOLD / AVOID
2. Conviction: HIGH / MEDIUM / LOW
3. Suggested position sizing note (relative: core / satellite / trim / avoid)
4. Entry consideration (at market / on weakness / wait for catalyst)
5. Key risk to monitor
6. One-line trade rationale (for the trade journal)

Note: final sizing is set by pm_risk, not you. Focus on the direction and conviction."""

    try:
        resp = _llm(temperature=0.2).invoke(prompt)
        return resp.content
    except Exception as e:
        return f"[Trader error: {e}]"


# ── Signal extraction ─────────────────────────────────────────────────────────

def _extract_signal(trader_plan: str) -> str:
    """
    Best-effort BUY/SELL/AVOID/HOLD from the trader's proposal.
    Prefers an explicit "Action: X" line; falls back to the first whole-word
    match in the text (word boundaries — "BUYBACK" doesn't count). HOLD default.
    """
    text = trader_plan.upper()
    m = re.search(r"ACTION\s*[:\-]\s*\**\s*(BUY|SELL|AVOID|HOLD)\b", text)
    if not m:
        m = re.search(r"\b(BUY|SELL|AVOID|HOLD)\b", text)
    return m.group(1) if m else "HOLD"


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run(ticker: str, debate_rounds: int = 2, save_to_kb: bool = True) -> TradingAgentsResult:
    """
    Run the full TradingAgents pipeline on a single ticker.

    Args:
        ticker:        The ticker to analyse (e.g. "NVDA", "0700.HK").
        debate_rounds: Bull/bear debate iterations (default 2).
        save_to_kb:    If True, save all 8 agent outputs to B4 knowledge_base.

    Returns:
        TradingAgentsResult with all reports and conclusions.
    """
    ticker = ticker.upper()
    run_date = datetime.now().strftime("%Y-%m-%d")
    result = TradingAgentsResult(ticker=ticker, run_date=run_date)

    print(f"[B5] Starting TradingAgents run: {ticker} ({run_date})")

    # ── Step 1: Fetch all data in parallel ──────────────────────────────────
    print("[B5] Fetching data...")
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_market  = ex.submit(_get_market_context, ticker)
        f_scores  = ex.submit(_get_scores_context, ticker)
        f_news    = ex.submit(_get_news_context, ticker)
        f_sec     = ex.submit(_get_sec_context, ticker)

        market_ctx  = f_market.result()
        scores_ctx  = f_scores.result()
        news_ctx    = f_news.result()
        sec_ctx     = f_sec.result()

    # ── Step 2: Run 4 analysts in parallel ──────────────────────────────────
    print("[B5] Running 4 analysts in parallel...")
    analyst_futures = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        analyst_futures["fundamentals"] = ex.submit(_run_fundamentals_analyst, ticker, market_ctx, sec_ctx)
        analyst_futures["market"]       = ex.submit(_run_market_analyst, ticker, market_ctx, scores_ctx)
        analyst_futures["news"]         = ex.submit(_run_news_analyst, ticker, news_ctx)
        analyst_futures["sentiment"]    = ex.submit(_run_sentiment_analyst, ticker, news_ctx, market_ctx)

        for name, fut in analyst_futures.items():
            try:
                report = fut.result(timeout=120)
                setattr(result, f"{name}_report", report)
                print(f"[B5]   ✓ {name} analyst done ({len(report)} chars)")
            except Exception as e:
                result.errors[name] = str(e)
                print(f"[B5]   ✗ {name} analyst failed: {e}")

    reports = {
        "fundamentals": result.fundamentals_report,
        "market":       result.market_report,
        "news":         result.news_report,
        "sentiment":    result.sentiment_report,
    }

    # ── Step 3: Bull / Bear debate ───────────────────────────────────────────
    print(f"[B5] Running bull/bear debate ({debate_rounds} rounds)...")
    history = ""
    bull_history = ""
    bear_history = ""
    current_bear = ""

    for round_num in range(debate_rounds):
        bull_arg = _run_bull_round(ticker, reports, history, current_bear)
        history += f"\n{bull_arg}"
        bull_history += f"\n{bull_arg}"
        print(f"[B5]   Round {round_num+1} bull done")

        bear_arg = _run_bear_round(ticker, reports, history, bull_arg)
        history += f"\n{bear_arg}"
        bear_history += f"\n{bear_arg}"
        current_bear = bear_arg
        print(f"[B5]   Round {round_num+1} bear done")

    result.debate_history = history.strip()
    result.bull_history   = bull_history.strip()
    result.bear_history   = bear_history.strip()

    # ── Step 4: Research Manager ─────────────────────────────────────────────
    print("[B5] Research Manager judging...")
    result.investment_plan = _run_research_manager(ticker, result.debate_history)
    print(f"[B5]   ✓ investment plan ({len(result.investment_plan)} chars)")

    # ── Step 5: Trader ───────────────────────────────────────────────────────
    print("[B5] Trader producing proposal...")
    result.trader_plan = _run_trader(ticker, result.investment_plan)
    print(f"[B5]   ✓ trader plan ({len(result.trader_plan)} chars)")

    # ── Step 6: Save to B4 ───────────────────────────────────────────────────
    if save_to_kb:
        try:
            from src.desks.equity_ls.infrastructure.b4_knowledge_base import knowledge_base as kb

            agents_to_save = [
                ("fundamentals_analyst", result.fundamentals_report),
                ("market_analyst",       result.market_report),
                ("news_analyst",         result.news_report),
                ("sentiment_analyst",    result.sentiment_report),
                ("bull_researcher",      result.bull_history),
                ("bear_researcher",      result.bear_history),
                ("research_manager",     result.investment_plan),
                ("trader",               result.trader_plan),
            ]
            signal = _extract_signal(result.trader_plan)

            for agent_name, reasoning in agents_to_save:
                kb.add_agent_output(ticker, agent_name, signal, reasoning)

            # Also save full run as a deep_dive report in B4
            full_report = (
                f"# TradingAgents Deep Dive: {ticker} ({run_date})\n\n"
                f"## Fundamentals\n{result.fundamentals_report}\n\n"
                f"## Market / Technical\n{result.market_report}\n\n"
                f"## News\n{result.news_report}\n\n"
                f"## Sentiment\n{result.sentiment_report}\n\n"
                f"## Bull/Bear Debate\n{result.debate_history}\n\n"
                f"## Investment Plan (Research Manager)\n{result.investment_plan}\n\n"
                f"## Trader Proposal\n{result.trader_plan}"
            )
            kb.add_report(
                ticker,
                "deep_dive",
                f"TradingAgents Run {run_date}",
                full_report,
                source="b5_pipeline",
            )
            print(f"[B5] Saved to B4 knowledge base")
        except Exception as e:
            result.errors["kb_save"] = str(e)
            print(f"[B5] KB save failed: {e}")

    print(f"[B5] Done. Errors: {result.errors or 'none'}")
    return result
