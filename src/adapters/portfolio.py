from src.adapters.base import Adapter
from src.core.objects import Position


class PortfolioAdapter(Adapter):
    def __init__(self) -> None:
        self.on_failure = "return empty list; caller reports no positions available"
        super().__init__()

    def fetch(self) -> list[Position]:
        try:
            from src.tools.notion_holdings import get_holdings_cached

            holdings = get_holdings_cached()
        except Exception:
            return []

        positions: list[Position] = []
        for ticker, data in holdings.items():
            shares = data.get("shares", 0)
            if shares <= 0:
                continue
            positions.append(
                Position(
                    name_ref=ticker,
                    account=data.get("account", "default"),
                    shares=shares,
                    avg_cost=data.get("avg_cost", 0),
                    current_price=data.get("current_price", 0),
                )
            )
        return positions
