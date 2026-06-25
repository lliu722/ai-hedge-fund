"""
Momentum backtest engine — no external backtesting libs required.

Strategy: classic 12-1 cross-sectional momentum
  - Each month, rank universe by 12-1m return
  - Go long top quintile (equal-weight), hold 1 month
  - Benchmark: SPY buy-and-hold

Outputs: hit rate, avg monthly return, annualised Sharpe, max drawdown,
         win months vs SPY, formatted Telegram message.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf


# ── Price fetch ───────────────────────────────────────────────────────────────

def _fetch_monthly_prices(tickers: list[str], years: int = 3) -> pd.DataFrame:
    """Monthly adjusted close prices for the universe + SPY."""
    all_tickers = list(dict.fromkeys(tickers + ["SPY"]))
    data = yf.download(
        all_tickers, period=f"{years * 12 + 2}mo", interval="1mo",
        auto_adjust=True, progress=False, threads=True,
    )
    if isinstance(data.columns, pd.MultiIndex):
        prices = data["Close"]
    else:
        prices = data[["Close"]]
        prices.columns = all_tickers

    prices = prices.dropna(axis=1, thresh=int(len(prices) * 0.7))  # drop sparse cols
    return prices.ffill()


# ── Signal ────────────────────────────────────────────────────────────────────

def _momentum_signal(prices: pd.DataFrame, t: int, lookback: int = 12, skip: int = 1) -> pd.Series:
    """12-1 momentum at time index t: return from t-12 to t-1."""
    if t < lookback + skip:
        return pd.Series(dtype=float)
    window = prices.iloc[t - lookback - skip: t - skip]
    if len(window) < lookback:
        return pd.Series(dtype=float)
    ret = (window.iloc[-1] / window.iloc[0]) - 1
    return ret.dropna()


# ── Backtest loop ─────────────────────────────────────────────────────────────

def run_backtest(
    tickers: list[str],
    years: int = 2,
    quintile: float = 0.20,
) -> str:
    """
    Walk-forward monthly momentum backtest.
    Returns formatted Telegram message.
    """
    print(f"[backtest] Fetching {len(tickers)} tickers × {years}y monthly prices...")
    prices = _fetch_monthly_prices(tickers, years=years)

    if prices.empty or len(prices) < 15:
        return "❌ Not enough price history to backtest."

    equity_tickers = [c for c in prices.columns if c != "SPY"]
    spy_prices      = prices["SPY"] if "SPY" in prices.columns else None

    strategy_returns: list[float] = []
    spy_returns:      list[float] = []
    dates:            list[str]   = []
    win_months = 0

    for t in range(14, len(prices)):
        signal = _momentum_signal(prices[equity_tickers], t)
        if signal.empty:
            continue

        n_long = max(1, int(len(signal) * quintile))
        longs  = signal.nlargest(n_long).index.tolist()

        # Forward 1-month return
        fwd_ret = ((prices[longs].iloc[t] / prices[longs].iloc[t - 1]) - 1).mean()
        strategy_returns.append(float(fwd_ret))
        dates.append(str(prices.index[t])[:7])

        if spy_prices is not None and t < len(spy_prices):
            spy_ret = float((spy_prices.iloc[t] / spy_prices.iloc[t - 1]) - 1)
            spy_returns.append(spy_ret)
            if fwd_ret > spy_ret:
                win_months += 1

    if not strategy_returns:
        return "❌ Backtest produced no results — universe may be too small."

    # ── Stats ──────────────────────────────────────────────────────────────────
    r = np.array(strategy_returns)
    s = np.array(spy_returns) if spy_returns else None

    avg_monthly  = float(np.mean(r))
    ann_return   = float((1 + avg_monthly) ** 12 - 1)
    ann_vol      = float(np.std(r) * np.sqrt(12))
    sharpe       = (ann_return / ann_vol) if ann_vol > 0 else 0.0
    hit_rate     = float(np.mean(r > 0))
    n_months     = len(r)

    # Max drawdown
    cum = np.cumprod(1 + r)
    peak = np.maximum.accumulate(cum)
    dd   = (cum - peak) / peak
    max_dd = float(np.min(dd))

    # SPY comparison
    spy_ann = 0.0
    beat_pct = 0.0
    if s is not None and len(s) > 0:
        spy_ann  = float((1 + np.mean(s)) ** 12 - 1)
        beat_pct = win_months / n_months

    # Best / worst months
    best_idx  = int(np.argmax(r))
    worst_idx = int(np.argmin(r))

    lines = [
        f"📈 <b>Quant Backtest — 12-1 Momentum</b>",
        f"<i>{len(tickers)} names · top {int(quintile*100)}% long · {n_months}m walk-forward · {years}y history</i>\n",

        "<b>Performance</b>",
        f"• Ann. return:    {ann_return*100:+.1f}%  (SPY {spy_ann*100:+.1f}%)" if spy_ann else f"• Ann. return: {ann_return*100:+.1f}%",
        f"• Ann. volatility: {ann_vol*100:.1f}%",
        f"• Sharpe ratio:   {sharpe:.2f}",
        f"• Max drawdown:   {max_dd*100:.1f}%",
        f"• Hit rate:       {hit_rate*100:.0f}% of months positive",
        f"• Beat SPY:       {beat_pct*100:.0f}% of months" if spy_returns else "",

        f"\n<b>Best month</b>  {dates[best_idx]}  {r[best_idx]*100:+.1f}%",
        f"<b>Worst month</b>  {dates[worst_idx]}  {r[worst_idx]*100:+.1f}%",
        f"\n<i>Strategy: buy top {int(quintile*100)}% by 12-1m momentum, equal-weight, hold 1 month.</i>",
        f"<i>Rebalanced monthly. Transaction costs not modelled.</i>",
    ]
    return "\n".join(l for l in lines if l)
