"""
B4 — Knowledge Base for the Equity L/S desk.

Standalone SQLite at src/desks/equity_ls/data/knowledge_base.db. Four tables:

  reports              — all written research (deep dives, earnings notes, valuation
                         notes, trade reviews). One row per document.
  reports_fts          — FTS5 shadow table for full-text search across reports.
  thesis_versions      — append-only thesis history per ticker. Each save is a new
                         version; latest is always the current thesis.
  trading_agent_outputs — signal + reasoning rows written by B5 (TradingAgents).
                          Append-only; get_latest_agent_output() returns most recent.

Report types (report_type field):
  deep_dive      — full company analysis
  earnings_note  — post-earnings observation
  valuation_note — valuation model snapshot
  trade_review   — post-trade / post-exit review
  other          — catch-all

B5 (trading_agents.py) writes to trading_agent_outputs directly.
data_sources.py Section 7 reads from this module via get_reports() and
get_latest_agent_output().
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "knowledge_base.db"

REPORT_TYPES = {"deep_dive", "earnings_note", "valuation_note", "trade_review", "other"}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            report_type TEXT NOT NULL,   -- deep_dive | earnings_note | valuation_note | trade_review | other
            title       TEXT NOT NULL,
            body        TEXT NOT NULL,
            source      TEXT DEFAULT '', -- author / tool / 'manual'
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS thesis_versions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker     TEXT NOT NULL,
            version    INTEGER NOT NULL,
            thesis     TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS trading_agent_outputs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker     TEXT NOT NULL,
            agent_name TEXT NOT NULL,   -- e.g. 'fundamentals_agent', 'sentiment_agent'
            signal     TEXT NOT NULL,   -- BUY | SELL | HOLD | WATCH
            reasoning  TEXT NOT NULL,
            confidence REAL DEFAULT 0.0,  -- 0.0–1.0
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS reports_fts USING fts5(
            ticker, title, body,
            content='reports',
            content_rowid='id'
        );
    """)
    conn.commit()
    return conn


# ── Reports ───────────────────────────────────────────────────────────────────

def add_report(
    ticker: str,
    report_type: str,
    title: str,
    body: str,
    source: str = "manual",
) -> int:
    """Insert a research document. Returns the new row id."""
    if report_type not in REPORT_TYPES:
        report_type = "other"
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO reports (ticker, report_type, title, body, source) VALUES (?,?,?,?,?)",
            (ticker.upper(), report_type, title, body, source),
        )
        row_id = cur.lastrowid
        # Keep FTS index in sync
        conn.execute(
            "INSERT INTO reports_fts (rowid, ticker, title, body) VALUES (?,?,?,?)",
            (row_id, ticker.upper(), title, body),
        )
    return row_id


def get_reports(ticker: str, report_type: str | None = None) -> list[dict]:
    """All reports for a ticker, newest first. Optionally filter by type."""
    with _connect() as conn:
        if report_type:
            rows = conn.execute(
                "SELECT * FROM reports WHERE ticker=? AND report_type=? ORDER BY created_at DESC",
                (ticker.upper(), report_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reports WHERE ticker=? ORDER BY created_at DESC",
                (ticker.upper(),),
            ).fetchall()
    return [dict(r) for r in rows]


def get_latest_report(ticker: str, report_type: str) -> dict | None:
    """Most recent report of a given type for a ticker."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE ticker=? AND report_type=? ORDER BY created_at DESC LIMIT 1",
            (ticker.upper(), report_type),
        ).fetchone()
    return dict(row) if row else None


def search_reports(query: str, ticker: str | None = None) -> list[dict]:
    """Full-text search across all reports. Optionally scoped to one ticker."""
    with _connect() as conn:
        if ticker:
            rows = conn.execute(
                """
                SELECT r.* FROM reports r
                JOIN reports_fts f ON r.id = f.rowid
                WHERE reports_fts MATCH ? AND r.ticker = ?
                ORDER BY r.created_at DESC
                """,
                (query, ticker.upper()),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT r.* FROM reports r
                JOIN reports_fts f ON r.id = f.rowid
                WHERE reports_fts MATCH ?
                ORDER BY r.created_at DESC
                """,
                (query,),
            ).fetchall()
    return [dict(r) for r in rows]


def delete_report(report_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM reports WHERE id=?", (report_id,))
        conn.execute("DELETE FROM reports_fts WHERE rowid=?", (report_id,))


# ── Thesis versions ───────────────────────────────────────────────────────────

def save_thesis(ticker: str, thesis: str) -> int:
    """Append a new thesis version. Returns the version number."""
    ticker = ticker.upper()
    with _connect() as conn:
        row = conn.execute(
            "SELECT MAX(version) FROM thesis_versions WHERE ticker=?", (ticker,)
        ).fetchone()
        next_version = (row[0] or 0) + 1
        conn.execute(
            "INSERT INTO thesis_versions (ticker, version, thesis) VALUES (?,?,?)",
            (ticker, next_version, thesis),
        )
    return next_version


def get_current_thesis(ticker: str) -> str | None:
    """Latest thesis text for a ticker, or None if none saved."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT thesis FROM thesis_versions WHERE ticker=? ORDER BY version DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
    return row[0] if row else None


def get_thesis_history(ticker: str) -> list[dict]:
    """All thesis versions for a ticker, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM thesis_versions WHERE ticker=? ORDER BY version DESC",
            (ticker.upper(),),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Trading agent outputs (written by B5) ─────────────────────────────────────

def add_agent_output(
    ticker: str,
    agent_name: str,
    signal: str,
    reasoning: str,
    confidence: float = 0.0,
) -> int:
    """B5 writes here after running TradingAgents on a ticker. Returns row id."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO trading_agent_outputs (ticker, agent_name, signal, reasoning, confidence) VALUES (?,?,?,?,?)",
            (ticker.upper(), agent_name, signal.upper(), reasoning, confidence),
        )
    return cur.lastrowid


def get_agent_outputs(ticker: str, agent_name: str | None = None) -> list[dict]:
    """All agent outputs for a ticker, newest first. Filter by agent_name if given."""
    with _connect() as conn:
        if agent_name:
            rows = conn.execute(
                "SELECT * FROM trading_agent_outputs WHERE ticker=? AND agent_name=? ORDER BY created_at DESC",
                (ticker.upper(), agent_name),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trading_agent_outputs WHERE ticker=? ORDER BY created_at DESC",
                (ticker.upper(),),
            ).fetchall()
    return [dict(r) for r in rows]


def get_latest_agent_output(ticker: str, agent_name: str | None = None) -> dict | None:
    """Most recent agent output. data_sources.py Section 7 calls this."""
    with _connect() as conn:
        if agent_name:
            row = conn.execute(
                "SELECT * FROM trading_agent_outputs WHERE ticker=? AND agent_name=? ORDER BY created_at DESC LIMIT 1",
                (ticker.upper(), agent_name),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM trading_agent_outputs WHERE ticker=? ORDER BY created_at DESC LIMIT 1",
                (ticker.upper(),),
            ).fetchone()
    return dict(row) if row else None


# ── Summary helper ────────────────────────────────────────────────────────────

def get_kb_summary(ticker: str) -> dict:
    """
    Quick summary of everything KB knows about a ticker.
    Used by A2 Deep Dive and A4 Portfolio Decision Support.
    """
    ticker = ticker.upper()
    reports = get_reports(ticker)
    thesis = get_current_thesis(ticker)
    latest_agent = get_latest_agent_output(ticker)

    by_type: dict[str, int] = {}
    for r in reports:
        t = r["report_type"]
        by_type[t] = by_type.get(t, 0) + 1

    return {
        "ticker": ticker,
        "report_count": len(reports),
        "reports_by_type": by_type,
        "has_thesis": thesis is not None,
        "current_thesis": thesis,
        "latest_agent_signal": latest_agent.get("signal") if latest_agent else None,
        "latest_agent_name": latest_agent.get("agent_name") if latest_agent else None,
        "latest_agent_at": latest_agent.get("created_at") if latest_agent else None,
    }
