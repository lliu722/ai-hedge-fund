"""
Quant factor engine — computes momentum, value, quality, and technical factors
for a universe of tickers and returns a z-scored composite ranking.

Factor weights:
  40% Momentum  — 12-1 month return (avoids reversal noise of last month)
  30% Quality   — ROE + gross margin composite
  30% Value     — inverse forward P/E (lower PE = higher score)

All factors are z-scored cross-sectionally before weighting so no single
factor dominates due to scale differences.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf


# ── Factor fetch ──────────────────────────────────────────────────────────────

def _fetch_one(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        # Momentum: 12-month return minus last month (12-1 momentum)
        hist = t.history(period="13mo", interval="1mo", auto_adjust=True)
        mom_12_1 = None
        if len(hist) >= 13:
            p_12 = float(hist["Close"].iloc[0])
            p_1  = float(hist["Close"].iloc[-2])   # 1 month ago
            p_now = float(hist["Close"].iloc[-1])
            if p_12 > 0:
                mom_12_1 = (p_1 - p_12) / p_12     # 12-1 return (excluding last month)
            rsi_val = _compute_rsi(hist["Close"].dropna().tolist())
        else:
            rsi_val = None

        # Value: forward P/E (inverted so low PE = high score)
        fpe = info.get("forwardPE") or info.get("trailingPE")
        inv_pe = (1.0 / fpe) if fpe and fpe > 0 and fpe < 500 else None

        # Quality: ROE + gross margin
        roe         = info.get("returnOnEquity")    # decimal, e.g. 0.35 = 35%
        gross_margin = info.get("grossMargins")      # decimal
        quality = None
        if roe is not None and gross_margin is not None:
            quality = (roe + gross_margin) / 2
        elif roe is not None:
            quality = roe
        elif gross_margin is not None:
            quality = gross_margin

        return {
            "ticker":    ticker,
            "mom_12_1":  mom_12_1,
            "rsi":       rsi_val,
            "inv_pe":    inv_pe,
            "quality":   quality,
            "price":     info.get("currentPrice") or info.get("regularMarketPrice"),
            "name":      info.get("shortName") or ticker,
            "sector":    info.get("sector", ""),
        }
    except Exception as e:
        print(f"[quant factors] {ticker}: {e}")
        return {"ticker": ticker, "mom_12_1": None, "rsi": None, "inv_pe": None, "quality": None}


def _compute_rsi(closes: list, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
    gains  = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ── Scoring ───────────────────────────────────────────────────────────────────

def _zscore_col(series: pd.Series) -> pd.Series:
    """Cross-sectional z-score, NaN-safe."""
    valid = series.dropna()
    if len(valid) < 3:
        return pd.Series(0.0, index=series.index)
    mean = valid.mean()
    std  = valid.std()
    if std == 0:
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std


def score_universe(tickers: list[str], workers: int = 20) -> pd.DataFrame:
    """
    Fetch factor data for all tickers and return a ranked DataFrame.
    Columns: ticker, name, sector, price, mom_12_1, rsi, inv_pe, quality,
             z_mom, z_quality, z_value, composite, signal
    """
    print(f"[quant] Fetching factors for {len(tickers)} tickers...")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(_fetch_one, tickers))

    df = pd.DataFrame(rows)
    df = df.set_index("ticker")

    # Z-score each factor (cross-sectional)
    df["z_mom"]     = _zscore_col(df["mom_12_1"])
    df["z_value"]   = _zscore_col(df["inv_pe"])
    df["z_quality"] = _zscore_col(df["quality"])

    # Composite: 40% momentum, 30% quality, 30% value
    df["composite"] = (
        0.40 * df["z_mom"].fillna(0) +
        0.30 * df["z_quality"].fillna(0) +
        0.30 * df["z_value"].fillna(0)
    )

    # Signal thresholds: top 20% = BUY, bottom 20% = AVOID
    n = len(df)
    top_cut  = df["composite"].quantile(0.80)
    bot_cut  = df["composite"].quantile(0.20)
    df["signal"] = "WATCH"
    df.loc[df["composite"] >= top_cut, "signal"] = "BUY"
    df.loc[df["composite"] <= bot_cut, "signal"] = "AVOID"

    df = df.sort_values("composite", ascending=False)
    df.index.name = "ticker"
    return df.reset_index()
