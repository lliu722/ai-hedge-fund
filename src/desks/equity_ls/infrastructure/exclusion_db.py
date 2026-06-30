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
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent / "data" / "exclusion.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS exclusion_list (
            ticker      TEXT PRIMARY KEY,
            reason      TEXT,
            added_at    TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def is_excluded(ticker: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM exclusion_list WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()
    return row is not None


def add(ticker: str, reason: str = "") -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO exclusion_list (ticker, reason) VALUES (?, ?)",
            (ticker.upper(), reason),
        )


def remove(ticker: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM exclusion_list WHERE ticker = ?", (ticker.upper(),)
        )


def list_all() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ticker, reason, added_at FROM exclusion_list ORDER BY added_at DESC"
        ).fetchall()
    return [{"ticker": r[0], "reason": r[1], "added_at": r[2]} for r in rows]
