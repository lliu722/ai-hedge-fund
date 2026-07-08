"""
Cross-Function Risk Layer (C) — minimal first cut.

Full spec has 8 checks (Thesis, Valuation, Liquidity, Event, Concentration,
Correlation, Data Quality, Portfolio Relevance). Per the 2026-07 pre-build
audit, three are built now because they're needed before A3/A4 exist, not
after — a levered/concentrated book with no automated concentration check is
a live gap, not a theoretical one (Zhipu is ~30% of the HK book today):

  concentration  — single-name weight within its own currency book (USD/HKD
                    books aren't summed together — see currency_for() in
                    universe.py; mixing them would understate concentration)
  liquidity      — position size vs. trading volume (days-to-exit at 100% ADV)
  data_quality   — are the fields a scoring decision would depend on actually
                    present, or would we be scoring on holes?

Pure functions — no network calls, no LLM calls. Callers (screener, A2, A4)
supply the data; this module only judges it. Remaining 5 checks (Thesis,
Valuation, Event, Correlation, Portfolio Relevance) land alongside A3/A4.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RiskFlag:
    check: str          # "concentration" | "liquidity" | "data_quality"
    severity: str       # "info" | "warning" | "critical"
    ticker: str | None
    message: str
    detail: dict = field(default_factory=dict)


# ── Concentration ──────────────────────────────────────────────────────────────

def scan_concentration(
    holdings: list[dict],
    prices: dict[str, float],
    warning_threshold: float = 0.15,
    critical_threshold: float = 0.25,
) -> list[RiskFlag]:
    """
    Single-name concentration within each currency book.

    Args:
        holdings: rows from portfolio_db.get_holdings() — needs 'ticker', 'shares'.
        prices:   ticker -> current market price. Missing prices fall back to
                  avg_cost if present on the holding row, else the position is
                  skipped (can't assess concentration without a value).
        warning_threshold / critical_threshold: fraction of the BOOK (not the
                  whole multi-currency portfolio) a single name can be before
                  flagging. USD and HKD books are kept separate — a position
                  that's 25% of the HK book but 2% of combined USD+HKD value
                  is still a real concentration risk in the account it lives in.

    Returns one RiskFlag per position that crosses warning_threshold, sorted
    by severity then weight descending.
    """
    from src.desks.equity_ls.infrastructure.b1_universe.universe import currency_for

    by_currency: dict[str, list[tuple[str, float, bool]]] = {}
    for h in holdings:
        ticker = h["ticker"]
        shares = h.get("shares") or 0
        if shares <= 0:
            continue
        live_price = prices.get(ticker)
        price = live_price or h.get("avg_cost")
        if not price:
            continue
        stale = live_price is None
        value = shares * price
        by_currency.setdefault(currency_for(ticker), []).append((ticker, value, stale))

    flags: list[RiskFlag] = []
    for currency, positions in by_currency.items():
        book_total = sum(v for _, v, _ in positions)
        if book_total <= 0:
            continue
        for ticker, value, stale in positions:
            weight = value / book_total
            if stale:
                # No live price — weight is computed off cost basis and is
                # unreliable in exactly the direction that hides risk: a
                # position up big (or down big) has its true weight understated
                # (or overstated). Flag this regardless of where it lands.
                flags.append(RiskFlag(
                    check="concentration", severity="warning", ticker=ticker,
                    message=f"{ticker}: no live price — weight ({weight:.0%} of {currency} book) "
                            f"computed off cost basis and may be significantly understated",
                    detail={"currency": currency, "weight": round(weight, 4),
                            "book_total": book_total, "stale_price": True},
                ))
                continue
            if weight >= critical_threshold:
                severity = "critical"
            elif weight >= warning_threshold:
                severity = "warning"
            else:
                continue
            flags.append(RiskFlag(
                check="concentration", severity=severity, ticker=ticker,
                message=f"{ticker} is {weight:.0%} of the {currency} book "
                        f"(threshold {warning_threshold:.0%})",
                detail={"currency": currency, "weight": round(weight, 4),
                        "book_total": book_total, "stale_price": False},
            ))

    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    flags.sort(key=lambda f: (severity_rank[f.severity], -f.detail["weight"]))
    return flags


# ── Liquidity ─────────────────────────────────────────────────────────────────

def check_liquidity(
    ticker: str,
    position_value: float,
    avg_volume: float | None,
    price: float | None,
    max_days_threshold: float = 5.0,
) -> RiskFlag | None:
    """
    Days-to-exit at 100% of average daily volume, without moving the price.
    A position that would take >max_days_threshold days to unwind at full
    ADV is a real constraint on how fast you can actually act on a Sell call.
    """
    if not avg_volume or not price or avg_volume <= 0 or price <= 0:
        return RiskFlag(
            check="liquidity", severity="warning", ticker=ticker,
            message=f"{ticker}: no volume data — cannot assess exit liquidity",
        )

    adv_dollars = avg_volume * price
    days_to_exit = position_value / adv_dollars if adv_dollars > 0 else float("inf")

    if days_to_exit <= max_days_threshold:
        return None

    severity = "critical" if days_to_exit > max_days_threshold * 3 else "warning"
    return RiskFlag(
        check="liquidity", severity=severity, ticker=ticker,
        message=f"{ticker}: ~{days_to_exit:.1f} days to exit at 100% ADV "
                f"(threshold {max_days_threshold:.0f}d)",
        detail={"days_to_exit": round(days_to_exit, 1), "adv_dollars": adv_dollars},
    )


# ── Data quality ──────────────────────────────────────────────────────────────

# Fields a scoring decision materially depends on. Missing these isn't a
# minor gap — the composite score becomes a guess dressed up as a number.
_CRITICAL_FIELDS = ("price", "market_cap")
_SCORING_FIELDS = (
    "trailing_pe", "forward_pe", "ev_to_ebitda", "price_to_sales",
    "revenue_growth", "gross_margins", "operating_margins", "free_cash_flow",
    "return_on_equity", "debt_to_equity", "current_ratio",
)


def check_data_quality(
    ticker: str,
    market_data: dict,
    min_scoring_fields: int = 5,
) -> RiskFlag | None:
    """
    Flags a ticker whose data is too thin to score reliably. Two tiers:
      critical — missing price or market_cap (hard filters can't even run)
      warning  — fewer than min_scoring_fields of the fields the 7 screener
                 engines actually read are populated (score would be built
                 mostly on Nones, which the engines silently treat as 0
                 contribution rather than "unknown" — a thin-data name and a
                 genuinely weak name can look identical in the composite).
    """
    if "_error" in market_data:
        return RiskFlag(
            check="data_quality", severity="critical", ticker=ticker,
            message=f"{ticker}: data fetch failed — {market_data['_error']}",
        )

    missing_critical = [f for f in _CRITICAL_FIELDS if market_data.get(f) is None]
    if missing_critical:
        return RiskFlag(
            check="data_quality", severity="critical", ticker=ticker,
            message=f"{ticker}: missing critical field(s) {missing_critical} — cannot screen",
            detail={"missing": missing_critical},
        )

    present = sum(1 for f in _SCORING_FIELDS if market_data.get(f) is not None)
    if present < min_scoring_fields:
        return RiskFlag(
            check="data_quality", severity="warning", ticker=ticker,
            message=f"{ticker}: only {present}/{len(_SCORING_FIELDS)} scoring fields "
                    f"populated — composite score may be unreliable",
            detail={"fields_present": present, "fields_total": len(_SCORING_FIELDS)},
        )

    return None


# ── Combined entry point ──────────────────────────────────────────────────────

def run_minimal_checks(
    ticker: str,
    market_data: dict,
    position_value: float | None = None,
) -> list[RiskFlag]:
    """
    Single-name checks only (data_quality always; liquidity if position_value
    given). Portfolio-wide concentration is a separate call — scan_concentration()
    needs the whole book, not one ticker — call it once per monitor/A4 run,
    not per name.
    """
    flags = []
    dq = check_data_quality(ticker, market_data)
    if dq:
        flags.append(dq)

    if position_value is not None:
        liq = check_liquidity(
            ticker, position_value,
            avg_volume=market_data.get("avg_volume_10d"),
            price=market_data.get("price"),
        )
        if liq:
            flags.append(liq)

    return flags
