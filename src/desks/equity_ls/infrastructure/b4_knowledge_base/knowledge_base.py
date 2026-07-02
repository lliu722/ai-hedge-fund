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
from contextlib import contextmanager
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

        -- Triggers own all FTS sync. External-content FTS5 tables must be
        -- updated via the special 'delete' command — a plain DELETE on the
        -- FTS table corrupts the index.
        CREATE TRIGGER IF NOT EXISTS reports_ai AFTER INSERT ON reports BEGIN
            INSERT INTO reports_fts(rowid, ticker, title, body)
            VALUES (new.id, new.ticker, new.title, new.body);
        END;
        CREATE TRIGGER IF NOT EXISTS reports_ad AFTER DELETE ON reports BEGIN
            INSERT INTO reports_fts(reports_fts, rowid, ticker, title, body)
            VALUES ('delete', old.id, old.ticker, old.title, old.body);
        END;
        CREATE TRIGGER IF NOT EXISTS reports_au AFTER UPDATE ON reports BEGIN
            INSERT INTO reports_fts(reports_fts, rowid, ticker, title, body)
            VALUES ('delete', old.id, old.ticker, old.title, old.body);
            INSERT INTO reports_fts(rowid, ticker, title, body)
            VALUES (new.id, new.ticker, new.title, new.body);
        END;
    """)
    conn.commit()
    return conn


@contextmanager
def _db():
    """One connection per call: commit/rollback via the transaction context,
    and always close the connection afterwards."""
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


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
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO reports (ticker, report_type, title, body, source) VALUES (?,?,?,?,?)",
            (ticker.upper(), report_type, title, body, source),
        )
        row_id = cur.lastrowid  # FTS index synced by trigger
    return row_id


def get_reports(ticker: str, report_type: str | None = None) -> list[dict]:
    """All reports for a ticker, newest first. Optionally filter by type."""
    with _db() as conn:
        if report_type:
            rows = conn.execute(
                "SELECT * FROM reports WHERE ticker=? AND report_type=? ORDER BY created_at DESC, id DESC",
                (ticker.upper(), report_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reports WHERE ticker=? ORDER BY created_at DESC, id DESC",
                (ticker.upper(),),
            ).fetchall()
    return [dict(r) for r in rows]


def get_latest_report(ticker: str, report_type: str) -> dict | None:
    """Most recent report of a given type for a ticker."""
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE ticker=? AND report_type=? ORDER BY created_at DESC, id DESC LIMIT 1",
            (ticker.upper(), report_type),
        ).fetchone()
    return dict(row) if row else None


def search_reports(query: str, ticker: str | None = None) -> list[dict]:
    """Full-text search across all reports. Optionally scoped to one ticker.
    Returns [] for FTS-invalid queries (e.g. stray operators) instead of raising."""
    try:
        with _db() as conn:
            if ticker:
                rows = conn.execute(
                    """
                    SELECT r.* FROM reports r
                    JOIN reports_fts f ON r.id = f.rowid
                    WHERE reports_fts MATCH ? AND r.ticker = ?
                    ORDER BY r.created_at DESC, r.id DESC
                    """,
                    (query, ticker.upper()),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT r.* FROM reports r
                    JOIN reports_fts f ON r.id = f.rowid
                    WHERE reports_fts MATCH ?
                    ORDER BY r.created_at DESC, r.id DESC
                    """,
                    (query,),
                ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def delete_report(report_id: int) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM reports WHERE id=?", (report_id,))  # FTS synced by trigger


# ── Thesis versions ───────────────────────────────────────────────────────────

def save_thesis(ticker: str, thesis: str) -> int:
    """Append a new thesis version. Returns the version number."""
    ticker = ticker.upper()
    with _db() as conn:
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
    with _db() as conn:
        row = conn.execute(
            "SELECT thesis FROM thesis_versions WHERE ticker=? ORDER BY version DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
    return row[0] if row else None


def get_thesis_history(ticker: str) -> list[dict]:
    """All thesis versions for a ticker, newest first."""
    with _db() as conn:
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
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO trading_agent_outputs (ticker, agent_name, signal, reasoning, confidence) VALUES (?,?,?,?,?)",
            (ticker.upper(), agent_name, signal.upper(), reasoning, confidence),
        )
    return cur.lastrowid


def get_agent_outputs(ticker: str, agent_name: str | None = None) -> list[dict]:
    """All agent outputs for a ticker, newest first. Filter by agent_name if given."""
    with _db() as conn:
        if agent_name:
            rows = conn.execute(
                "SELECT * FROM trading_agent_outputs WHERE ticker=? AND agent_name=? ORDER BY created_at DESC, id DESC",
                (ticker.upper(), agent_name),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trading_agent_outputs WHERE ticker=? ORDER BY created_at DESC, id DESC",
                (ticker.upper(),),
            ).fetchall()
    return [dict(r) for r in rows]


def get_latest_agent_output(ticker: str, agent_name: str | None = None) -> dict | None:
    """Most recent agent output. data_sources.py Section 7 calls this."""
    with _db() as conn:
        if agent_name:
            row = conn.execute(
                "SELECT * FROM trading_agent_outputs WHERE ticker=? AND agent_name=? ORDER BY created_at DESC, id DESC LIMIT 1",
                (ticker.upper(), agent_name),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM trading_agent_outputs WHERE ticker=? ORDER BY created_at DESC, id DESC LIMIT 1",
                (ticker.upper(),),
            ).fetchone()
    return dict(row) if row else None


# ── Summary helper ────────────────────────────────────────────────────────────

# ── PDF ingestion ─────────────────────────────────────────────────────────────
#
# Drop PDFs into:  src/desks/equity_ls/infrastructure/b4_knowledge_base/pdf_inbox/
#
# Naming convention (used to auto-fill ticker + type if not passed explicitly):
#   NVDA_deep_dive_2025Q2.pdf   →  ticker=NVDA, type=deep_dive
#   TSMC_earnings_note.pdf      →  ticker=TSMC, type=earnings_note
#   anything_else.pdf           →  ticker=UNKNOWN, type=other  (override manually)
#
# After ingestion the PDF stays in pdf_inbox/ — we never delete source files.

_PDF_INBOX = Path(__file__).parent / "pdf_inbox"

_TYPE_KEYWORDS = {
    "deep_dive": "deep_dive",
    "deepdive": "deep_dive",
    "earnings": "earnings_note",
    "earnings_note": "earnings_note",
    "valuation": "valuation_note",
    "trade_review": "trade_review",
    "review": "trade_review",
}


def _parse_pdf_filename(path: Path) -> tuple[str, str]:
    """Best-effort ticker + report_type from filename. Returns (ticker, report_type)."""
    stem = path.stem  # e.g. "NVDA_deep_dive_2025Q2"
    parts = stem.lower().split("_")
    ticker = parts[0].upper() if parts else "UNKNOWN"
    report_type = "other"
    # Check single parts and adjacent pairs (handles "deep_dive", "trade_review")
    candidates = parts[1:] + ["_".join(parts[i:i+2]) for i in range(1, len(parts) - 1)]
    for candidate in candidates:
        if candidate in _TYPE_KEYWORDS:
            report_type = _TYPE_KEYWORDS[candidate]
            break
    return ticker, report_type


def ingest_pdf(
    path: str | Path,
    ticker: str | None = None,
    report_type: str | None = None,
    title: str | None = None,
    source: str = "pdf_import",
) -> int:
    """
    Extract text from a PDF and store as a report in the KB.
    ticker / report_type / title are inferred from the filename if not provided.
    Returns the new report id.
    """
    import pdfplumber

    path = Path(path)
    inferred_ticker, inferred_type = _parse_pdf_filename(path)

    ticker = ticker or inferred_ticker
    report_type = report_type or inferred_type
    title = title or path.stem.replace("_", " ")

    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)

    body = "\n\n".join(pages).strip()
    if not body:
        raise ValueError(f"No extractable text found in {path.name}")

    return add_report(ticker, report_type, title, body, source=source)


def ingest_all_pdfs(
    inbox: str | Path | None = None,
    skip_existing: bool = True,
) -> list[dict]:
    """
    Process every PDF in pdf_inbox/ (or a custom folder).
    Returns a list of {file, ticker, report_type, report_id} for each ingested file.
    If skip_existing=True, files whose stem already has a matching title are skipped.
    """
    inbox = Path(inbox) if inbox else _PDF_INBOX
    results = []

    for pdf_path in sorted(inbox.glob("*.pdf")):
        inferred_ticker, inferred_type = _parse_pdf_filename(pdf_path)
        title = pdf_path.stem.replace("_", " ")

        if skip_existing:
            with _db() as conn:
                exists = conn.execute(
                    "SELECT 1 FROM reports WHERE ticker=? AND title=?",
                    (inferred_ticker, title),
                ).fetchone()
            if exists:
                results.append({"file": pdf_path.name, "status": "skipped (already ingested)"})
                continue

        try:
            report_id = ingest_pdf(pdf_path)
            results.append({
                "file": pdf_path.name,
                "ticker": inferred_ticker,
                "report_type": inferred_type,
                "report_id": report_id,
                "status": "ok",
            })
        except Exception as e:
            results.append({"file": pdf_path.name, "status": f"error: {e}"})

    return results


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
