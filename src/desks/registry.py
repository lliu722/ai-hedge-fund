"""Desk registry — the single source of truth for what desks exist.

Canonical list: docs/DESKS.md §3. Maps desk_id → desk class. Desks are
registered here as they are built; `pm_risk` is the orchestrator and is NOT in
the idea-desk registry (it consumes IdeaCards, it doesn't emit them).

Pragmatic note (Louis's book is equity-focused): desks for markets not actively
traded can stay unregistered/dormant until needed — register a desk only once it
has a real implementation.
"""
from __future__ import annotations

# desk_id → fully-qualified intent. Classes are added as each desk is implemented.
DESK_IDS: dict[str, str] = {
    "equity_ls":   "Equity Long/Short — single-name & sector equity ideas",
    "macro":       "Macro — regime → rates/FX/index/commodity expression",
    "credit":      "Credit — cycle, spreads, default/refi risk",
    "commodities": "Commodities — energy/metals/ags supply-demand",
    "options_vol": "Options/Volatility — hedging, defined-risk, vol/income",
    "crypto":      "Crypto — BTC/ETH/crypto-equity, risk-capped",
    "event":       "Event-Driven — earnings, M&A, regulation, litigation",
    "quant":       "Quant/Systematic — signals, screens, backtests + signal-as-a-service",
}

# Concrete classes, populated as desks are built: {desk_id: Desk subclass}.
REGISTRY: dict[str, type] = {}


def register(desk_id: str, desk_cls: type) -> None:
    """Register a built desk class against its id."""
    if desk_id not in DESK_IDS:
        raise ValueError(f"Unknown desk_id '{desk_id}'. Add it to DESK_IDS first.")
    REGISTRY[desk_id] = desk_cls


def get_desk(desk_id: str) -> type:
    return REGISTRY[desk_id]


def active_desks() -> list[str]:
    """Desk ids that have a concrete implementation registered."""
    return sorted(REGISTRY.keys())
