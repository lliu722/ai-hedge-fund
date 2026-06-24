"""
Risk Engine Phase 1 — concentration, correlation clusters, macro sensitivity.
Uses yfinance 1Y historical prices. No external dependencies beyond yfinance + numpy.
"""
import yfinance as yf
import numpy as np
from datetime import datetime
from src.tools.scheduler import PORTFOLIO_CATEGORIES


def _get_returns(tickers: list, period: str = "1y") -> "pd.DataFrame | None":
    try:
        import pandas as pd
        data = yf.download(tickers, period=period, progress=False, threads=True)
        if data.empty:
            return None
        closes = data["Close"] if len(tickers) > 1 else data[["Close"]].rename(columns={"Close": tickers[0]})
        closes = closes.dropna(axis=1, how="all")
        return closes.pct_change().dropna()
    except Exception:
        return None


def get_risk_report(holdings: dict, prices: dict) -> str:
    held = {t: d for t, d in holdings.items() if (d.get("shares") or 0) > 0}
    if not held:
        return "No held positions found."

    # ── 1. Concentration by category ─────────────────────────────────────────
    total_value = 0.0
    position_values = {}
    for t, d in held.items():
        p = prices.get(t, {}).get("price") or 0
        val = (d.get("shares") or 0) * p
        position_values[t] = val
        total_value += val

    cat_values = {}
    for cat, members in PORTFOLIO_CATEGORIES.items():
        cat_val = sum(position_values.get(t, 0) for t in members if t in held)
        if cat_val > 0:
            cat_values[cat] = cat_val

    cat_sorted = sorted(cat_values.items(), key=lambda x: -x[1])

    conc_msg = "<b>📊 Concentration by Theme:</b>\n"
    warnings = []
    for cat, val in cat_sorted:
        pct = val / total_value * 100 if total_value else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        flag = " ⚠️" if pct > 25 else ""
        conc_msg += f"• <b>{cat}</b>: {pct:.1f}%{flag}\n"
        if pct > 25:
            warnings.append(f"{cat} is {pct:.1f}% of portfolio — single-theme concentration risk")

    # Top 5 single positions
    top5 = sorted(position_values.items(), key=lambda x: -x[1])[:5]
    conc_msg += "\n<b>Top 5 Single Positions:</b>\n"
    for t, val in top5:
        pct = val / total_value * 100 if total_value else 0
        name = held.get(t, {}).get("name", t)
        flag = " ⚠️" if pct > 10 else ""
        conc_msg += f"• <b>{t}</b> ({name}): {pct:.1f}%{flag}\n"

    # ── 2. Correlation clusters ───────────────────────────────────────────────
    # Only US equities for correlation (yfinance handles these cleanly)
    us_held = [t for t in held if not any(t.endswith(s) for s in [".HK", ".SS", ".SZ", ".TW"])
               and t not in {"BTC", "ETH", "SOL", "MATIC", "POL"}][:20]

    corr_msg = ""
    try:
        returns = _get_returns(us_held)
        if returns is not None and len(returns.columns) > 1:
            corr = returns.corr()
            # Find highly correlated pairs (>0.7, excluding self)
            high_corr = []
            cols = list(corr.columns)
            for i in range(len(cols)):
                for j in range(i + 1, len(cols)):
                    c = corr.iloc[i, j]
                    if c > 0.70:
                        high_corr.append((cols[i], cols[j], c))
            high_corr.sort(key=lambda x: -x[2])

            corr_msg = "\n<b>🔗 Highly Correlated Pairs (>70% — these move together):</b>\n"
            if high_corr:
                for t1, t2, c in high_corr[:8]:
                    corr_msg += f"• <b>{t1}</b> + <b>{t2}</b>: {c:.0%}\n"
                corr_msg += "<i>High correlation = concentrated bet even if they look diversified</i>\n"
            else:
                corr_msg += "• No pairs above 70% correlation — good diversification\n"
    except Exception:
        corr_msg = "\n<i>Correlation data unavailable.</i>\n"

    # ── 3. Risk warnings summary ──────────────────────────────────────────────
    warn_msg = ""
    if warnings:
        warn_msg = "\n<b>⚠️ Risk Flags:</b>\n"
        for w in warnings:
            warn_msg += f"• {w}\n"

    total_str = f"${total_value:,.0f}" if total_value else "N/A"
    header = (
        f"🛡️ <b>Portfolio Risk Check</b>\n"
        f"<i>{datetime.now().strftime('%d %b %Y, %H:%M')} · {len(held)} positions · {total_str}</i>\n\n"
    )

    return header + conc_msg + corr_msg + warn_msg
