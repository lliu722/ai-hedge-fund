"""
Custom alert thresholds — user-configurable per-ticker price move alerts.
Stored in SQLite alongside the research library.
"""
import os
import sqlite3
from contextlib import contextmanager

_DB_PATH = "/app/data/research.db" if os.path.exists("/app/data") else "research.db"


@contextmanager
def _conn():
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _init_db():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS custom_alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT NOT NULL,
                threshold   REAL NOT NULL,
                direction   TEXT NOT NULL DEFAULT 'both',  -- 'up' | 'down' | 'both'
                created     TEXT NOT NULL,
                UNIQUE(ticker, direction)
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_alert_ticker ON custom_alerts(ticker)")
        con.execute("""
            CREATE TABLE IF NOT EXISTS watchlist_targets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT NOT NULL UNIQUE,
                target      REAL NOT NULL,   -- entry price target
                direction   TEXT NOT NULL,   -- 'below' (buy dip) | 'above' (breakout)
                note        TEXT,
                created     TEXT NOT NULL
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_wl_ticker ON watchlist_targets(ticker)")
        con.execute("""
            CREATE TABLE IF NOT EXISTS alerted_today (
                ticker  TEXT NOT NULL,
                date    TEXT NOT NULL,
                PRIMARY KEY (ticker, date)
            )
        """)


_init_db()


def has_alerted_today(ticker: str, today: str) -> bool:
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM alerted_today WHERE ticker=? AND date=?", (ticker, today)
        ).fetchone()
        return row is not None


def mark_alerted_today(ticker: str, today: str):
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO alerted_today (ticker, date) VALUES (?, ?)", (ticker, today)
        )


def clear_alerted_today(today: str):
    """Remove entries older than today — called at morning briefing."""
    with _conn() as con:
        con.execute("DELETE FROM alerted_today WHERE date != ?", (today,))


def set_alert(ticker: str, threshold: float, direction: str = "both") -> str:
    """Add or update a custom alert for a ticker."""
    ticker = ticker.upper()
    direction = direction.lower().strip()
    if direction not in ("up", "down", "both"):
        direction = "both"
    from datetime import datetime
    with _conn() as con:
        con.execute(
            """INSERT INTO custom_alerts (ticker, threshold, direction, created)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(ticker, direction) DO UPDATE SET threshold=excluded.threshold, created=excluded.created""",
            (ticker, abs(threshold), direction, datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
    arrow = {"up": "📈 up", "down": "📉 down", "both": "either direction"}.get(direction, direction)
    return f"🔔 Alert set: <b>{ticker}</b> moves {arrow} ≥ <b>{threshold:.1f}%</b>"


def remove_alert(ticker: str, direction: str = None) -> str:
    """Remove a custom alert. If direction is None, removes all alerts for the ticker."""
    ticker = ticker.upper()
    with _conn() as con:
        if direction:
            con.execute("DELETE FROM custom_alerts WHERE ticker=? AND direction=?", (ticker, direction.lower()))
        else:
            con.execute("DELETE FROM custom_alerts WHERE ticker=?", (ticker,))
    return f"🔕 Alert removed for <b>{ticker}</b>."


def get_alerts() -> list[dict]:
    """Return all configured custom alerts."""
    with _conn() as con:
        rows = con.execute("SELECT * FROM custom_alerts ORDER BY ticker").fetchall()
    return [dict(r) for r in rows]


def get_alerts_for_ticker(ticker: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM custom_alerts WHERE ticker=?", (ticker.upper(),)).fetchall()
    return [dict(r) for r in rows]


def check_custom_alerts(prices: dict, alerted_cache: dict, today: str) -> list[tuple]:
    """
    Compare current prices against all custom thresholds.
    Returns list of (ticker, change_pct, price, threshold, direction) for triggered alerts.
    Deduped: one alert per ticker+direction per day via alerted_cache.
    """
    alerts = get_alerts()
    if not alerts:
        return []

    triggered = []
    for row in alerts:
        ticker = row["ticker"]
        threshold = row["threshold"]
        direction = row["direction"]
        data = prices.get(ticker)
        if not data:
            continue
        change = data.get("change_pct") or 0
        price = data.get("price") or 0

        fired = (
            (direction == "up"   and change >= threshold) or
            (direction == "down" and change <= -threshold) or
            (direction == "both" and abs(change) >= threshold)
        )
        if not fired:
            continue

        cache_key = f"{ticker}:{direction}:{today}"
        if alerted_cache.get(cache_key):
            continue

        alerted_cache[cache_key] = True
        triggered.append((ticker, change, price, threshold, direction))

    return triggered


# ── Watchlist Price Targets ───────────────────────────────────────────────────

def set_watchlist_target(ticker: str, target: float, direction: str = "below", note: str = "") -> str:
    """Set an entry price target for a watchlist name."""
    ticker = ticker.upper()
    direction = "above" if direction.lower() in ("above", "breakout", "up") else "below"
    from datetime import datetime
    with _conn() as con:
        con.execute(
            """INSERT INTO watchlist_targets (ticker, target, direction, note, created)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(ticker) DO UPDATE SET
                 target=excluded.target, direction=excluded.direction,
                 note=excluded.note, created=excluded.created""",
            (ticker, target, direction, note[:200], datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
    arrow = "📉 drops below" if direction == "below" else "📈 breaks above"
    return f"🎯 Target set: alert me when <b>{ticker}</b> {arrow} <b>${target:.2f}</b>"


def remove_watchlist_target(ticker: str) -> str:
    ticker = ticker.upper()
    with _conn() as con:
        con.execute("DELETE FROM watchlist_targets WHERE ticker=?", (ticker,))
    return f"🎯 Target removed for <b>{ticker}</b>."


def get_watchlist_targets() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM watchlist_targets ORDER BY ticker").fetchall()
    return [dict(r) for r in rows]


def check_watchlist_targets(prices: dict, alerted_cache: dict, today: str) -> list[tuple]:
    """
    Check if any watchlist price targets have been hit.
    Returns list of (ticker, price, target, direction, note) for triggered targets.
    Deduped per ticker per day.
    """
    targets = get_watchlist_targets()
    if not targets:
        return []
    triggered = []
    for row in targets:
        ticker = row["ticker"]
        target = row["target"]
        direction = row["direction"]
        data = prices.get(ticker)
        if not data or not data.get("price"):
            continue
        price = data["price"]
        fired = (direction == "below" and price <= target) or \
                (direction == "above" and price >= target)
        if not fired:
            continue
        cache_key = f"wl_target:{ticker}:{today}"
        if alerted_cache.get(cache_key):
            continue
        alerted_cache[cache_key] = True
        triggered.append((ticker, price, target, direction, row.get("note", "")))
    return triggered


def format_watchlist_targets() -> str:
    targets = get_watchlist_targets()
    if not targets:
        return "🎯 No watchlist targets set.\n\nSet one with: <code>target MRVL below 60</code>"
    msg = "🎯 <b>Watchlist Targets</b>\n\n"
    for row in targets:
        arrow = "📉 below" if row["direction"] == "below" else "📈 above"
        note = f" — {row['note']}" if row.get("note") else ""
        msg += f"• <b>{row['ticker']}</b>: {arrow} <b>${row['target']:.2f}</b>{note}\n"
    msg += "\n<i>Remove with: remove target MRVL</i>"
    return msg


def format_alerts_list() -> str:
    alerts = get_alerts()
    if not alerts:
        return "🔕 No custom alerts set.\n\nSet one with: <code>alert NVDA 5</code> or <code>alert MU down 3</code>"
    msg = "🔔 <b>Custom Alerts</b>\n\n"
    for row in alerts:
        arrow = {"up": "📈 ≥", "down": "📉 ≥", "both": "± "}.get(row["direction"], "±")
        msg += f"• <b>{row['ticker']}</b>: {arrow}{row['threshold']:.1f}% ({row['direction']})\n"
    msg += "\n<i>Remove with: remove alert NVDA</i>"
    return msg
