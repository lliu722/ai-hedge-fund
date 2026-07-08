"""
A4 — Portfolio Decision Support.

Answers: "What should I do with what I already own?" A4 is the sole writer
of current_view for held tickers (see decision_history.py's single-writer
rule) — A2/A3 can only log inputs once a name is held; A4 is what actually
decides the desk's live stance on it.

HARD BOUNDARY (audit finding #4 — read before touching this file):
A4 gives DIRECTION ONLY — Hold / Add / Trim / Sell / Rotate / Deep Dive
Further. It NEVER outputs a share count, dollar amount, or target weight.
Sizing is pm_risk's job, and pm_risk doesn't exist yet — until it does, A4's
output goes to Louis via Telegram and a human sizes it. This is enforced
structurally: PositionReview has no size/weight field to put a number in,
and the LLM prompt explicitly forbids sizing language. Don't add one.

Two entry points:
  review_position(ticker)  — single-name thesis-health check. Pulls holding
                              state, saved thesis, recent A2/A3 signals, a
                              fresh screener score, and risk flags; produces
                              a direction + rationale; becomes current_view.
  review_portfolio()       — portfolio-wide exposure scan (concentration,
                              currency books) + a strategy note on which
                              themes look strong/weak in aggregate. Read-only
                              — does not touch current_view for any ticker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.desks.equity_ls.infrastructure.llm import get_llm as _llm

DIRECTIONS = {"Hold", "Add", "Trim", "Sell", "Rotate", "Deep Dive Further"}


@dataclass
class PositionReview:
    ticker: str
    run_date: str

    is_held: bool = False
    skipped: bool = False
    skip_reason: str = ""

    holding_snapshot: dict = field(default_factory=dict)   # shares, avg_cost, pnl_pct
    thesis: str = ""
    recent_signals: list[dict] = field(default_factory=list)   # A2/A3 decisions since thesis was set
    screener_score: float | None = None
    screener_classification: str = ""
    risk_flags: list = field(default_factory=list)   # RiskFlag objects from core/risk/checks.py

    assessment: str = ""       # LLM narrative
    direction: str = ""        # one of DIRECTIONS ("" if unparseable)

    decision_id: int | None = None
    became_current_view: bool = False
    errors: dict = field(default_factory=dict)


@dataclass
class PortfolioReview:
    run_date: str
    total_positions: int = 0
    concentration_flags: list = field(default_factory=list)    # RiskFlag list
    sector_exposure: dict[str, float] = field(default_factory=dict)    # market-value weight by sector
    currency_exposure: dict[str, float] = field(default_factory=dict)  # market-value weight by currency book
    strategy_note: str = ""
    errors: dict = field(default_factory=dict)


# ── Single-position review ─────────────────────────────────────────────────────

def _get_recent_signals(ticker: str, since_days: int = 30) -> list[dict]:
    """A2/A3 decisions for this ticker in the recent window — what's happened
    since the thesis was last set, that A4 should weigh."""
    from src.desks.equity_ls.infrastructure.b4_knowledge_base import decision_history as dh

    history = dh.get_decision_history(ticker)
    out = []
    for d in history:
        if d["source"] not in ("a2", "a3"):
            continue
        try:
            age = (datetime.now() - datetime.strptime(d["created_at"][:10], "%Y-%m-%d")).days
        except ValueError:
            continue
        if age <= since_days:
            out.append(d)
    return out


def _format_position_context(
    ticker: str,
    holding: dict,
    price: float | None,
    thesis: str,
    signals: list[dict],
    sr,
    flags: list,
) -> str:
    shares = holding.get("shares") or 0
    avg_cost = holding.get("avg_cost") or 0
    pnl_pct = ((price - avg_cost) / avg_cost * 100) if price and avg_cost else None

    lines = [
        f"HOLDING: {ticker}",
        f"  Shares: {shares} | Avg cost: ${avg_cost:.2f} | Current price: "
        f"{'$' + format(price, '.2f') if price else 'N/A'} | "
        f"P&L: {f'{pnl_pct:+.1f}%' if pnl_pct is not None else 'N/A'}",
        "",
        f"SAVED THESIS:\n{thesis}",
        "",
        f"SCREENER SCORE: {sr.composite_score:.1f}/100 | {sr.classification}"
        if sr else "SCREENER SCORE: unavailable",
    ]

    if signals:
        lines.append("\nRECENT SIGNALS (A2/A3, last 30d):")
        for s in signals[:8]:
            lines.append(f"  [{s['source']}] {s['created_at'][:10]}: {s['verdict']} — {s['rationale'][:150]}")
    else:
        lines.append("\nRECENT SIGNALS: none in the last 30 days")

    if flags:
        lines.append("\nRISK FLAGS:")
        for f in flags:
            lines.append(f"  [{f.severity}] {f.message}")

    return "\n".join(lines)


def _judge_position(ticker: str, context_block: str) -> tuple[str, str]:
    """Returns (assessment, direction). One LLM call — direction only, never
    a size. See module docstring for why this boundary is non-negotiable
    right now."""
    prompt = f"""You are the Equity L/S desk's portfolio decision analyst for an existing holding.
Assess thesis health and recommend a DIRECTION ONLY — never a share count, dollar amount,
or target weight/position size. Sizing belongs to the risk desk, not you.

{context_block}

Consider: Is the original thesis still intact given recent signals and the current score?
Has anything happened that should change the stance? Is this name still worth the capital
it occupies, or would that capital work harder elsewhere?

Respond in exactly this format:

ASSESSMENT: <3-5 sentences on thesis health and what's changed, if anything>
DIRECTION: <one of: Hold, Add, Trim, Sell, Rotate, Deep Dive Further>

Definitions:
- Hold: thesis intact, no action needed
- Add: thesis strengthening, worth increasing exposure (direction only — no amount)
- Trim: thesis weakening or position has become oversized relative to conviction
- Sell: thesis broken or better opportunities elsewhere
- Rotate: exit this name in favor of a specific stronger peer (name the peer in ASSESSMENT)
- Deep Dive Further: recent signals are material enough that this needs a fresh full review before deciding"""

    try:
        resp = _llm(temperature=0.2).invoke(prompt)
        text = resp.content.strip()
        assessment, direction = "", ""
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("ASSESSMENT:"):
                assessment = line.split(":", 1)[1].strip()
            elif line.upper().startswith("DIRECTION:"):
                raw = line.split(":", 1)[1].strip()
                direction = next((d for d in DIRECTIONS if d.lower() in raw.lower()), "")
        return assessment or text, direction
    except Exception as e:
        return f"[Position judgment error: {e}]", ""


def review_position(ticker: str, save_to_kb: bool = True) -> PositionReview:
    """
    Thesis-health review of one held position. Refuses to run on a name
    that isn't actually held — A4's job is existing holdings; a not-held
    name belongs to A2.
    """
    from src.desks.equity_ls.infrastructure.b3_portfolio import portfolio_db

    ticker = ticker.upper()
    run_date = datetime.now().strftime("%Y-%m-%d")
    result = PositionReview(ticker=ticker, run_date=run_date)

    holding = portfolio_db.get_holding(ticker)
    if not holding or (holding.get("shares") or 0) <= 0:
        result.skipped = True
        result.skip_reason = f"{ticker} is not currently held — use A2 deep dive instead"
        return result

    result.is_held = True
    print(f"[A4] Reviewing position: {ticker}")

    from src.desks.equity_ls.infrastructure.b2_data_source.data_sources import get_market_data
    from src.desks.equity_ls.infrastructure.b4_knowledge_base import knowledge_base as kb
    from src.desks.equity_ls.core.screener import screener as screener_mod
    from src.desks.equity_ls.core.risk import checks as risk_checks
    from src.desks.equity_ls.infrastructure.b1_universe.universe import check as universe_check

    md = get_market_data(ticker)
    price = md.get("price") if "_error" not in md else None
    shares = holding.get("shares") or 0
    avg_cost = holding.get("avg_cost") or 0
    result.holding_snapshot = {
        "shares": shares, "avg_cost": avg_cost, "price": price,
        "pnl_pct": ((price - avg_cost) / avg_cost * 100) if price and avg_cost else None,
    }

    result.thesis = kb.get_current_thesis(ticker) or "[No saved thesis for this ticker.]"
    result.recent_signals = _get_recent_signals(ticker)

    tier = universe_check(ticker).tier or 0
    try:
        sr = screener_mod.run(ticker, tier=tier)
        result.screener_score = sr.composite_score
        result.screener_classification = sr.classification
    except Exception as e:
        sr = None
        result.errors["screener"] = str(e)

    position_value = shares * price if price else None
    result.risk_flags = risk_checks.run_minimal_checks(ticker, md, position_value)

    context_block = _format_position_context(
        ticker, holding, price, result.thesis, result.recent_signals, sr, result.risk_flags,
    )
    result.assessment, result.direction = _judge_position(ticker, context_block)
    print(f"[A4] {ticker} direction: {result.direction or '(unparsed)'}")

    # ── Record as current_view — A4 owns held tickers ────────────────────────
    if result.direction:
        try:
            from src.desks.equity_ls.infrastructure.b4_knowledge_base import decision_history as dh
            result.decision_id = dh.record_as_current_view(
                ticker, "a4", result.direction, result.assessment,
                triggered_by="a4_position_review",
            )
            result.became_current_view = True
        except Exception as e:
            result.errors["decision_history"] = str(e)

    if save_to_kb:
        try:
            from src.desks.equity_ls.infrastructure.b4_knowledge_base import knowledge_base as kb2
            kb2.add_report(
                ticker, "trade_review",
                f"Position Review {run_date}",
                f"# Position Review: {ticker} ({run_date})\n\n{context_block}\n\n"
                f"## Assessment\n{result.assessment}\n\n## Direction\n{result.direction}",
                source="a4_portfolio_decision",
            )
        except Exception as e:
            result.errors["kb_save"] = str(e)

    return result


# ── Portfolio-wide review ──────────────────────────────────────────────────────

def review_portfolio() -> PortfolioReview:
    """
    Read-only portfolio-wide scan: concentration + currency exposure + a
    strategy note on which themes look strong/weak in aggregate. Does not
    touch current_view for any ticker — call review_position() per-name for that.
    """
    from concurrent.futures import ThreadPoolExecutor
    from src.desks.equity_ls.infrastructure.b3_portfolio import portfolio_db
    from src.desks.equity_ls.infrastructure.b2_data_source.data_sources import get_market_data
    from src.desks.equity_ls.infrastructure.b1_universe.universe import currency_for
    from src.desks.equity_ls.core.risk import checks as risk_checks

    run_date = datetime.now().strftime("%Y-%m-%d")
    result = PortfolioReview(run_date=run_date)

    holdings = portfolio_db.get_holdings()
    result.total_positions = len(holdings)
    if not holdings:
        return result

    tickers = [h["ticker"] for h in holdings]

    def fetch(t: str) -> tuple[str, dict]:
        return t, get_market_data(t)

    with ThreadPoolExecutor(max_workers=10) as ex:
        market_data = dict(ex.map(fetch, tickers))

    prices = {t: d.get("price") for t, d in market_data.items() if "_error" not in d and d.get("price")}

    result.concentration_flags = risk_checks.scan_concentration(holdings, prices)

    # Sector + currency exposure by market value (falls back to cost basis,
    # same stale-price caveat as scan_concentration — not separately re-flagged
    # here since concentration_flags already surfaces which names are stale).
    sector_value: dict[str, float] = {}
    currency_value: dict[str, float] = {}
    for h in holdings:
        t = h["ticker"]
        shares = h.get("shares") or 0
        if shares <= 0:
            continue
        price = prices.get(t) or h.get("avg_cost")
        if not price:
            continue
        value = shares * price
        sector = h.get("sector") or "Unknown"
        sector_value[sector] = sector_value.get(sector, 0.0) + value
        currency = currency_for(t)
        currency_value[currency] = currency_value.get(currency, 0.0) + value

    total = sum(sector_value.values())
    if total > 0:
        result.sector_exposure = {s: round(v / total, 4) for s, v in sorted(sector_value.items(), key=lambda kv: -kv[1])}
        result.currency_exposure = {c: round(v / total, 4) for c, v in sorted(currency_value.items(), key=lambda kv: -kv[1])}

    # Strategy note: aggregate screener scores per sector, one LLM synthesis call.
    try:
        result.strategy_note = _synthesize_strategy(result.sector_exposure, result.concentration_flags)
    except Exception as e:
        result.errors["strategy_note"] = str(e)

    return result


def _synthesize_strategy(sector_exposure: dict[str, float], concentration_flags: list) -> str:
    if not sector_exposure:
        return ""

    exposure_lines = "\n".join(f"  {s}: {w:.0%}" for s, w in sector_exposure.items())
    flag_lines = "\n".join(f"  [{f.severity}] {f.message}" for f in concentration_flags) or "  None"

    prompt = f"""You are the Equity L/S desk's portfolio strategist. Given the current sector
exposure and concentration flags below, write a short strategy note (4-6 sentences).
Comment on whether exposure looks balanced or lopsided, which sectors might warrant
trimming or adding to on a relative basis, and flag any concentration risk that stands out.
Direction only — never a specific dollar amount, share count, or target weight.

SECTOR EXPOSURE (% of book, market value):
{exposure_lines}

CONCENTRATION FLAGS:
{flag_lines}"""

    resp = _llm(temperature=0.3).invoke(prompt)
    return resp.content.strip()
