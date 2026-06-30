"""
Market Monitor — the daily orchestration loop for the Equity L/S desk.

Runs on a schedule (daily cron via Railway). For each name in the universe:
  1. Checks tier cadence — is a score refresh due? (screener/cadence.py)
  2. If yes, runs the screener (Steps 1–6, fast, no LLM)
  3. Evaluates result — should this escalate to a full A2 deep dive?
  4. If yes, triggers A2 (B5 TradingAgents + desk conclusion + verdict)
  5. Sends Telegram alert for any actionable verdict

Tier sources:
  T0 / T1 — portfolio_db holdings + watchlist (B3)
  T2       — hardcoded sector leaders in universe.py (B1)
  T3 / T4  — added dynamically by A1 Theme Discovery (not yet built)

Entry points:
  run_daily()     — main cron entry; call from Railway scheduler
  run_ticker(ticker) — single-name check (for manual triggers / testing)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MonitorResult:
    ticker: str
    tier: int
    score: float | None = None
    classification: str = ""
    deep_dive_triggered: bool = False
    verdict: str = ""
    alert_sent: bool = False
    skipped: bool = False
    skip_reason: str = ""
    errors: dict = field(default_factory=dict)


def run_ticker(
    ticker: str,
    force_deep_dive: bool = False,
    send_alert: bool = True,
) -> MonitorResult:
    """
    Run a single-name monitor check.

    1. Universe gate + tier
    2. Cadence check — due for a refresh?
    3. Screener (Steps 1–6)
    4. Escalate to A2 deep dive if warranted
    5. Telegram alert if verdict is actionable
    """
    from src.desks.equity_ls.infrastructure.b1_universe.universe import check as universe_check
    from src.desks.equity_ls.core.screener import screener as s
    from src.desks.equity_ls.core.screener.cadence import should_trigger_deep_dive

    ticker = ticker.upper()
    meta = universe_check(ticker)

    if not meta.in_scope:
        return MonitorResult(
            ticker=ticker, tier=-1, skipped=True,
            skip_reason=f"Out of universe: {meta.rejection_reason}",
        )

    tier = meta.tier
    result = MonitorResult(ticker=ticker, tier=tier)

    # ── Screener (fast, no LLM) ───────────────────────────────────────────────
    print(f"[Monitor] {ticker} (T{tier}) — running screener...")
    try:
        sr = s.run(ticker, tier=tier)
        result.score = sr.composite_score
        result.classification = sr.classification

        if not sr.hard_pass:
            result.skipped = True
            result.skip_reason = sr.hard_fail_reason
            return result

        print(f"[Monitor] {ticker} score: {sr.composite_score:.1f} | {sr.classification}")
    except Exception as e:
        result.errors["screener"] = str(e)
        print(f"[Monitor] {ticker} screener error: {e}")
        return result

    # ── Detect major events (earnings proximity, news spike) ──────────────────
    days_to_earn = sr.raw.get("days_to_earnings")
    has_major_event = (
        days_to_earn is not None and 0 <= days_to_earn <= 7
    )

    # ── Escalate to A2 deep dive? ─────────────────────────────────────────────
    escalate = force_deep_dive or should_trigger_deep_dive(
        tier, sr.composite_score, has_major_event
    )

    if escalate:
        print(f"[Monitor] {ticker} → escalating to A2 deep dive...")
        try:
            from src.desks.equity_ls.core.a2_deep_dive import deep_dive
            dd = deep_dive.run(ticker, save_to_kb=True)
            result.deep_dive_triggered = True
            result.verdict = dd.verdict
        except Exception as e:
            result.errors["deep_dive"] = str(e)
            print(f"[Monitor] {ticker} deep dive error: {e}")
    else:
        result.verdict = ""  # no actionable output yet

    # ── Telegram alert ────────────────────────────────────────────────────────
    if send_alert and result.verdict and result.verdict not in ("Monitor", ""):
        try:
            _send_alert(ticker, tier, result.score, result.verdict, sr)
            result.alert_sent = True
        except Exception as e:
            result.errors["alert"] = str(e)

    return result


def run_daily(send_alerts: bool = True) -> list[MonitorResult]:
    """
    Daily monitor run across all universe names due for a refresh.

    Pulls T0/T1 from portfolio_db, T2 from universe hardcoded list.
    T3/T4 added when A1 Theme Discovery is built.
    """
    from src.desks.equity_ls.infrastructure.b3_portfolio.portfolio_db import (
        get_holdings, get_watchlist,
    )
    from src.desks.equity_ls.infrastructure.b1_universe.universe import _T2_SECTOR_LEADERS
    from src.desks.equity_ls.core.screener.cadence import get_cadence, should_run_score_refresh

    today = datetime.now()
    results: list[MonitorResult] = []

    # Build the run list: (ticker, tier, days_since_last_run)
    run_list: list[tuple[str, int, int]] = []

    # T0 — holdings (always due if daily cadence)
    for h in get_holdings():
        run_list.append((h["ticker"], 0, 1))  # treat as 1 day since last run → always runs

    # T1 — watchlist
    for w in get_watchlist():
        if w["ticker"] not in [r[0] for r in run_list]:
            run_list.append((w["ticker"], 1, 1))

    # T2 — sector leaders (weekly cadence; use day of week to stagger)
    if today.weekday() == 0:  # Monday
        for ticker in _T2_SECTOR_LEADERS:
            if ticker not in [r[0] for r in run_list]:
                run_list.append((ticker, 2, 7))

    print(f"[Monitor] Daily run: {len(run_list)} names")

    for ticker, tier, days_since in run_list:
        cadence = get_cadence(tier)
        if not should_run_score_refresh(tier, days_since):
            results.append(MonitorResult(
                ticker=ticker, tier=tier, skipped=True,
                skip_reason="Not due per cadence",
            ))
            continue
        try:
            r = run_ticker(ticker, send_alert=send_alerts)
            results.append(r)
        except Exception as e:
            results.append(MonitorResult(
                ticker=ticker, tier=tier,
                errors={"run_ticker": str(e)},
            ))

    # Summary
    triggered  = [r for r in results if r.deep_dive_triggered]
    actionable = [r for r in results if r.verdict and r.verdict not in ("", "Monitor")]
    print(
        f"[Monitor] Done. Checked: {len(results)} | "
        f"Deep dives: {len(triggered)} | Actionable: {len(actionable)}"
    )
    return results


# ── Telegram alert ────────────────────────────────────────────────────────────

def _send_alert(ticker: str, tier: int, score: float, verdict: str, sr) -> None:
    """Send a Telegram alert for an actionable verdict."""
    import os, requests

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id   = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        print(f"[Monitor] Telegram not configured — skipping alert for {ticker}")
        return

    tier_label = {0: "T0 Holding", 1: "T1 Watchlist", 2: "T2 Leader", 3: "T3 Peer", 4: "T4 New"}.get(tier, "?")
    verdict_emoji = {
        "Long": "🟢", "Add to watchlist": "📋", "Monitor": "👀",
        "Trim": "✂️", "Sell": "🔴", "Avoid": "⛔", "Dig further": "🔍",
    }.get(verdict, "📊")

    msg = (
        f"{verdict_emoji} *Equity L/S Monitor — {ticker}*\n"
        f"Tier: {tier_label} | Score: {score:.1f}/100\n"
        f"Classification: {sr.classification}\n"
        f"*Verdict: {verdict}*\n"
        f"Sector: {sr.sector} | {sr.industry}"
    )

    requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
        timeout=10,
    )
