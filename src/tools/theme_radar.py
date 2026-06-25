"""
Theme Radar — weekly scan of ~55 sector + thematic ETFs.
Detects emerging investment themes before consensus using ETF Z-score momentum.

Method:
  1. Pull 52 weeks of weekly returns for every ETF in the universe via yfinance
  2. Compute Z-score: (this_week_return - 52w_mean) / 52w_stdev
  3. Compute correlation of each ETF vs portfolio average weekly returns
  4. Flag: Z > threshold AND correlation < threshold (moving independently)
  5. For each flag: Tavily news narrative + DeepSeek synthesis

Works for ALL sectors — biotech, consumer, energy, EM, etc. — not just tech.
GitHub/arXiv signals in momentum.py are tech-specific enhancements added separately.
"""
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import yfinance as yf

from src.tools.llm import call_deepseek, tavily_search, clean_news, fmt_snippet


# ── ETF Universe ──────────────────────────────────────────────────────────────
# All GICS sectors + thematic ETFs. Z-score finds what's moving — no pre-selection.

ETF_UNIVERSE = {
    # GICS Core Sectors (11)
    "XLK":  "Technology",
    "XLF":  "Financials",
    "XLE":  "Energy",
    "XLV":  "Healthcare",
    "XLI":  "Industrials",
    "XLY":  "Consumer Discretionary",
    "XLP":  "Consumer Staples",
    "XLU":  "Utilities",
    "XLC":  "Communication Services",
    "XLB":  "Materials",
    "XLRE": "Real Estate",

    # Semiconductors & Tech Sub-sectors
    "SOXX": "Semiconductors",
    "SMH":  "Semiconductors (VanEck)",
    "IGV":  "Software",
    "CLOU": "Cloud Computing",
    "CIBR": "Cybersecurity",
    "HACK": "Cybersecurity (ETFMG)",
    "FINX": "Fintech",

    # Biotech & Healthcare Sub-sectors
    "IBB":  "Biotech",
    "XBI":  "Biotech Small-Cap",
    "ARKG": "Genomics",
    "IDNA": "DNA & Genomics",
    "IHI":  "Medical Devices",

    # Clean Energy & Power
    "ICLN": "Clean Energy",
    "TAN":  "Solar",
    "FAN":  "Wind Energy",
    "NLR":  "Nuclear Energy",
    "NUKZ": "Nuclear (Range)",
    "ACES": "Clean Energy (ALPS)",

    # Robotics, Automation & AI
    "BOTZ": "Robotics & Automation",
    "ROBO": "Robotics (ROBO Global)",
    "IRBO": "Robotics & AI",

    # Defence & Aerospace
    "ITA":  "Aerospace & Defence",
    "PPA":  "Defence (Invesco)",
    "XAR":  "Aerospace (SPDR)",

    # Space
    "UFO":  "Space Exploration",

    # Commodities & Materials
    "REMX": "Rare Earth & Materials",
    "GDX":  "Gold Miners",
    "COPX": "Copper Miners",
    "MOO":  "Agriculture",
    "PHO":  "Water",
    "DBA":  "Agriculture (Invesco)",

    # Transport & Autonomous Vehicles
    "DRIV": "Autonomous & Electric Vehicles",
    "KARS": "Electric Vehicles",

    # Consumer Sub-sectors
    "XRT":  "Retail",
    "XHB":  "Homebuilders",
    "ITB":  "Home Construction",

    # Emerging Markets & International
    "KWEB": "China Internet",
    "CQQQ": "China Tech",
    "FXI":  "China Large Cap",
    "INDA": "India",
    "EEM":  "Emerging Markets",
    "EWJ":  "Japan",
    "EWZ":  "Brazil",
    "VWO":  "Emerging Markets (Vanguard)",

    # Digital Assets & Blockchain
    "BKCH": "Blockchain & Crypto",

    # Real Assets & Infrastructure
    "WOOD": "Timber & Forestry",
    "AMLP": "Energy Infrastructure (MLP)",
    "SRVR": "Data Centre REITs",

    # Frontier / Emerging Themes
    "PRNT": "3D Printing",
    "MSOS": "Cannabis",
    "UFO":  "Space Exploration",
}


def _get_weekly_returns(ticker: str, weeks: int = 52) -> list[float]:
    """Fetch weekly closing returns for a ticker over the past N weeks."""
    try:
        data = yf.download(
            ticker, period=f"{weeks + 6}wk", interval="1wk",
            progress=False, auto_adjust=True
        )
        if data.empty or len(data) < 8:
            return []
        closes = data["Close"].dropna()
        returns = closes.pct_change().dropna().tolist()
        if isinstance(returns[0], (list, np.ndarray)):
            returns = [float(r[0]) for r in returns]
        else:
            returns = [float(r) for r in returns]
        return returns[-weeks:] if len(returns) >= weeks else returns
    except Exception:
        return []


def _zscore(recent: float, historical: list[float]) -> float:
    if len(historical) < 8:
        return 0.0
    mean = float(np.mean(historical))
    std  = float(np.std(historical))
    return 0.0 if std == 0 else (recent - mean) / std


def _correlation(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 8:
        return 1.0
    arr_a = np.array(a[-n:])
    arr_b = np.array(b[-n:])
    if np.std(arr_a) == 0 or np.std(arr_b) == 0:
        return 0.0
    return float(np.corrcoef(arr_a, arr_b)[0, 1])


def run_theme_radar(
    held_tickers: list[str],
    z_threshold: float = 1.5,
    corr_threshold: float = 0.4,
    max_flags: int = 5,
) -> str:
    """
    Scan ETF universe for emerging themes with momentum outside the current portfolio.
    Returns a formatted Telegram string, or "" if nothing fires.
    """
    print(f"[{datetime.now().strftime('%H:%M')}] Theme radar: fetching portfolio returns...")

    # Portfolio weekly returns — average across held positions
    def _fetch(ticker):
        return ticker, _get_weekly_returns(ticker, weeks=52)

    with ThreadPoolExecutor(max_workers=12) as ex:
        port_data = dict(ex.map(lambda t: _fetch(t), held_tickers[:25]))

    valid_port = {t: r for t, r in port_data.items() if len(r) >= 8}
    if valid_port:
        min_len  = min(len(r) for r in valid_port.values())
        port_avg = list(np.mean([r[-min_len:] for r in valid_port.values()], axis=0))
    else:
        port_avg = []

    print(f"[{datetime.now().strftime('%H:%M')}] Theme radar: scanning {len(ETF_UNIVERSE)} ETFs...")

    with ThreadPoolExecutor(max_workers=15) as ex:
        etf_data = dict(ex.map(lambda t: _fetch(t), ETF_UNIVERSE.keys()))

    # Score each ETF
    candidates = []
    for ticker, returns in etf_data.items():
        if len(returns) < 8:
            continue
        recent     = returns[-1]
        historical = returns[:-1]
        z    = _zscore(recent, historical)
        corr = _correlation(returns, port_avg) if port_avg else 0.5
        if z >= z_threshold and corr < corr_threshold:
            candidates.append((ticker, ETF_UNIVERSE[ticker], recent, z, corr))

    candidates.sort(key=lambda x: x[3], reverse=True)

    if not candidates:
        return ""

    print(f"[{datetime.now().strftime('%H:%M')}] Theme radar: {len(candidates)} flags — fetching narratives...")

    sections = []
    for ticker, label, recent_ret, z, corr in candidates[:max_flags]:
        try:
            news = clean_news(tavily_search(
                f"{label} sector ETF {ticker} investing theme trend 2026",
                max_results=5, search_depth="basic",
            ))
            news_text = ""
            for a in news[:3]:
                news_text += f"- {a.get('title', '')}\n"
                snip = fmt_snippet(a.get("content", ""), 130)
                if snip:
                    news_text += f"  {snip}\n"

            prompt = (
                f"The {label} ETF ({ticker}) returned {recent_ret * 100:.1f}% this week — "
                f"a Z-score of {z:.1f} vs its 52-week history. "
                f"It is moving independently of a portfolio concentrated in AI, memory, energy, and space.\n\n"
                f"RECENT NEWS:\n{news_text or 'No specific news found.'}\n\n"
                f"In 2-3 sentences: why is this theme moving now, is there substance behind it, "
                f"and name 1-2 specific stocks within this theme worth investigating. "
                f"Be direct and specific. Use <b>bold</b> for stock tickers."
            )
            narrative = call_deepseek(prompt, max_tokens=160, temperature=0.3, timeout=25)
            if narrative and not narrative.startswith("❌"):
                sections.append(
                    f"⚡ <b>{label}</b> ({ticker})\n"
                    f"<i>Z-score {z:.1f} · {recent_ret * 100:+.1f}% this week · low portfolio overlap</i>\n"
                    f"{narrative}"
                )
        except Exception as e:
            print(f"Theme radar narrative error ({ticker}): {e}")

    if not sections:
        return ""

    return (
        f"🔭 <b>Theme Radar</b>\n"
        f"<i>Sectors moving outside your portfolio this week</i>\n\n"
        + "\n\n".join(sections)
    )
