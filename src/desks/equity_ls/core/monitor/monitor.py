"""
Market Monitor — the daily orchestration loop for the Equity L/S desk.

Runs on a schedule (daily cron via Railway). For each name in the universe:
  1. Checks tier cadence — is a score refresh due? (screener/cadence.py,
     tracked per ticker in a small monitor_state SQLite DB)
  2. If yes, runs the screener (Steps 1–6, fast, no LLM)
  3. Evaluates result — should this escalate to a full A2 deep dive?
  4. If yes, triggers A2 (B5 TradingAgents + desk conclusion + verdict)
  5. Sends Telegram alert for any actionable verdict

Tier sources:
  T0 / T1 — portfolio_db holdings + watchlist (B3)
  T2       — universe.get_sector_leaders() (B1)
  T3 / T4  — added dynamically by A1 Theme Discovery (not yet built)

The daily price/news check part of the T0/T1 cadence is future work — this
module currently covers the score-refresh + escalation loop.

Entry points:
  run_daily()        — main cron entry; call from Railway scheduler
  run_ticker(ticker) — single-name check (for manual triggers / testing)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_STATE_DB = Path(__file__).parent.parent.parent / "data" / "monitor_state.db"

_NEVER_RUN = 10_000  # days-since value for names with no recorded run


# ── Last-run state (per-ticker screener history) ─────────────────────────────

@contextmanager
def _state_db():
    conn = sqlite3.connect(_STATE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS last_screen (
            ticker   TEXT PRIMARY KEY,
            last_run TEXT NOT NULL   -- YYYY-MM-DD
        )
    """)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _days_since_last_run(ticker: str) -> int:
    with _state_db() as conn:
        row = conn.execute(
            "SELECT last_run FROM last_screen WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()
    if not row:
        return _NEVER_RUN
    try:
        last = datetime.strptime(row[0], "%Y-%m-%d")
        return (datetime.now() - last).days
    except ValueError:
        return _NEVER_RUN


def _mark_run(ticker: str) -> None:
    with _state_db() as conn:
        conn.execute(
            """
            INSERT INTO last_screen (ticker, last_run) VALUES (?, ?)
            ON CONFLICT(ticker) DO UPDATE SET last_run = excluded.last_run
            """,
            (ticker.upper(), datetime.now().strftime("%Y-%m-%d")),
        )


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class MonitorResult:
    ticker: str
    tier: int
    score: float | None = None
    classification: str = ""
    deep_dive_triggered: bool = False
    verdict: str = ""          # canonical A2 verdict ("" if no deep dive ran)
    alert_sent: bool = False
    skipped: bool = False
    skip_reason: str = ""
    errors: dict = field(default_factory=dict)


# ── Single-name check ─────────────────────────────────────────────────────────

def run_ticker(
    ticker: str,
    force_deep_dive: bool = False,
    send_alert: bool = True,
) -> MonitorResult:
    """
    Run a single-name monitor check: universe gate → screener → escalate to
    A2 deep dive if warranted → Telegram alert if the verdict is actionable.
    """
    from src.desks.equity_ls.infrastructure.b1_universe.universe import check as universe_check
    from src.desks.equity_ls.core.screener import screener as s

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
        _mark_run(ticker)

        if not sr.hard_pass:
            result.skipped = True
            result.skip_reason = sr.hard_fail_reason
            return result

        print(f"[Monitor] {ticker} score: {sr.composite_score:.1f} | {sr.classification}")
    except Exception as e:
        result.errors["screener"] = str(e)
        print(f"[Monitor] {ticker} screener error: {e}")
        return result

    # ── Escalate to A2 deep dive? ─────────────────────────────────────────────
    # sr.handoff_trigger already answered this via cadence.should_trigger_deep_dive
    # (the single authority — see cadence.py). Read it rather than recompute it,
    # so the monitor and the screener can never disagree about the same decision.
    escalate = force_deep_dive or sr.handoff_trigger == "Deep Dive Trigger"

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

    # ── Telegram alert for actionable verdicts ────────────────────────────────
    if send_alert and result.verdict and result.verdict != "Monitor":
        try:
            _send_alert(ticker, tier, result.score, result.verdict, sr)
            result.alert_sent = True
        except Exception as e:
            result.errors["alert"] = str(e)

    return result


# ── Daily loop ────────────────────────────────────────────────────────────────

def run_daily(send_alerts: bool = True) -> list[MonitorResult]:
    """
    Daily monitor run across all universe names due for a refresh per their
    tier cadence. Last run per ticker is tracked in monitor_state.db, so a
    weekly-cadence name runs on whichever day it becomes due.
    """
    from src.desks.equity_ls.infrastructure.b3_portfolio.portfolio_db import (
        get_holdings, get_watchlist,
    )
    from src.desks.equity_ls.infrastructure.b1_universe.universe import get_sector_leaders
    from src.desks.equity_ls.core.screener.cadence import should_run_score_refresh

    # Build the run list: highest tier wins when a name appears in several sources
    tiers: dict[str, int] = {}
    for t in get_sector_leaders():
        tiers[t.upper()] = 2
    for w in get_watchlist():
        tiers[w["ticker"].upper()] = 1
    for h in get_holdings():
        tiers[h["ticker"].upper()] = 0

    print(f"[Monitor] Daily run: {len(tiers)} names in scope")

    results: list[MonitorResult] = []
    for ticker, tier in sorted(tiers.items(), key=lambda kv: kv[1]):
        days_since = _days_since_last_run(ticker)
        if not should_run_score_refresh(tier, days_since):
            results.append(MonitorResult(
                ticker=ticker, tier=tier, skipped=True,
                skip_reason=f"Not due (last run {days_since}d ago)",
            ))
            continue
        try:
            results.append(run_ticker(ticker, send_alert=send_alerts))
        except Exception as e:
            results.append(MonitorResult(
                ticker=ticker, tier=tier, errors={"run_ticker": str(e)},
            ))

    checked    = [r for r in results if not r.skipped]
    triggered  = [r for r in results if r.deep_dive_triggered]
    actionable = [r for r in results if r.verdict and r.verdict != "Monitor"]
    print(
        f"[Monitor] Done. Screened: {len(checked)}/{len(results)} | "
        f"Deep dives: {len(triggered)} | Actionable: {len(actionable)}"
    )
    return results


# ── Telegram alert ────────────────────────────────────────────────────────────

def _send_alert(ticker: str, tier: int, score: float | None, verdict: str, sr) -> None:
    """Send a plain-text Telegram alert (no parse_mode — ticker/classification
    text can contain characters that break Markdown parsing)."""
    import os
    import requests

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

    score_txt = f"{score:.1f}" if score is not None else "?"
    msg = (
        f"{verdict_emoji} Equity L/S Monitor — {ticker}\n"
        f"Tier: {tier_label} | Score: {score_txt}/100\n"
        f"Classification: {sr.classification}\n"
        f"Verdict: {verdict}\n"
        f"Sector: {sr.sector} | {sr.industry}"
    )

    requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": msg},
        timeout=10,
    )
