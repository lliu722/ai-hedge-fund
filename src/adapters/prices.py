from src.adapters.base import Adapter


class PriceAdapter(Adapter):
    def __init__(self) -> None:
        self.on_failure = "return empty dict; caller treats missing prices as stale and degrades"
        super().__init__()

    def fetch(self, tickers: list[str]) -> dict:
        try:
            from src.tools.prices import get_live_prices

            return get_live_prices(tickers)
        except Exception:
            return {}
