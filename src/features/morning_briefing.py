"""Standalone morning briefing reference implementation.

degrade_to: if PortfolioAdapter returns no positions, return
"Morning Briefing — no positions available (data pending)".
"""
from datetime import date

from src.adapters.portfolio import PortfolioAdapter
from src.adapters.prices import PriceAdapter


def _price_value(price_data: object) -> object:
    if isinstance(price_data, dict):
        return price_data.get("price", "data pending")
    if price_data is None:
        return "data pending"
    return price_data


def build_morning_briefing() -> str:
    positions = PortfolioAdapter().fetch()
    if not positions:
        return "Morning Briefing — no positions available (data pending)"

    tickers = [position.name_ref for position in positions]
    prices = PriceAdapter().fetch(tickers)

    lines = [f"Morning Briefing — {date.today().isoformat()}"]
    for position in sorted(positions, key=lambda p: p.pnl_pct, reverse=True):
        price = _price_value(prices.get(position.name_ref))
        lines.append(f"{position.name_ref}: {price} ({position.pnl_pct}%)")
    return "\n".join(lines)
