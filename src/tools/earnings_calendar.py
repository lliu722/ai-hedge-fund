import yfinance as yf
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

WATCHLIST = ["NVDA", "TSM", "AVGO", "AMD", "ASML", "ARM", "ALAB", "PLTR", "APP", "CEG"]


def _fetch_one(ticker):
    today = datetime.today().date()
    try:
        info = yf.Ticker(ticker).info
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
