import yfinance as yf
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# Simple in-memory cache: {ticker: (timestamp, data)}
_cache = {}
_CACHE_SECONDS = 120  # prices considered fresh for 2 minutes


def _fetch_one_detailed(ticker: str) -> dict:
    """Fetch full stats for a single ticker via yfinance .info (rich, for single lookups)."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
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


def _cached(ticker: str, detailed: bool = False):
    key = f"{ticker}:{'detailed' if detailed else 'fast'}"
    entry = _cache.get(key)
    if entry:
        ts, data = entry
        if (datetime.now() - ts).total_seconds() < _CACHE_SECONDS:
            return data
    return None


def _fetch_batch_fast(tickers: list) -> dict:
    """Fetch price + daily change for many tickers in one batched yf.download call."""
    results = {}
    if not tickers:
        return results
    try:
        data = yf.download(
            tickers,
            period="2d",
            progress=False,
            group_by="ticker",
            threads=True,
        )
    except Exception:
        return results

    for t in tickers:
        try:
            # Handle single vs multi-ticker dataframe shapes
            if len(tickers) == 1:
                closes = data["Close"].dropna()
            else:
                closes = data[t]["Close"].dropna()

            if len(closes) >= 2:
                today = float(closes.iloc[-1])
                prev = float(closes.iloc[-2])
                change_pct = round((today - prev) / prev * 100, 2) if prev else 0
                results[t] = {
                    "price": round(today, 2),
                    "change_pct": change_pct,
                    "week52_high": None,
                    "week52_low": None,
                    "market_cap": None,
                    "pe_ratio": None,
                    "volume": None,
                }
            elif len(closes) == 1:
                results[t] = {
                    "price": round(float(closes.iloc[-1]), 2),
                    "change_pct": 0,
                    "week52_high": None, "week52_low": None,
                    "market_cap": None, "pe_ratio": None, "volume": None,
                }
            else:
                results[t] = {}
        except Exception:
            results[t] = {}
    return results


def get_live_prices(tickers: list, detailed: bool = False) -> dict:
    """
    Fetch live prices for a list of tickers.
    detailed=False (default): fast batched fetch, price + change (best for portfolio sweeps).
    detailed=True: full stats including P/E and 52-week range (best for single lookups).
    Failed tickers (e.g. HK/crypto not yet supported) return {} but stay in the dict.
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
            # Parallel detailed fetch for single/few lookups
            with ThreadPoolExecutor(max_workers=10) as executor:
                fetched = dict(zip(to_fetch, executor.map(_fetch_one_detailed, to_fetch)))
        else:
            # One batched call for the whole list
            fetched = _fetch_batch_fast(to_fetch)

        for t, data in fetched.items():
            results[t] = data
            if data:
                key = f"{t}:{'detailed' if detailed else 'fast'}"
                _cache[key] = (datetime.now(), data)

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
    return {"total_value": total_value, "positions": positions, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")}


if __name__ == "__main__":
    import time
    print("Testing FAST batch (portfolio sweep)...")
    start = time.time()
    tickers = ["NVDA", "TSM", "AVGO", "AMD", "ASML", "ARM", "ALAB", "PLTR", "APP", "CEG"]
    prices = get_live_prices(tickers)
    for ticker, data in prices.items():
        print(f"{ticker}: ${data.get('price')} ({data.get('change_pct')}%)")
    print(f"\nFast fetch took {time.time()-start:.1f}s\n")

    print("Testing DETAILED single lookup...")
    start = time.time()
    detail = get_live_prices(["NVDA"], detailed=True)
    print(f"NVDA detailed: {detail['NVDA']}")
    print(f"Detailed fetch took {time.time()-start:.1f}s")