from src.adapters.base import Adapter


class RiskDataAdapter(Adapter):
    def __init__(self) -> None:
        self.on_failure = (
            "return empty correlations + UNKNOWN regime; caller degrades to concentration-only"
        )
        super().__init__()

    def fetch(self, tickers: list[str]) -> dict:
        result = {"correlations": [], "regime": "UNKNOWN"}

        try:
            from src.tools.ficc import get_macro_regime

            result["regime"] = get_macro_regime()
        except Exception:
            pass

        excluded_suffixes = [".HK", ".SS", ".SZ", ".TW"]
        excluded_assets = {"BTC", "ETH", "SOL", "MATIC", "POL"}
        us = [
            ticker
            for ticker in tickers
            if not any(ticker.endswith(suffix) for suffix in excluded_suffixes)
            and ticker not in excluded_assets
        ][:20]
        if len(us) < 2:
            return result

        try:
            import yfinance as yf

            closes = yf.download(us, period="1y", progress=False)["Close"]
            returns = closes.pct_change().dropna()
            corr = returns.corr()
            pairs = []
            for i, left in enumerate(us):
                for right in us[i + 1 :]:
                    value = corr.loc[left, right]
                    if value > 0.70:
                        pairs.append(
                            {"a": left, "b": right, "corr": round(float(value), 2)}
                        )
            result["correlations"] = pairs
        except Exception:
            pass

        return result
