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


def get_ficc_message() -> str:
    """Single call: fetch + format. Use in bot tools and scheduler."""
    data = get_ficc_snapshot()
    return format_ficc_brief(data)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    print(get_ficc_message())
