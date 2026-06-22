import yfinance as yf
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ── Cache ─────────────────────────────────────────────────────────────────────
_cache = {}
_CACHE_SECONDS = 120

# ── Crypto ID map (Notion ticker -> CoinGecko ID) ─────────────────────────────
CRYPTO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "MATIC": "polygon-ecosystem-token",
    "POL": "polygon-ecosystem-token",
}

# ── Index symbol fixes ────────────────────────────────────────────────────────
INDEX_MAP = {
    ".VIX": "^VIX",
    "800000.HK": "^HSI",
    "^KS11": "^KS11",
}


# ── Ticker normaliser ─────────────────────────────────────────────────────────

def normalize_ticker(ticker: str) -> str:
    """
    Convert a Notion-stored ticker to its yfinance-correct format.
    Returns "" for placeholder/junk rows (skipped by fetchers).
    Returns "CRYPTO:XXX" for crypto tickers (routed to CoinGecko).
    """
    t = ticker.strip().upper()

    # Placeholder / junk rows e.g. "— (SECTOR)"
    if not t or t.startswith("—") or "(" in t:
        return ""

    # Index fixes
    if t in INDEX_MAP:
        return INDEX_MAP[t]

    # HK stocks: yfinance wants 4-digit zero-padded + .HK
    if t.endswith(".HK"):
        num = t[:-3].lstrip("0")
        if num.isdigit() and len(num) <= 4:
            return f"{num.zfill(4)}.HK"
        return t  # 5-6 digit = likely mislabelled, leave as-is

    # Crypto: route to CoinGecko
    if t in CRYPTO_IDS:
        return f"CRYPTO:{t}"

    # US, .SS, .SZ, .TW pass through unchanged
    return t


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cached(ticker: str, detailed: bool = False):
    key = f"{ticker}:{'detailed' if detailed else 'fast'}"
    entry = _cache.get(key)
    if entry:
        ts, data = entry
        if (datetime.now() - ts).total_seconds() < _CACHE_SECONDS:
            return data
    return None


def _store_cache(ticker: str, data: dict, detailed: bool = False):
    if data:
        key = f"{ticker}:{'detailed' if detailed else 'fast'}"
        _cache[key] = (datetime.now(), data)


# ── Fetchers ──────────────────────────────────────────────────────────────────

def _fetch_crypto_prices(tickers: list) -> dict:
    """Fetch crypto prices from CoinGecko free API — no key required."""
    results = {}
    ticker_to_id = {t: CRYPTO_IDS[t] for t in tickers if t in CRYPTO_IDS}
    if not ticker_to_id:
        return {t: {} for t in tickers}

    ids = ",".join(set(ticker_to_id.values()))
    try:
        r = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={ids}&vs_currencies=usd&include_24hr_change=true",
            timeout=10,
        )
        data = r.json()
        for ticker, cg_id in ticker_to_id.items():
            cg_data = data.get(cg_id, {})
            price = cg_data.get("usd")
            change = cg_data.get("usd_24h_change")
            results[ticker] = {
                "price": round(price, 2),
                "change_pct": round(change, 2) if change else 0,
                "week52_high": None, "week52_low": None,
                "market_cap": None, "pe_ratio": None, "volume": None,
            } if price else {}
    except Exception:
        results = {t: {} for t in tickers}
    return results


def _fetch_one_detailed(ticker: str) -> dict:
    """Fetch full stats for a single ticker via yfinance .info (rich data, single lookups)."""
    yf_ticker = normalize_ticker(ticker)
    if not yf_ticker or yf_ticker.startswith("CRYPTO:"):
        # For crypto single lookups, fall back to CoinGecko
        if ticker in CRYPTO_IDS:
            return _fetch_crypto_prices([ticker]).get(ticker, {})
        return {}
    try:
        info = yf.Ticker(yf_ticker).info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price:
            return {}
        return {
            "price": round(price, 2),
            "change_pct": round(info.get("regularMarketChangePercent", 0) or 0, 2),
            "week52_high": info.get("fiftyTwoWeekHigh"),
            "week52_low": info.get("fiftyTwoWeekLow"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "volume": info.get("regularMarketVolume"),
        }
    except Exception:
        return {}


def _fetch_batch_fast(tickers: list) -> dict:
    """
    Fetch price + daily change for many tickers at once.
    - Equity/ETF/index: single batched yf.download call
    - Crypto: single batched CoinGecko call
    Results keyed to the ORIGINAL Notion ticker.
    """
    results = {}
    if not tickers:
        return results

    norm_map = {}    # yfinance_ticker -> original_ticker
    crypto_list = [] # original tickers to fetch via CoinGecko

    for t in tickers:
        n = normalize_ticker(t)
        if not n:
            results[t] = {}          # placeholder row
        elif n.startswith("CRYPTO:"):
            crypto_list.append(t)    # route to CoinGecko
        else:
            norm_map[n] = t          # route to yfinance

    # ── CoinGecko fetch ───────────────────────────────────────────────────────
    if crypto_list:
        results.update(_fetch_crypto_prices(crypto_list))

    # ── yfinance batch fetch ──────────────────────────────────────────────────
    yf_tickers = list(norm_map.keys())
    if not yf_tickers:
        return results  # nothing left to fetch from yfinance

    try:
        data = yf.download(
            yf_tickers,
            period="2d",
            progress=False,
            group_by="ticker",
            threads=True,
        )
    except Exception:
        for orig in norm_map.values():
            results[orig] = {}
        return results

    for yf_t in yf_tickers:
        orig = norm_map[yf_t]
        try:
            closes = data["Close"].dropna() if len(yf_tickers) == 1 else data[yf_t]["Close"].dropna()
            if len(closes) >= 2:
                today = float(closes.iloc[-1])
                prev = float(closes.iloc[-2])
                results[orig] = {
                    "price": round(today, 2),
                    "change_pct": round((today - prev) / prev * 100, 2) if prev else 0,
                    "week52_high": None, "week52_low": None,
                    "market_cap": None, "pe_ratio": None, "volume": None,
                }
            elif len(closes) == 1:
                results[orig] = {
                    "price": round(float(closes.iloc[-1]), 2),
                    "change_pct": 0,
                    "week52_high": None, "week52_low": None,
                    "market_cap": None, "pe_ratio": None, "volume": None,
                }
            else:
                results[orig] = {}
        except Exception:
            results[orig] = {}

    return results


# ── Public API ────────────────────────────────────────────────────────────────

def get_live_prices(tickers: list, detailed: bool = False) -> dict:
    """
    Fetch live prices for a list of tickers.
    detailed=False: fast batched fetch — price + change (use for portfolio sweeps).
    detailed=True:  full stats with P/E and 52w range (use for single-ticker lookups).
    Failed tickers return {} but remain in the dict.
    """
    results = {}
    to_fetch = []

    for t in tickers:
        cached = _cached(t, detailed)
        if cached is not None:
            results[t] = cached
        else:
            to_fetch.append(t)

    if to_fetch:
        if detailed:
            with ThreadPoolExecutor(max_workers=10) as executor:
                fetched = dict(zip(to_fetch, executor.map(_fetch_one_detailed, to_fetch)))
        else:
            fetched = _fetch_batch_fast(to_fetch)

        for t, data in fetched.items():
            results[t] = data
            _store_cache(t, data, detailed)

    return {t: results.get(t, {}) for t in tickers}


def get_portfolio_summary(portfolio_json: dict) -> dict:
    """Given a portfolio.json holdings dict, calculate live allocation percentages."""
    tickers = list(portfolio_json.get("holdings", {}).keys())
    prices = get_live_prices(tickers)
    holdings = portfolio_json.get("holdings", {})
    total_value = 0
    positions = {}
    for ticker, data in holdings.items():
        shares = data.get("shares", 0)
        price = prices.get(ticker, {}).get("price") or 0
        value = shares * price
        total_value += value
        positions[ticker] = {
            "shares": shares,
            "price": price,
            "value": value,
            "change_pct": prices.get(ticker, {}).get("change_pct", 0),
        }
    for ticker in positions:
        positions[ticker]["allocation_pct"] = round(
            (positions[ticker]["value"] / total_value * 100) if total_value > 0 else 0, 2
        )
    return {
        "total_value": total_value,
        "positions": positions,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ── Test ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import time
    print("Testing: equities + HK + A-share + crypto + index...\n")
    start = time.time()
    test_tickers = ["NVDA", "00700.HK", "601689.SS", "BTC", "ETH", "SOL", "MATIC", "^VIX"]
    prices = get_live_prices(test_tickers)
    for t, d in prices.items():
        print(f"{t}: ${d.get('price')} ({d.get('change_pct')}%)")
    print(f"\nFast batch took {time.time()-start:.1f}s\n")

    print("Detailed single lookup (NVDA)...")
    start = time.time()
    d = get_live_prices(["NVDA"], detailed=True)["NVDA"]
    print(f"NVDA: ${d.get('price')} | P/E: {d.get('pe_ratio')} | 52w: {d.get('week52_low')}-{d.get('week52_high')}")
    print(f"Detailed took {time.time()-start:.1f}s")