import yfinance as yf
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

WATCHLIST = ["NVDA", "TSM", "AVGO", "AMD", "ASML", "ARM", "ALAB", "PLTR", "APP", "CEG"]


_NO_EARNINGS = {"date": "Not available", "days_until": None, "alert": False}


def _has_earnings(ticker: str) -> bool:
    """
    Only real equities have earnings dates. Crypto, indices, and placeholder
    rows do not — looking them up is a guaranteed 404 every single cycle.

    This ran unnormalized against the whole holdings list from both the
    morning briefing and every market-open alert, so the live logs carried a
    steady drip of 404s for ".VIX", "MATIC", "SOL" and the literal
    placeholder string "— (SECTOR)". Two real costs beyond the noise: it
    burns yfinance quota on calls that can never succeed (the same session
    also shows 401 "Invalid Crumb" rate-limit errors), and a constant stream
    of expected 404s is exactly what hides an unexpected one.
    """
    from src.tools.prices import normalize_ticker, CRYPTO_IDS
    if not ticker or ticker in CRYPTO_IDS:
        return False
    norm = normalize_ticker(ticker)
    # normalize_ticker returns "" for junk/placeholder rows and a "CRYPTO:"
    # prefix for coins routed to CoinGecko.
    if not norm or norm.startswith("CRYPTO:") or norm.startswith("^"):
        return False
    return True


def _fetch_one(ticker):
    today = datetime.today().date()
    if not _has_earnings(ticker):
        return ticker, dict(_NO_EARNINGS)
    try:
        from src.tools.prices import normalize_ticker
        info = yf.Ticker(normalize_ticker(ticker)).info
        next_earnings = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
        if next_earnings:
            earnings_date = datetime.fromtimestamp(next_earnings, tz=timezone.utc).date()
            days_until = (earnings_date - today).days
            return ticker, {"date": str(earnings_date), "days_until": days_until, "alert": 0 <= days_until <= 7}
        return ticker, {"date": "Not available", "days_until": None, "alert": False}
    except Exception:
        return ticker, {"date": "Error", "days_until": None, "alert": False}


def get_earnings_dates(tickers: list) -> dict:
    """Fetch earnings dates for all tickers in parallel — 10x faster than sequential."""
    with ThreadPoolExecutor(max_workers=10) as ex:
        results = dict(ex.map(_fetch_one, tickers))
    return results


def get_upcoming_earnings(tickers: list, days_ahead: int = 60) -> list:
    dates = get_earnings_dates(tickers)
    upcoming = [
        {"ticker": t, "date": d["date"], "days_until": d["days_until"], "alert": d["alert"]}
        for t, d in dates.items()
        if d.get("days_until") is not None and 0 <= d["days_until"] <= days_ahead
    ]
    return sorted(upcoming, key=lambda x: x["days_until"])


if __name__ == "__main__":
    import time
    print("Earnings Calendar")
    print("As of: " + datetime.today().strftime("%Y-%m-%d") + "\n")
    start = time.time()
    all_dates = get_earnings_dates(WATCHLIST)
    for ticker, data in all_dates.items():
        alert = " SOON" if data["alert"] else ""
        print("  " + ticker + ": " + data["date"] + " (" + str(data["days_until"]) + " days)" + alert)
    print("\nTook " + str(round(time.time() - start, 1)) + "s")
