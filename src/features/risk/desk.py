"""Risk Watch on-demand desk entry points.

degrade_to: if price data is unavailable and no market value can be computed,
return a DATA Signal so callers see that concentration could not be computed.
"""
from src.adapters.prices import PriceAdapter
from src.adapters.risk_data import RiskDataAdapter
from src.core.objects import Action, Position, Recommendation, Signal, SignalType


def _market_values(positions: list[Position]) -> dict[str, float]:
    tickers = [position.name_ref for position in positions]
    prices = PriceAdapter().fetch(tickers)
    return {
        position.name_ref: position.shares
        * (prices.get(position.name_ref, {}).get("price") or 0)
        for position in positions
    }


def run_risk_sweep(positions: list[Position]) -> list[Signal]:
    if not positions:
        return [
            Signal(
                type=SignalType.DATA,
                subject_ref="PORTFOLIO",
                severity=2,
                summary="no positions to assess",
                source_desk="risk_watch",
            )
        ]

    tickers = [position.name_ref for position in positions]
    market_values = _market_values(positions)
    total = sum(market_values.values())
    if total == 0:
        return [
            Signal(
                type=SignalType.DATA,
                subject_ref="PORTFOLIO",
                severity=3,
                summary="risk: price data unavailable — concentration not computed",
                source_desk="risk_watch",
            )
        ]

    signals: list[Signal] = []
    for position in positions:
        weight = market_values[position.name_ref] / total * 100
        if weight > 10:
            signals.append(
                Signal(
                    type=SignalType.RISK,
                    subject_ref=position.name_ref,
                    severity=min(10, round(weight / 3)),
                    summary=(
                        f"{position.name_ref} is {weight:.1f}% of book — "
                        "single-name concentration (>10%)"
                    ),
                    source_desk="risk_watch",
                )
            )

    data = RiskDataAdapter().fetch(tickers)
    for pair in data["correlations"]:
        signals.append(
            Signal(
                type=SignalType.RISK,
                subject_ref=f"{pair['a']}+{pair['b']}",
                severity=5,
                summary=(
                    f"{pair['a']} & {pair['b']} correlated {pair['corr']:.0%} — "
                    "effectively one bet"
                ),
                source_desk="risk_watch",
            )
        )
    signals.append(
        Signal(
            type=SignalType.RISK,
            subject_ref="PORTFOLIO",
            severity=2,
            summary=f"macro regime: {data['regime']}",
            source_desk="risk_watch",
        )
    )
    return signals


def vet_decision(rec: Recommendation, positions: list[Position]) -> Signal:
    market_values = _market_values(positions)
    total = sum(market_values.values())
    weight = (market_values.get(rec.name_ref, 0) / total * 100) if total else 0.0

    if rec.action in {Action.BUY, Action.ADD} and weight > 10:
        return Signal(
            type=SignalType.RISK,
            subject_ref=rec.name_ref,
            severity=8,
            summary=(
                f"CAP: {rec.name_ref} already {weight:.1f}% (>10%) — "
                "do not add; trim or hold"
            ),
            source_desk="risk_watch",
        )

    return Signal(
        type=SignalType.RISK,
        subject_ref=rec.name_ref,
        severity=1,
        summary=f"{rec.name_ref} within limits ({weight:.1f}%) — no cap",
        source_desk="risk_watch",
    )
