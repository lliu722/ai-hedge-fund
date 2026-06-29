from src.adapters.base import Adapter


class FundamentalsAdapter(Adapter):
    def __init__(self) -> None:
        self.on_failure = "return empty dict; valuation lens degrades to 'data partial'"
        super().__init__()

    def fetch(self, ticker: str) -> dict:
        try:
            import yfinance as yf

            info = yf.Ticker(ticker).info
            return {
                "free_cash_flow": info.get("freeCashflow"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "market_cap": info.get("marketCap"),
                "beta": info.get("beta"),
                "revenue": info.get("totalRevenue"),
                "revenue_growth": info.get("revenueGrowth"),
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "profit_margins": info.get("profitMargins"),
                "current_price": info.get("currentPrice"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            }
        except Exception:
            return {}
