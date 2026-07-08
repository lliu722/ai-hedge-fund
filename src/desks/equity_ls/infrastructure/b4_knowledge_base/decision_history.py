"""
Decision History + single-writer "current view" — the desk's memory of its own
recommendations, and the resolution to the multi-writer problem identified in
the 2026-07 pre-build audit:

    NVDA reports earnings. A3 says "trim." The weekly monitor triggers A2,
    which says "Long." A4's thesis-health check says "hold." All three want
    to write the desk's official stance. Which one wins?

Two tables, two different jobs:

  decisions      — append-only log of EVERY recommendation-worthy output from
                   any A-function. Never overwritten. This is what lets us
                   eventually measure "was the desk right" (recommendation vs.
                   later price action vs. what Louis actually did).

  current_view   — exactly one row per ticker: the desk's official live
                   stance right now. Only set via `record_as_current_view()`,
                   which enforces WHO is allowed to write it:

                     - held ticker (per B3 portfolio_db.is_holding)  → only A4
                       (Portfolio Decision Support) may set current_view.
                     - not-held ticker                               → only A2
                       (Single-Name Deep Dive) may set current_view.

                   A3 (Catalyst Response) and A5 (Relative Value) NEVER write
                   current_view directly — they call `record_decision()` to
                   log their output as an input, and if material, trigger a
                   re-run of whichever of A2/A4 currently owns the ticker.
                   That re-run's output becomes the new current_view.

                   Ownership is resolved dynamically at write time (via
                   portfolio_db.is_holding), not stored statically — so a
                   sold position naturally flips from A4-owned to A2-owned
                   on its very next decision, with no explicit transition step.

Every previous current_view row is preserved in `decisions` (never deleted);
`current_view` just tracks which decision is currently "live" per ticker.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "knowledge_base.db"

# Which A-function is allowed to set the official current_view for a ticker,
# keyed by whether the ticker is currently held. This is the single-writer
# rule from the audit, enforced in code (not just documented).
_CURRENT_VIEW_OWNER = {True: "a4", False: "a2"}

VALID_SOURCES = {"a1", "a2", "a3", "a4", "a5"}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS decisions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker       TEXT NOT NULL,
            source       TEXT NOT NULL,   -- a1 | a2 | a3 | a4 | a5
            verdict      TEXT NOT NULL,   -- free text; each function has its own vocabulary
            rationale    TEXT NOT NULL,
            triggered_by TEXT DEFAULT '', -- e.g. 'weekly cadence refresh', 'earnings catalyst', 'manual'
            superseded_by INTEGER,        -- id of the decision that later replaced this as current_view
            created_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS current_view (
            ticker      TEXT PRIMARY KEY,
            decision_id INTEGER NOT NULL,
            source      TEXT NOT NULL,   -- a2 | a4 — whichever wrote it
            verdict     TEXT NOT NULL,
            rationale   TEXT NOT NULL,
            updated_at  TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (decision_id) REFERENCES decisions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_decisions_ticker ON decisions(ticker);
    """)
    conn.commit()
    return conn


@contextmanager
def _db():
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


class SingleWriterViolation(ValueError):
    """Raised when a function tries to set current_view for a ticker it doesn't own.
    A3/A5 must call record_decision() instead — see module docstring."""


# ── Decisions (append-only log — anyone may write) ────────────────────────────

def record_decision(
    ticker: str,
    source: str,
    verdict: str,
    rationale: str,
    triggered_by: str = "",
) -> int:
    """
    Log a recommendation-worthy output from any A-function. Always succeeds —
    this does NOT touch current_view. Returns the new decision id.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"Unknown source '{source}' — must be one of {VALID_SOURCES}")
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO decisions (ticker, source, verdict, rationale, triggered_by) VALUES (?,?,?,?,?)",
            (ticker.upper(), source, verdict, rationale, triggered_by),
        )
        return cur.lastrowid


def get_decision_history(ticker: str, source: str | None = None) -> list[dict]:
    """All logged decisions for a ticker, newest first. Optionally filter by source."""
    with _db() as conn:
        if source:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE ticker=? AND source=? ORDER BY created_at DESC, id DESC",
                (ticker.upper(), source),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE ticker=? ORDER BY created_at DESC, id DESC",
                (ticker.upper(),),
            ).fetchall()
    return [dict(r) for r in rows]


# ── Current view (single-writer — only record_as_current_view may set it) ─────

def _is_held(ticker: str) -> bool:
    from src.desks.equity_ls.infrastructure.b3_portfolio import portfolio_db
    return portfolio_db.is_holding(ticker)


def owner_for(ticker: str) -> str:
    """Which source ('a2' or 'a4') is currently allowed to set this ticker's
    current_view, based on whether it's held right now."""
    return _CURRENT_VIEW_OWNER[_is_held(ticker)]


def record_as_current_view(
    ticker: str,
    source: str,
    verdict: str,
    rationale: str,
    triggered_by: str = "",
) -> int:
    """
    Log a decision AND make it the ticker's official current view, in one
    transaction. Raises SingleWriterViolation if `source` doesn't own this
    ticker right now (see module docstring for the ownership rule).

    This is the only function A2 and A4 should call when they conclude a run.
    A3/A5 must use record_decision() instead — they are never allowed here.
    """
    ticker = ticker.upper()
    expected_owner = owner_for(ticker)
    if source != expected_owner:
        held = _is_held(ticker)
        raise SingleWriterViolation(
            f"'{source}' cannot set current_view for {ticker} — "
            f"{'held' if held else 'not held'} tickers are owned by '{expected_owner}'. "
            f"Use record_decision() to log this as an input instead."
        )

    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO decisions (ticker, source, verdict, rationale, triggered_by) VALUES (?,?,?,?,?)",
            (ticker, source, verdict, rationale, triggered_by),
        )
        decision_id = cur.lastrowid

        prev = conn.execute("SELECT decision_id FROM current_view WHERE ticker=?", (ticker,)).fetchone()
        if prev:
            conn.execute("UPDATE decisions SET superseded_by=? WHERE id=?", (decision_id, prev["decision_id"]))

        conn.execute(
            """
            INSERT INTO current_view (ticker, decision_id, source, verdict, rationale, updated_at)
            VALUES (?,?,?,?,?, datetime('now'))
            ON CONFLICT(ticker) DO UPDATE SET
                decision_id=excluded.decision_id, source=excluded.source,
                verdict=excluded.verdict, rationale=excluded.rationale, updated_at=datetime('now')
            """,
            (ticker, decision_id, source, verdict, rationale),
        )
    return decision_id


def get_current_view(ticker: str) -> dict | None:
    """The desk's official live stance on a ticker, or None if it's never had one."""
    with _db() as conn:
        row = conn.execute("SELECT * FROM current_view WHERE ticker=?", (ticker.upper(),)).fetchone()
    return dict(row) if row else None


def get_all_current_views() -> list[dict]:
    """Every ticker with a live current_view, most recently updated first."""
    with _db() as conn:
        rows = conn.execute("SELECT * FROM current_view ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]
