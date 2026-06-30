"""Quant Engine on-demand desk entry points.

degrade_to: if QuantAdapter returns no rows, return one DATA Signal for the
UNIVERSE so callers see that the quant screen is unavailable rather than silent.
"""
from src.adapters.quant import QuantAdapter
from src.core.objects import Signal, SignalType


def run_quant_screen(tickers: list[str]) -> list[Signal]:
    rows = QuantAdapter().fetch(tickers)
    if not rows:
        return [
            Signal(
                type=SignalType.DATA,
                subject_ref="UNIVERSE",
                severity=3,
                summary="quant screen unavailable — data source down",
                source_desk="quant_engine",
            )
        ]

    signals: list[Signal] = []
    for index, row in enumerate(rows):
        composite = row.get("composite") or 0.0
        severity = max(1, min(10, round(5 + composite * 1.5)))
        label = row.get("signal", "WATCH")
        rsi = row.get("rsi")
        caveat = ""
        if label == "BUY" and rsi and rsi > 70:
            caveat = f" ⚠️ RSI overbought {round(rsi)}"
        elif label == "AVOID" and rsi and rsi < 30:
            caveat = f" ⚠️ RSI oversold {round(rsi)}"

        summary = (
            f"{label} · rank {index + 1} · composite {composite:.2f} "
            f"(mom {row.get('z_mom', 0):.2f}/qual {row.get('z_quality', 0):.2f}/"
            f"val {row.get('z_value', 0):.2f}){caveat}"
        )
        signals.append(
            Signal(
                type=SignalType.THEME,
                subject_ref=row["ticker"],
                severity=severity,
                summary=summary,
                source_desk="quant_engine",
            )
        )

    return signals
