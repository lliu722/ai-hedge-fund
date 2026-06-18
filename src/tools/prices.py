import yfinance as yf
from datetime import datetime

def get_live_prices(tickers: list) -> dict:
    """
    Fetch live prices and key metrics for a list of tickers.
    Returns a dict of {ticker: {price, change_pct, week52_high, week52_low, market_cap}}
    """
    results = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            results[ticker] = {
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "change_pct": round(info.get("regularMarketChangePercent", 0), 2),
                "week52_high": info.get("fiftyTwoWeekHigh"),
                "week52_low": info.get("fiftyTwoWeekLow"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "volume": info.get("regularMarketVolume"),
            }
        except Exception as e:
            print(f"Error fetching {ticker}: {e}")
            results[ticker] = {}
    return results

def get_portfolio_summary(portfolio_json: dict) -> dict:
    """
    Given a portfolio.json holdings dict, calculate live allocation percentages.
    """
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
    print("Testing live prices...\n")
    tickers = ["NVDA", "TSM", "AVGO", "AMD", "ASML"]
    prices = get_live_prices(tickers)
    for ticker, data in prices.items():
        print(f"{ticker}: ${data.get('price')} ({data.get('change_pct')}%) | 52w High: ${data.get('week52_high')}")
