"""
FICC Data Layer — Powered by FRED API (Federal Reserve Bank of St. Louis)
Free API key at: https://fred.stlouisfed.org/docs/api/api_key.html
Set FRED_API_KEY in .env and Railway dashboard.

Covers: yield curve, credit spreads, Fed Funds, key FX pairs.
"""
import os
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# ── FRED Series IDs ───────────────────────────────────────────────────────────
YIELD_CURVE = {
    "DGS2":   "2Y Treasury",
    "DGS5":   "5Y Treasury",
    "DGS10":  "10Y Treasury",
    "DGS30":  "30Y Treasury",
    "T10Y2Y": "10Y-2Y Spread",
}

CREDIT = {
    "BAMLC0A0CM":   "IG Credit Spread",
    "BAMLH0A0HYM2": "HY Credit Spread",
}

RATES = {
    "FEDFUNDS": "Fed Funds Rate",
    "SOFR":     "SOFR",
}

FX = {
    "DEXCHUS": "USD/CNY",
    "DEXJPUS": "USD/JPY",
    "DEXUSUK": "GBP/USD",
    "DEXUSEU": "EUR/USD",
}


def _fetch_one(series_id: str, days_back: int = 7) -> tuple:
    """Fetch the most recent value for a FRED series. Returns (series_id, value)."""
    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        return series_id, None

    observation_start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    try:
        r = requests.get(
            FRED_BASE,
            params={
                "series_id": series_id,
                "api_key": api_key,
                "observation_start": observation_start,
                "sort_order": "desc",
                "limit": 2,
                "file_type": "json",
            },
            timeout=10,
        )
        if r.status_code == 200:
            obs = [o for o in r.json().get("observations", []) if o.get("value") != "."]
            if obs:
                return series_id, float(obs[0]["value"])
    except Exception:
        pass
    return series_id, None


def get_ficc_snapshot() -> dict:
    """
    Fetch full FICC snapshot in parallel.
    Returns {series_id: value} for all series.
    """
    all_series = list(YIELD_CURVE) + list(CREDIT) + list(RATES) + list(FX)
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = dict(ex.map(_fetch_one, all_series))
    return results


def format_ficc_brief(data: dict) -> str:
    """Format FICC snapshot as Telegram-ready message."""
    if not os.getenv("FRED_API_KEY"):
        return "⚠️ <b>FICC:</b> FRED_API_KEY not set — get free key at fred.stlouisfed.org"

    lines = ["📊 <b>FICC Snapshot</b>\n"]

    # Yield curve
    lines.append("<b>Yield Curve (US Treasuries):</b>")
    for sid, label in YIELD_CURVE.items():
        val = data.get(sid)
        if val is not None:
            arrow = "▲" if sid == "T10Y2Y" and val > 0 else ("▼" if sid == "T10Y2Y" and val < 0 else "")
            lines.append(f"• {label}: <b>{val:.2f}%</b> {arrow}")

    # Credit spreads
    lines.append("\n<b>Credit Spreads (OAS):</b>")
    for sid, label in CREDIT.items():
        val = data.get(sid)
        if val is not None:
            lines.append(f"• {label}: <b>{val:.2f}%</b>")

    # Rates
    lines.append("\n<b>Policy Rates:</b>")
    for sid, label in RATES.items():
        val = data.get(sid)
        if val is not None:
            lines.append(f"• {label}: <b>{val:.2f}%</b>")

    # FX
    lines.append("\n<b>FX:</b>")
    for sid, label in FX.items():
        val = data.get(sid)
        if val is not None:
            lines.append(f"• {label}: <b>{val:.4f}</b>")

    lines.append(f"\n<i>Source: FRED · {datetime.now().strftime('%d %b %Y')}</i>")
    return "\n".join(lines)


def get_macro_regime() -> str:
    """
    Derive a macro regime label from live FICC data.
    Regime: RISK-ON / RISK-OFF / EASING CYCLE / STAGFLATION / LATE CYCLE
    Logic:
      Yield curve (T10Y2Y): >0.5 = steepening/expansion, <0 = inverted/recession risk
      HY credit spread: <350bp = tight/risk-on, >550bp = stressed/risk-off
      Fed Funds: context for easing vs tightening cycle
    """
    data = get_ficc_snapshot()

    curve    = data.get("T10Y2Y")        # 10Y-2Y spread, %
    hy_oas   = data.get("BAMLH0A0HYM2")  # HY OAS, %
    ig_oas   = data.get("BAMLC0A0CM")    # IG OAS, %
    fed      = data.get("FEDFUNDS")       # Fed Funds, %
    y10      = data.get("DGS10")
    y2       = data.get("DGS2")

    signals = []
    regime_scores = {"RISK-ON": 0, "RISK-OFF": 0, "EASING": 0, "STAGFLATION": 0, "LATE CYCLE": 0}

    # Yield curve signal
    if curve is not None:
        if curve > 0.5:
            signals.append(f"Yield curve <b>+{curve:.2f}%</b> — steepening, expansion signal")
            regime_scores["RISK-ON"] += 2
        elif curve > 0:
            signals.append(f"Yield curve <b>+{curve:.2f}%</b> — flat, late-cycle")
            regime_scores["LATE CYCLE"] += 2
        elif curve > -0.3:
            signals.append(f"Yield curve <b>{curve:.2f}%</b> — mildly inverted, slowdown risk")
            regime_scores["LATE CYCLE"] += 1
            regime_scores["RISK-OFF"] += 1
        else:
            signals.append(f"Yield curve <b>{curve:.2f}%</b> — deeply inverted, recession signal 🚨")
            regime_scores["RISK-OFF"] += 3

    # Credit spread signal
    if hy_oas is not None:
        hy_bp = hy_oas * 100
        if hy_bp < 350:
            signals.append(f"HY spreads <b>{hy_bp:.0f}bp</b> — tight, credit benign, risk-on")
            regime_scores["RISK-ON"] += 2
        elif hy_bp < 550:
            signals.append(f"HY spreads <b>{hy_bp:.0f}bp</b> — neutral, no stress")
            regime_scores["RISK-ON"] += 1
        elif hy_bp < 800:
            signals.append(f"HY spreads <b>{hy_bp:.0f}bp</b> — elevated, credit stress building ⚠️")
            regime_scores["RISK-OFF"] += 2
        else:
            signals.append(f"HY spreads <b>{hy_bp:.0f}bp</b> — wide, crisis-level credit stress 🚨")
            regime_scores["RISK-OFF"] += 4

    # Fed signal
    if fed is not None:
        if fed > 4.5:
            signals.append(f"Fed Funds <b>{fed:.2f}%</b> — restrictive, tightening cycle")
            regime_scores["LATE CYCLE"] += 1
            regime_scores["STAGFLATION"] += 1
        elif fed > 2.5:
            signals.append(f"Fed Funds <b>{fed:.2f}%</b> — neutral to tight")
        else:
            signals.append(f"Fed Funds <b>{fed:.2f}%</b> — accommodative, easing cycle")
            regime_scores["EASING"] += 2
            regime_scores["RISK-ON"] += 1

    # Determine regime
    regime = max(regime_scores, key=lambda k: regime_scores[k])
    regime_emoji = {
        "RISK-ON": "🟢", "RISK-OFF": "🔴", "EASING": "🔵",
        "STAGFLATION": "🟡", "LATE CYCLE": "🟠"
    }.get(regime, "⚪")

    regime_desc = {
        "RISK-ON":    "Credit tight + steepening curve — favour growth, cyclicals, and risk assets",
        "RISK-OFF":   "Credit stress + curve signals — reduce risk, favour quality, watch AI valuations",
        "EASING":     "Fed cutting + loose financial conditions — duration and growth stocks benefit",
        "STAGFLATION":"High rates + credit pressure + flat curve — hardest environment; energy and real assets outperform",
        "LATE CYCLE": "Flat/inverted curve + restrictive rates — rotation to quality, reduce concentration risk",
    }.get(regime, "")

    msg = f"🌐 <b>Macro Regime: {regime_emoji} {regime}</b>\n"
    msg += f"<i>{datetime.now().strftime('%d %b %Y')}</i>\n\n"
    msg += f"<i>{regime_desc}</i>\n\n"
    msg += "<b>Signals:</b>\n"
    for s in signals:
        msg += f"• {s}\n"
    msg += f"\n<i>Source: FRED · T10Y2Y={curve:.2f}% · HY OAS={(hy_oas*100 if hy_oas else 0):.0f}bp · Fed={fed:.2f}%</i>"
    return msg


def get_ficc_message() -> str:
    """Single call: fetch + format. Use in bot tools and scheduler."""
    data = get_ficc_snapshot()
    return format_ficc_brief(data)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    print(get_ficc_message())
