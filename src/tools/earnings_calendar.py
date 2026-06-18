import yfinance as yf
from datetime import datetime

WATCHLIST = ["NVDA", "TSM", "AVGO", "AMD", "ASML", "ARM", "ALAB", "PLTR", "APP", "CEG"]

def get_earnings_dates(tickers: list) -> dict:
    results = {}
    today = datetime.today().date()

    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            # Try getting earnings dates from info
            info = stock.info
            next_earnings = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
            if next_earnings:
                from datetime import timezone
                earnings_date = datetime.fromtimestamp(next_earnings, tz=timezone.utc).date()
                days_until = (earnings_date - today).days
                results[ticker] = {
                    "date": str(earnings_date),
                    "days_until": days_until,
                    "alert": 0 <= days_until <= 7,
                }
            else:
                results[ticker] = {"date": "Not available", "days_until": None, "alert": False}
        except Exception as e:
            results[ticker] = {"date": f"Error: {str(e)[:50]}", "days_until": None, "alert": False}

    return results

def get_upcoming_earnings(tickers: list, days_ahead: int = 60) -> list:
    dates = get_earnings_dates(tickers)
    upcoming = []
    for ticker, data in dates.items():
        days = data.get("days_until")
        if days is not None and 0 <= days <= days_ahead:
            upcoming.append({
                "ticker": ticker,
                "date": data["date"],
                "days_until": days,
                "alert": data["alert"],
            })
    return sorted(upcoming, key=lambda x: x["days_until"])

if __name__ == "__main__":
    print("Earnings Calendar")
    print(f"As of: {datetime.today().strftime('%Y-%m-%d')}\n")
    all_dates = get_earnings_dates(WATCHLIST)
    for ticker, data in all_dates.items():
        alert = " ⚠️ SOON" if data["alert"] else ""
        print(f"  {ticker}: {data['date']} ({data['days_until']} days){alert}")