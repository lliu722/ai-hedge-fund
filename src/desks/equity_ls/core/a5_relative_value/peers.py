"""
Shared peer map + peer comparison table — the data A5 (Relative Value) is
built around, but also needed by A2 (valuation view) and A3 (read-through
analysis). Extracted from a2_deep_dive/deep_dive.py so all three share one
map instead of drifting out of sync with duplicated copies.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

# Ticker → list of closest comparable tickers. Extend as needed.
PEER_MAP: dict[str, list[str]] = {
    # US Semis
    "NVDA": ["AMD", "INTC", "AVGO", "QCOM", "TSM"],
    "AMD":  ["NVDA", "INTC", "AVGO", "QCOM"],
    "AVGO": ["NVDA", "AMD", "QCOM", "MRVL", "TXN"],
    "QCOM": ["AVGO", "AMD", "MRVL", "TXN"],
    "TSM":  ["NVDA", "ASML", "INTC", "AVGO"],
    "ASML": ["TSM", "AMAT", "KLAC", "LRCX"],
    # US Mega-cap Tech
    "AAPL": ["MSFT", "GOOGL", "META", "AMZN"],
    "MSFT": ["AAPL", "GOOGL", "AMZN", "CRM"],
    "GOOGL":["MSFT", "META", "AMZN", "SNAP"],
    "META": ["GOOGL", "SNAP", "PINS", "RDDT"],
    "AMZN": ["MSFT", "GOOGL", "BABA", "JD"],
    # Financials
    "JPM":  ["GS", "MS", "BAC", "C"],
    "GS":   ["JPM", "MS", "BX", "BAC"],
    "BLK":  ["BX", "APO", "KKR", "SCHW"],
    "V":    ["MA", "PYPL", "AXP", "FIS"],
    "MA":   ["V", "PYPL", "AXP", "FIS"],
    # Healthcare
    "LLY":  ["NVO", "PFE", "MRK", "ABBV"],
    "UNH":  ["CVS", "CI", "HUM", "MOH"],
    "JNJ":  ["ABT", "MDT", "PFE", "MRK"],
    # Energy
    "XOM":  ["CVX", "COP", "BP", "SHEL"],
    "CVX":  ["XOM", "COP", "OXY", "BP"],
    # Consumer
    "WMT":  ["COST", "TGT", "AMZN", "KR"],
    "COST": ["WMT", "TGT", "BJ", "AMZN"],
    "MCD":  ["YUM", "QSR", "CMG", "SBUX"],
    # HK / China
    "0700.HK": ["9988.HK", "BIDU", "JD", "NTES"],
    "9988.HK": ["0700.HK", "JD", "PDD", "BIDU"],
    # Japan
    "6758.T": ["7203.T", "6861.T", "AAPL", "SMSN.IL"],
    "7203.T": ["6758.T", "TSLA", "HMC", "7267.T"],
    # Crypto-equity
    "COIN":  ["MSTR", "HOOD", "MARA", "RIOT"],
}

# Sector fallback peers if ticker not in PEER_MAP.
SECTOR_FALLBACK: dict[str, list[str]] = {
    "Technology":             ["AAPL", "MSFT", "NVDA", "GOOGL"],
    "Financials":             ["JPM", "GS", "BAC", "MS"],
    "Healthcare":             ["JNJ", "LLY", "UNH", "PFE"],
    "Energy":                 ["XOM", "CVX", "COP", "BP"],
    "Consumer Cyclical":      ["AMZN", "TSLA", "MCD", "NKE"],
    "Consumer Defensive":     ["WMT", "COST", "PG", "KO"],
    "Industrials":            ["CAT", "HON", "GE", "RTX"],
    "Communication Services": ["GOOGL", "META", "DIS", "NFLX"],
    "Basic Materials":        ["LIN", "APD", "NEM", "FCX"],
}


def get_peers(ticker: str, sector: str = "", limit: int = 5) -> list[str]:
    """Closest comparable tickers for `ticker` — explicit map first, sector
    fallback second, empty list if neither has anything."""
    return PEER_MAP.get(ticker.upper(), SECTOR_FALLBACK.get(sector, []))[:limit]


def get_peer_comparison_table(ticker: str, sector: str = "") -> str:
    """
    Fetch real multiples for `ticker` + its peers and format a comparison
    table. Never raises — a peer-data failure must not sink the caller
    (A2's valuation view, A3's read-through, A5's relative-value calls).
    """
    try:
        return _build_peer_table(ticker, sector)
    except Exception as e:
        return f"[Peer comparison unavailable: {e}]"


def _build_peer_table(ticker: str, sector: str) -> str:
    from src.desks.equity_ls.infrastructure.b2_data_source.data_sources import get_market_data

    ticker = ticker.upper()
    peers = get_peers(ticker, sector)
    if not peers:
        return "No peer data available."

    all_tickers = [ticker] + [p for p in peers if p != ticker]

    def fetch(t: str) -> tuple[str, dict]:
        return t, get_market_data(t)

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = dict(ex.map(fetch, all_tickers))

    def _fmt(val, fmt=".1f", suffix=""):
        if val is None:
            return "N/A"
        try:
            return f"{val:{fmt}}{suffix}"
        except Exception:
            return "N/A"

    def _fcf_yield(d: dict) -> str:
        fcf = d.get("free_cash_flow") or 0
        cap = d.get("market_cap") or 1
        if fcf <= 0 or cap <= 0:
            return "N/A"
        return f"{fcf/cap*100:.1f}%"

    header = f"{'Ticker':<10} {'P/E':>6} {'FwdP/E':>7} {'EV/EBITDA':>10} {'P/S':>6} {'FCFYld':>7} {'GrMgn':>7} {'RevGrw':>7}"
    sep    = "-" * len(header)
    rows   = [header, sep]

    for t in all_tickers:
        d = results.get(t, {})
        if "_error" in d:
            rows.append(f"{t:<10} {'error':>6}")
            continue
        marker = " ◀" if t == ticker else ""
        rows.append(
            f"{t:<10}"
            f" {_fmt(d.get('trailing_pe'), '.1f'):>6}"
            f" {_fmt(d.get('forward_pe'), '.1f'):>7}"
            f" {_fmt(d.get('ev_to_ebitda'), '.1f'):>10}"
            f" {_fmt(d.get('price_to_sales'), '.1f'):>6}"
            f" {_fcf_yield(d):>7}"
            f" {_fmt(d.get('gross_margins') and d['gross_margins']*100, '.0f', '%'):>7}"
            f" {_fmt(d.get('revenue_growth') and d['revenue_growth']*100, '.0f', '%'):>7}"
            f"{marker}"
        )

    return "\n".join(rows)
