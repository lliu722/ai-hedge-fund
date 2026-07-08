"""
A3 — Earnings / Catalyst Response.

Answers: "Did this event change anything important?" — fast and cheap by
design. Not every earnings print or headline needs a full A2 deep dive
(TradingAgents' 8 agents + 6-step pipeline); A3 exists specifically so most
events get a quick, single-LLM-call judgment, and only the minority that
actually threaten or improve the thesis escalate to a full rerun.

Three event types, one shared judgment pipeline:
  earnings_preview  — before the print: consensus setup, what's priced in
  earnings_review    — after the print: does the result confirm or break thesis
  catalyst           — anything else material: M&A, lawsuits, regulation,
                        product launches, guidance changes, analyst days

Every run does, in order:
  1. Dedupe check      — don't reprocess the same ticker/event class within
                          a window (default 1 day) unless forced. Prevents
                          earnings-season spam (audit finding #8).
  2. Thesis impact      — Improves / Confirms / Weakens / Breaks / Unclear,
                          via one LLM call against the current KB thesis.
  3. Read-through        — which peers does this event actually implicate
                          (shared peer map from A5).
  4. Rerun decision      — Weakens/Breaks (or explicit force) escalates to a
                          full A2 deep dive, capped by a daily budget so
                          earnings season can't fire unbounded TA runs.
  5. Record              — always logs to Decision History via
                          record_decision() (source="a3"). A3 NEVER sets
                          current_view directly — see decision_history.py's
                          single-writer rule. If it triggers A2, A2's own run
                          is what may update current_view.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.desks.equity_ls.infrastructure.llm import get_llm as _llm

EVENT_TYPES = {"earnings_preview", "earnings_review", "catalyst"}
THESIS_IMPACTS = {"Improves", "Confirms", "Weakens", "Breaks", "Unclear"}

# Daily cap on A3-triggered A2 reruns. Earnings season can put 15-20 holdings'
# events in the same window; each full A2 run is ~15-20 LLM calls (B5's 4
# analysts + debate + manager + trader, plus A2's own 4 calls). Uncapped, one
# bad morning could fire the whole book through TradingAgents at once.
DEFAULT_DAILY_RERUN_BUDGET = 5

# Don't reprocess the same ticker for the same event type within this window
# unless force=True. Prevents duplicate processing if the monitor and a
# manual trigger both fire on the same event.
DEFAULT_DEDUPE_DAYS = 1


@dataclass
class CatalystResult:
    ticker: str
    event_type: str
    run_date: str

    skipped: bool = False
    skip_reason: str = ""

    summary: str = ""              # the LLM's read of the event
    thesis_impact: str = ""        # one of THESIS_IMPACTS ("" if unparseable)
    read_through: list[str] = field(default_factory=list)   # peer tickers implicated
    read_through_note: str = ""
    action: str = ""               # Hold | Add | Trim | Sell | Monitor | Deep Dive | Update Thesis

    deep_dive_triggered: bool = False
    deep_dive_result: object = None   # DeepDiveResult, if triggered

    decision_id: int | None = None
    errors: dict = field(default_factory=dict)


# ── Dedupe / budget (pure logic — no LLM, no network) ─────────────────────────

def _recently_processed(ticker: str, event_type: str, window_days: int) -> bool:
    """True if this ticker already had an A3 decision of this event_type
    within `window_days`."""
    from src.desks.equity_ls.infrastructure.b4_knowledge_base import decision_history as dh

    for d in dh.get_decision_history(ticker, source="a3"):
        if d["triggered_by"] != event_type:
            continue
        try:
            age_days = (datetime.now() - datetime.strptime(d["created_at"][:10], "%Y-%m-%d")).days
        except ValueError:
            continue
        if age_days < window_days:
            return True
    return False


def _reruns_today() -> int:
    """Count of A3-triggered A2 reruns logged today, across all tickers —
    the daily budget is portfolio-wide, not per-ticker."""
    from src.desks.equity_ls.infrastructure.b4_knowledge_base import decision_history as dh

    today = datetime.now().strftime("%Y-%m-%d")
    with dh._db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM decisions "
            "WHERE source='a3' AND triggered_by LIKE 'rerun:%' AND created_at LIKE ?",
            (f"{today}%",),
        ).fetchone()
    return row[0] if row else 0


def budget_remaining(daily_budget: int = DEFAULT_DAILY_RERUN_BUDGET) -> int:
    """How many more A3-triggered A2 reruns are allowed today."""
    return max(0, daily_budget - _reruns_today())


# ── Context gathering ──────────────────────────────────────────────────────────

def _get_earnings_context(ticker: str) -> dict:
    from src.desks.equity_ls.infrastructure.b2_data_source.data_sources import get_earnings_dates
    try:
        return get_earnings_dates(ticker)
    except Exception as e:
        return {"_error": str(e)}


def _get_news_context(ticker: str, days_back: int = 3, n: int = 8) -> str:
    from src.desks.equity_ls.infrastructure.b2_data_source.data_sources import get_news
    try:
        articles = get_news(ticker, days_back=days_back)[:n]
        if not articles or "_error" in (articles[0] if articles else {}):
            return "No recent news found."
        lines = []
        for a in articles:
            lines.append(f"• {a.get('title', '')}")
            if a.get("snippet"):
                lines.append(f"  {a['snippet'][:200]}")
        return "\n".join(lines)
    except Exception as e:
        return f"[News error: {e}]"


def _get_price_reaction(ticker: str) -> str:
    from src.desks.equity_ls.infrastructure.b2_data_source.data_sources import get_market_data
    try:
        d = get_market_data(ticker)
        if "_error" in d:
            return "N/A"
        chg = d.get("change_pct")
        price = d.get("price")
        return f"${price} ({chg:+.1f}% today)" if chg is not None and price else f"${price}" if price else "N/A"
    except Exception:
        return "N/A"


def _get_current_thesis(ticker: str) -> str:
    from src.desks.equity_ls.infrastructure.b4_knowledge_base import knowledge_base as kb
    try:
        thesis = kb.get_current_thesis(ticker)
        return thesis or "[No saved thesis for this ticker.]"
    except Exception:
        return "[Thesis lookup failed.]"


# ── LLM judgment (one call — this is what keeps A3 cheap) ────────────────────

def _judge_event(
    ticker: str,
    event_type: str,
    event_description: str,
    thesis: str,
    news_block: str,
    price_reaction: str,
    earnings_ctx: dict,
) -> tuple[str, str, str]:
    """Returns (summary, thesis_impact, action) in one LLM call."""

    if event_type == "earnings_preview":
        context_block = (
            f"Next earnings date: {earnings_ctx.get('earnings_date', 'N/A')}\n"
            f"Consensus EPS estimate: {earnings_ctx.get('eps_estimate', 'N/A')}\n"
            f"Consensus revenue estimate: {earnings_ctx.get('revenue_estimate', 'N/A')}\n"
            f"Recent news:\n{news_block}"
        )
        task = (
            "This is an EARNINGS PREVIEW. Summarise what the market is pricing in, "
            "the key questions for this print, and the setup (crowded long, low bar, high bar, etc.)."
        )
    elif event_type == "earnings_review":
        context_block = (
            f"Reported results / guidance (as supplied):\n{event_description or '[not supplied]'}\n"
            f"Price reaction: {price_reaction}\n"
            f"Recent news:\n{news_block}"
        )
        task = (
            "This is an EARNINGS REVIEW. Summarise what was reported, how it compares to "
            "expectations, management tone, and whether the print confirms or challenges the thesis."
        )
    else:  # catalyst
        context_block = (
            f"Event: {event_description or '[not supplied]'}\n"
            f"Price reaction: {price_reaction}\n"
            f"Recent news:\n{news_block}"
        )
        task = (
            "This is a CATALYST EVENT (M&A, lawsuit, regulation, product launch, guidance change, "
            "or other material news). Summarise what happened and why it matters."
        )

    prompt = f"""You are the Equity L/S desk's catalyst response analyst for {ticker}.
{task}

CURRENT SAVED THESIS:
{thesis}

CONTEXT:
{context_block}

Respond in exactly this format:

SUMMARY: <2-4 sentences on what happened / what's being priced in>
THESIS_IMPACT: <one of: Improves, Confirms, Weakens, Breaks, Unclear>
ACTION: <one of: Hold, Add, Trim, Sell, Monitor, Deep Dive, Update Thesis>

Be decisive. Reserve "Unclear" only for genuinely ambiguous cases, and "Deep Dive" only
when the event is significant enough to warrant a full multi-agent research rerun
(not for routine news)."""

    try:
        resp = _llm(temperature=0.2).invoke(prompt)
        text = resp.content.strip()
        summary = ""
        impact = ""
        action = ""
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("SUMMARY:"):
                summary = line.split(":", 1)[1].strip()
            elif line.upper().startswith("THESIS_IMPACT:"):
                raw = line.split(":", 1)[1].strip()
                impact = next((v for v in THESIS_IMPACTS if v.lower() in raw.lower()), "")
            elif line.upper().startswith("ACTION:"):
                action = line.split(":", 1)[1].strip()
        return summary or text, impact, action
    except Exception as e:
        return f"[Catalyst judgment error: {e}]", "", ""


def _read_through(ticker: str, sector: str) -> tuple[list[str], str]:
    """Which peers does this event plausibly implicate. Cheap — reuses the
    shared peer map, no LLM call (the LLM already commented on the ticker
    itself; read-through is just 'who else is exposed to the same thing')."""
    from src.desks.equity_ls.core.a5_relative_value.peers import get_peers
    peers = get_peers(ticker, sector)
    note = f"Same theme/supply-chain exposure: {', '.join(peers)}" if peers else "No mapped peers."
    return peers, note


# ── Main entry point ──────────────────────────────────────────────────────────

def run(
    ticker: str,
    event_type: str,
    event_description: str = "",
    force: bool = False,
    dedupe_days: int = DEFAULT_DEDUPE_DAYS,
    daily_rerun_budget: int = DEFAULT_DAILY_RERUN_BUDGET,
) -> CatalystResult:
    """
    Run A3 catalyst response for a ticker.

    Args:
        ticker:             Ticker to analyse.
        event_type:         One of EVENT_TYPES.
        event_description:  Free text describing the event (reported numbers,
                             M&A details, lawsuit summary, etc.) — required
                             context for earnings_review/catalyst, optional
                             for earnings_preview (which pulls consensus data
                             itself).
        force:              Skip the dedupe check.
        dedupe_days:        Reprocessing window (default 1 day).
        daily_rerun_budget: Max A3-triggered A2 reruns per day, portfolio-wide.

    Returns:
        CatalystResult.
    """
    ticker = ticker.upper()
    run_date = datetime.now().strftime("%Y-%m-%d")
    result = CatalystResult(ticker=ticker, event_type=event_type, run_date=run_date)

    if event_type not in EVENT_TYPES:
        result.skipped = True
        result.skip_reason = f"Unknown event_type '{event_type}' — must be one of {EVENT_TYPES}"
        return result

    print(f"[A3] {ticker} — {event_type}")

    # ── Universe gate ──────────────────────────────────────────────────────────
    from src.desks.equity_ls.infrastructure.b1_universe.universe import check as universe_check
    meta = universe_check(ticker)
    if not meta.in_scope:
        result.skipped = True
        result.skip_reason = f"Out of universe: {meta.rejection_reason}"
        print(f"[A3] {ticker} rejected: {result.skip_reason}")
        return result

    # ── Dedupe ────────────────────────────────────────────────────────────────
    if not force and _recently_processed(ticker, event_type, dedupe_days):
        result.skipped = True
        result.skip_reason = f"Already processed {event_type} for {ticker} within {dedupe_days}d"
        print(f"[A3] {ticker} skipped: {result.skip_reason}")
        return result

    # ── Gather context ───────────────────────────────────────────────────────
    thesis = _get_current_thesis(ticker)
    news_block = _get_news_context(ticker)
    price_reaction = _get_price_reaction(ticker)
    earnings_ctx = _get_earnings_context(ticker) if event_type == "earnings_preview" else {}

    # ── Judge ─────────────────────────────────────────────────────────────────
    result.summary, result.thesis_impact, result.action = _judge_event(
        ticker, event_type, event_description, thesis, news_block, price_reaction, earnings_ctx,
    )
    print(f"[A3] {ticker} impact={result.thesis_impact or '?'} action={result.action or '?'}")

    # ── Read-through ─────────────────────────────────────────────────────────
    from src.desks.equity_ls.core.screener import screener as _screener_mod
    sector = ""
    try:
        sr = _screener_mod.run(ticker, tier=meta.tier or 4)
        sector = sr.sector
    except Exception:
        pass
    result.read_through, result.read_through_note = _read_through(ticker, sector)

    # ── Rerun decision ───────────────────────────────────────────────────────
    material = result.thesis_impact in ("Weakens", "Breaks") or result.action == "Deep Dive"
    if material:
        remaining = budget_remaining(daily_rerun_budget)
        if remaining <= 0:
            print(f"[A3] {ticker} warrants a rerun but daily budget ({daily_rerun_budget}) is exhausted")
            result.errors["budget"] = "Daily A2 rerun budget exhausted — flagged for manual review"
        else:
            print(f"[A3] {ticker} → triggering A2 deep dive ({remaining} reruns left today)")
            try:
                from src.desks.equity_ls.core.a2_deep_dive import deep_dive
                result.deep_dive_result = deep_dive.run(ticker, save_to_kb=True)
                result.deep_dive_triggered = True
            except Exception as e:
                result.errors["deep_dive"] = str(e)

    # ── Record (A3 never sets current_view — see decision_history.py) ────────
    try:
        from src.desks.equity_ls.infrastructure.b4_knowledge_base import decision_history as dh
        triggered_by = f"rerun:{event_type}" if result.deep_dive_triggered else event_type
        result.decision_id = dh.record_decision(
            ticker, "a3",
            verdict=result.action or "Monitor",
            rationale=result.summary,
            triggered_by=triggered_by,
        )
    except Exception as e:
        result.errors["decision_history"] = str(e)

    print(f"[A3] {ticker} done. Errors: {result.errors or 'none'}")
    return result
