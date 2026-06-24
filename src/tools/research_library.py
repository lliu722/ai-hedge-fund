"""
Research Library — SQLite store for deep dives, earnings notes, and thesis snapshots.
Saves automatically when deep_dive or get_earnings_transcript is called.
Searchable by ticker, keyword, or date range.
"""
import os
import sqlite3
from datetime import datetime
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
            CREATE TABLE IF NOT EXISTS research (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker    TEXT NOT NULL,
                type      TEXT NOT NULL,  -- 'deep_dive' | 'earnings' | 'thesis' | 'note'
                content   TEXT NOT NULL,
                created   TEXT NOT NULL
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_ticker ON research(ticker)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_type   ON research(type)")


_init_db()


def save_research(ticker: str, type: str, content: str) -> None:
    """Persist a research entry. Called automatically by deep_dive and earnings_transcript tools."""
    ticker = ticker.upper()
    with _conn() as con:
        con.execute(
            "INSERT INTO research (ticker, type, content, created) VALUES (?, ?, ?, ?)",
            (ticker, type, content[:8000], datetime.now().strftime("%Y-%m-%d %H:%M")),
        )


def search_research(query: str = "", ticker: str = "", limit: int = 10) -> list[dict]:
    """Search research library by ticker and/or keyword."""
    with _conn() as con:
        if ticker and query:
            rows = con.execute(
                "SELECT * FROM research WHERE ticker=? AND content LIKE ? ORDER BY created DESC LIMIT ?",
                (ticker.upper(), f"%{query}%", limit),
            ).fetchall()
        elif ticker:
            rows = con.execute(
                "SELECT * FROM research WHERE ticker=? ORDER BY created DESC LIMIT ?",
                (ticker.upper(), limit),
            ).fetchall()
        elif query:
            rows = con.execute(
                "SELECT * FROM research WHERE content LIKE ? ORDER BY created DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM research ORDER BY created DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


def get_research_summary() -> str:
    """Count entries per ticker for the library index."""
    with _conn() as con:
        rows = con.execute(
            "SELECT ticker, COUNT(*) as cnt, MAX(created) as last FROM research GROUP BY ticker ORDER BY last DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Earnings Surprise Tracker ─────────────────────────────────────────────────

def _init_earnings_table():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS earnings_surprises (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker           TEXT NOT NULL,
                period           TEXT NOT NULL,
                beat_miss        TEXT NOT NULL,  -- 'Beat' | 'Miss' | 'In-line'
                rev_surprise_pct REAL,
                eps_surprise_pct REAL,
                stock_reaction   REAL,
                notes            TEXT,
                created          TEXT NOT NULL
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_earn_ticker ON earnings_surprises(ticker)")

_init_earnings_table()


def log_earnings_surprise(ticker: str, period: str, beat_miss: str,
                          rev_surprise_pct: float = None, eps_surprise_pct: float = None,
                          stock_reaction: float = None, notes: str = "") -> str:
    ticker = ticker.upper()
    beat_miss = beat_miss.strip().title()
    if beat_miss not in ("Beat", "Miss", "In-line"):
        beat_miss = "Beat" if "beat" in beat_miss.lower() else ("Miss" if "miss" in beat_miss.lower() else "In-line")
    with _conn() as con:
        con.execute(
            """INSERT INTO earnings_surprises
               (ticker, period, beat_miss, rev_surprise_pct, eps_surprise_pct, stock_reaction, notes, created)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticker, period, beat_miss, rev_surprise_pct, eps_surprise_pct,
             stock_reaction, notes[:500], datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
    emoji = "🟢" if beat_miss == "Beat" else ("🔴" if beat_miss == "Miss" else "🟡")
    return f"{emoji} Logged: <b>{ticker}</b> {period} — {beat_miss}"


def get_earnings_history(ticker: str) -> list[dict]:
    ticker = ticker.upper()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM earnings_surprises WHERE ticker=? ORDER BY created DESC LIMIT 8",
            (ticker,)
        ).fetchall()
    return [dict(r) for r in rows]


def format_earnings_history(ticker: str) -> str:
    rows = get_earnings_history(ticker)
    if not rows:
        return f"No earnings history logged for <b>{ticker}</b>.\nLog with: <code>log earnings {ticker} Q1 2026 beat rev+3% eps+5% stock-2%</code>"
    beats = sum(1 for r in rows if r["beat_miss"] == "Beat")
    misses = sum(1 for r in rows if r["beat_miss"] == "Miss")
    msg = f"📈 <b>Earnings History: {ticker}</b>\n"
    msg += f"<i>{beats} beats · {misses} misses · {len(rows)-beats-misses} in-line (last {len(rows)} quarters)</i>\n\n"
    for r in rows:
        emoji = "🟢" if r["beat_miss"] == "Beat" else ("🔴" if r["beat_miss"] == "Miss" else "🟡")
        msg += f"{emoji} <b>{r['period']}</b> — {r['beat_miss']}"
        parts = []
        if r["rev_surprise_pct"] is not None:
            parts.append(f"Rev {r['rev_surprise_pct']:+.1f}%")
        if r["eps_surprise_pct"] is not None:
            parts.append(f"EPS {r['eps_surprise_pct']:+.1f}%")
        if r["stock_reaction"] is not None:
            parts.append(f"Stock {r['stock_reaction']:+.1f}%")
        if parts:
            msg += f" · {' · '.join(parts)}"
        if r["notes"]:
            msg += f"\n  <i>{r['notes'][:100]}</i>"
        msg += "\n"
    return msg.strip()


def format_research_results(rows: list[dict], show_content: bool = True) -> str:
    if not rows:
        return "No research found."
    out = ""
    for r in rows:
        out += f"📄 <b>{r['ticker']}</b> · <i>{r['type']}</i> · {r['created']}\n"
        if show_content:
            snippet = r["content"][:300].replace("\n", " ")
            out += f"<i>{snippet}{'…' if len(r['content']) > 300 else ''}</i>\n"
        out += "\n"
    return out.strip()
