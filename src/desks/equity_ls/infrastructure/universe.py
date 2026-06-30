"""
Equity L/S universe filter + tier tagger.

Two responsibilities:
  1. Gate — does this ticker belong in scope? (region + instrument type + not excluded)
  2. Tag  — what priority tier is this name? Tag travels with the name downstream.

Tier definitions:
  T0 — Core Holdings       (names currently in the book)
  T1 — Core Watchlist      (names actively monitored)
  T2 — Sector Leaders      (large, liquid, defines a sector/theme)
  T3 — Peer / Supply Chain (competitors, suppliers, customers, read-throughs)
  T4 — Discovered Names    (new names surfaced by A1 Theme Discovery)

T0/T1 stubs for now — will be live reads from B3 (portfolio_db) when built.
T2 is hardcoded here. T3/T4 are assigned by the functions that discover them.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.desks.equity_ls.infrastructure import exclusion_db

# ── Eligible region suffixes ──────────────────────────────────────────────────

ELIGIBLE_SUFFIXES: set[str] = {
    "",         # US, Canada
    ".HK",      # Hong Kong
    ".TW",      # Taiwan
    ".KS",      # South Korea KOSPI
    ".KQ",      # South Korea KOSDAQ
    ".T",       # Japan
    ".BO",      # India BSE
    ".NS",      # India NSE
    ".SI",      # Singapore
    ".AX",      # Australia
    ".L",       # UK
    ".DE",      # Germany
    ".PA",      # France
    ".AS",      # Netherlands
    ".MI",      # Italy
    ".MC",      # Spain
    ".SW",      # Switzerland
    ".ST",      # Sweden / Nordics
    ".SS",      # China A-share Shanghai
    ".SZ",      # China A-share Shenzhen
}

# ── Instrument types ──────────────────────────────────────────────────────────

INSTRUMENT_TYPES = {"single_stock", "etf", "adr", "gdr", "reit", "holding_company"}
DEFAULT_INSTRUMENT_TYPES: set[str] = INSTRUMENT_TYPES.copy()

# ── T2 Sector Leaders (hardcoded until B3 DB is built) ───────────────────────
# Large, liquid names that define each major sector or theme.
# This list is intentionally small — only true sector/theme anchors.

_T2_SECTOR_LEADERS: set[str] = {
    # US Tech / AI
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSM", "ASML",
    # US Financials
    "JPM", "GS", "BLK", "V", "MA",
    # US Healthcare
    "LLY", "UNH", "JNJ",
    # US Energy
    "XOM", "CVX",
    # US Industrials
    "CAT", "HON", "GE",
    # US Consumer
    "WMT", "COST", "MCD",
    # HK / China
    "0700.HK", "9988.HK", "0005.HK",
    # Japan
    "6758.T", "7203.T",
    # Crypto-equity anchor
    "COIN",
}


# ── Output type ───────────────────────────────────────────────────────────────

@dataclass
class TickerMeta:
    ticker: str
    in_scope: bool
    tier: int | None      # 0–4 if in scope; None if rejected
    rejection_reason: str  # empty string if in scope


# ── Public interface ──────────────────────────────────────────────────────────

def check(
    ticker: str,
    instrument_type: str = "single_stock",
    allowed_types: set[str] | None = None,
) -> TickerMeta:
    """
    Gate + tag in one call. Returns TickerMeta with in_scope and tier.
    Use this everywhere — the tag travels with the name downstream.
    """
    if allowed_types is None:
        allowed_types = DEFAULT_INSTRUMENT_TYPES

    if exclusion_db.is_excluded(ticker):
        return TickerMeta(ticker=ticker, in_scope=False, tier=None, rejection_reason="excluded")

    if not _region_eligible(ticker):
        return TickerMeta(ticker=ticker, in_scope=False, tier=None, rejection_reason="region not eligible")

    if not _type_eligible(instrument_type, allowed_types):
        return TickerMeta(ticker=ticker, in_scope=False, tier=None, rejection_reason=f"instrument type '{instrument_type}' not allowed")

    tier = _assign_tier(ticker)
    return TickerMeta(ticker=ticker, in_scope=True, tier=tier, rejection_reason="")


def in_universe(ticker: str, instrument_type: str = "single_stock") -> bool:
    """Convenience wrapper — returns True/False only."""
    return check(ticker, instrument_type).in_scope


# ── Tier assignment ───────────────────────────────────────────────────────────

def _assign_tier(ticker: str) -> int:
    if _is_holding(ticker):
        return 0
    if _is_watchlist(ticker):
        return 1
    if ticker.upper() in _T2_SECTOR_LEADERS:
        return 2
    return 4  # default — T3 assigned by peer/supply-chain discovery, T4 by A1


def _is_holding(ticker: str) -> bool:
    from src.desks.equity_ls.infrastructure import portfolio_db
    return portfolio_db.is_holding(ticker)


def _is_watchlist(ticker: str) -> bool:
    from src.desks.equity_ls.infrastructure import portfolio_db
    return portfolio_db.is_watchlist(ticker)


# ── Internal checks ───────────────────────────────────────────────────────────

def _region_eligible(ticker: str) -> bool:
    return _get_suffix(ticker) in ELIGIBLE_SUFFIXES


def _type_eligible(instrument_type: str, allowed_types: set[str]) -> bool:
    return instrument_type in allowed_types


def _get_suffix(ticker: str) -> str:
    return ("." + ticker.rsplit(".", 1)[-1]) if "." in ticker else ""
