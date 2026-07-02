"""
Exclusion list database for the Equity L/S desk.

Backed by SQLite at src/desks/equity_ls/data/exclusion.db.
Names on this list are hard-blocked — universe filter rejects them regardless
of region, tier, or instrument type.

Add names here for: sanctions, regulatory restrictions, internal blacklist,
names with no reliable data, or any name the desk must never touch.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "exclusion.db"


@contextmanager
def _db():
    """One connection per call: commit/rollback via the transaction context,
    and always close the connection afterwards."""
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS exclusion_list (
            ticker      TEXT PRIMARY KEY,
            reason      TEXT,
            added_at    TEXT DEFAULT (datetime('now'))
        )
    """)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def is_excluded(ticker: str) -> bool:
    with _db() as conn:
        row = conn.execute(
            "SELECT 1 FROM exclusion_list WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()
    return row is not None


def add(ticker: str, reason: str = "") -> None:
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO exclusion_list (ticker, reason) VALUES (?, ?)
            ON CONFLICT(ticker) DO UPDATE SET reason = excluded.reason
            """,
            (ticker.upper(), reason),
        )


def remove(ticker: str) -> None:
    with _db() as conn:
        conn.execute(
            "DELETE FROM exclusion_list WHERE ticker = ?", (ticker.upper(),)
        )


def list_all() -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT ticker, reason, added_at FROM exclusion_list ORDER BY added_at DESC"
        ).fetchall()
    return [{"ticker": r[0], "reason": r[1], "added_at": r[2]} for r in rows]
