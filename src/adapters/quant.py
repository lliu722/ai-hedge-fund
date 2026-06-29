from src.adapters.base import Adapter


class QuantAdapter(Adapter):
    def __init__(self) -> None:
        self.on_failure = "return empty list; caller reports quant unavailable"
        super().__init__()

    def fetch(self, tickers: list[str]) -> list[dict]:
        try:
            from src.tools.quant.factors import score_universe

            df = score_universe(tickers)
            return df.to_dict("records")
        except Exception:
            return []
