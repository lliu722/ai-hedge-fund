"""
B3 — Portfolio Database for the Equity L/S desk.

Standalone SQLite at src/desks/equity_ls/data/portfolio.db. Three tables:
  holdings       — what we own (ticker, shares, avg_cost, thesis, sector, ...)
  watchlist      — what we're watching (ticker, note)
  trade_journal  — every buy/sell/trim (append-only history)

This is the target state: the desk owns its portfolio data, independent of Notion.
The bot currently keeps holdings in Notion, so `seed_from_notion()` is a temporary
one-way bridge to populate this DB with real data today. Drop it once this DB is truth.

Design rule: the DB itself is data-source-agnostic. CRUD takes plain values; it does
not know or care where they came from. Only `seed_from_notion()` touches Notion.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent / "data" / "portfolio.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS holdings (
            ticker     TEXT PRIMARY KEY,
            name       TEXT,
            sector     TEXT,
            role       TEXT,
            rating     TEXT,
            shares     REAL,
            avg_cost   REAL,
            thesis     TEXT,
            account    TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS watchlist (
            ticker   TEXT PRIMARY KEY,
            name     TEXT,
            note     TEXT,
            added_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS trade_journal (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker    TEXT NOT NULL,
            action    TEXT NOT NULL,      -- buy / sell / trim / add
            shares    REAL,
            price     REAL,
            rationale TEXT,
            traded_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    return conn


# ── Holdings ──────────────────────────────────────────────────────────────────

def upsert_holding(
    ticker: str, *, name: str = "", sector: str = "", role: str = "",
    rating: str = "", shares: float = 0.0, avg_cost: float = 0.0,
    thesis: str = "", account: str = "",
) -> None:
    with _connect() as conn:
        conn.execute("""
            INSERT INTO holdings (ticker, name, sector, role, rating, shares, avg_cost, thesis, account, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?, datetime('now'))
            ON CONFLICT(ticker) DO UPDATE SET
                name=excluded.name, sector=excluded.sector, role=excluded.role,
                rating=excluded.rating, shares=excluded.shares, avg_cost=excluded.avg_cost,
                thesis=excluded.thesis, account=excluded.account, updated_at=datetime('now')
        """, (ticker.upper(), name, sector, role, rating, shares, avg_cost, thesis, account))


def get_holding(ticker: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM holdings WHERE ticker = ?", (ticker.upper(),)).fetchone()
    return dict(row) if row else None


def get_holdings(account: str | None = None) -> list[dict]:
    with _connect() as conn:
        if account:
            rows = conn.execute("SELECT * FROM holdings WHERE account = ? AND shares > 0 ORDER BY ticker", (account,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM holdings WHERE shares > 0 ORDER BY ticker").fetchall()
    return [dict(r) for r in rows]


def remove_holding(ticker: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM holdings WHERE ticker = ?", (ticker.upper(),))


def is_holding(ticker: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM holdings WHERE ticker = ? AND shares > 0", (ticker.upper(),)).fetchone()
    return row is not None


# ── Watchlist ─────────────────────────────────────────────────────────────────

def add_to_watchlist(ticker: str, name: str = "", note: str = "") -> None:
    with _connect() as conn:
        conn.execute("""
            INSERT INTO watchlist (ticker, name, note) VALUES (?,?,?)
            ON CONFLICT(ticker) DO UPDATE SET name=excluded.name, note=excluded.note
        """, (ticker.upper(), name, note))


def get_watchlist() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM watchlist ORDER BY added_at DESC").fetchall()
    return [dict(r) for r in rows]


def remove_from_watchlist(ticker: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper(),))


def is_watchlist(ticker: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM watchlist WHERE ticker = ?", (ticker.upper(),)).fetchone()
    return row is not None


# ── Trade journal ─────────────────────────────────────────────────────────────

def log_trade(ticker: str, action: str, *, shares: float = 0.0, price: float = 0.0, rationale: str = "") -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO trade_journal (ticker, action, shares, price, rationale) VALUES (?,?,?,?,?)",
            (ticker.upper(), action, shares, price, rationale),
        )


def get_trades(ticker: str | None = None) -> list[dict]:
    with _connect() as conn:
        if ticker:
            rows = conn.execute("SELECT * FROM trade_journal WHERE ticker = ? ORDER BY traded_at DESC", (ticker.upper(),)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM trade_journal ORDER BY traded_at DESC").fetchall()
    return [dict(r) for r in rows]


# ── Exposure (derived) ────────────────────────────────────────────────────────

def sector_exposure() -> dict[str, float]:
    """Cost-basis weight per sector across current holdings. (Market-value version
    comes later when wired to live prices.)"""
    holdings = get_holdings()
    totals: dict[str, float] = {}
    grand = 0.0
    for h in holdings:
        cost = (h.get("shares") or 0) * (h.get("avg_cost") or 0)
        sector = h.get("sector") or "Unknown"
        totals[sector] = totals.get(sector, 0.0) + cost
        grand += cost
    if grand <= 0:
        return {}
    return {s: round(v / grand, 4) for s, v in sorted(totals.items(), key=lambda kv: -kv[1])}


# ── Notion bridge (temporary — remove once this DB is the source of truth) ─────

def seed_from_notion() -> int:
    """
    One-way sync: pull current holdings + watchlist from the live Notion source
    into this DB. Reuses the live bot's notion_holdings reader. Returns count of
    holdings seeded. TEMPORARY — delete when Notion is retired.
    """
    from src.tools.notion_holdings import get_holdings_from_notion, get_watchlist_tickers

    holdings = get_holdings_from_notion()
    for ticker, d in holdings.items():
        upsert_holding(
            ticker,
            name=d.get("name", ""), sector=d.get("sector", ""), role=d.get("role", ""),
            rating=d.get("rating", ""), shares=float(d.get("shares") or 0),
            avg_cost=float(d.get("avg_cost") or 0), thesis=d.get("thesis", ""),
            account=d.get("account", ""),
        )

    try:
        for ticker in get_watchlist_tickers():
            add_to_watchlist(ticker)
    except Exception:
        pass

    return len(holdings)
