"""Standalone morning briefing reference implementation (spine + canonical objects).

Builds a briefing string from Position objects (via PortfolioAdapter) and live
prices (via PriceAdapter). No data SDK is imported here — only the two adapters.

degrade_to: if PortfolioAdapter returns no positions, return
"Morning Briefing — no positions available (data pending)".
"""
from datetime import date

from src.adapters.portfolio import PortfolioAdapter
from src.adapters.prices import PriceAdapter


def build_morning_briefing() -> str:
    positions = PortfolioAdapter().fetch()
    if not positions:
        return "Morning Briefing — no positions available (data pending)"

    tickers = [p.name_ref for p in positions]
    # PriceAdapter returns {ticker: {"price": float, "change_pct": float}}.
    # A failed ticker is PRESENT but maps to {} — .get("price") yields None.
    prices = PriceAdapter().fetch(tickers)

    rows = []  # (sort_key, line)
    for p in positions:
        price = prices.get(p.name_ref, {}).get("price")
        if not price:  # None or 0 → data not available
            rows.append((-9999, f"{p.name_ref}: data pending"))
        else:
            pnl_pct = round((price - p.avg_cost) / p.avg_cost * 100, 1) if p.avg_cost else 0.0
            rows.append((pnl_pct, f"{p.name_ref}: ${price} ({pnl_pct}% vs cost)"))

    rows.sort(key=lambda r: r[0], reverse=True)
    lines = [f"Morning Briefing — {date.today().isoformat()}"] + [line for _, line in rows]
    return "\n".join(lines)
