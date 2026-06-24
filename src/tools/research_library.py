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
