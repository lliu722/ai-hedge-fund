"""
Portfolio optimizer using PyPortfolioOpt.
Suggests optimal weights + exact share counts for a given ticker list.

Falls back gracefully if PyPortfolioOpt is not installed.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf


def _fetch_prices(tickers: list[str], period: str = "2y") -> pd.DataFrame:
    data = yf.download(tickers, period=period, interval="1d",
                       auto_adjust=True, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        prices = data["Close"]
    else:
        prices = data[["Close"]]
        prices.columns = tickers
    return prices.dropna(axis=1, how="all").dropna()


def run_optimizer(tickers: list[str], total_value: float = 100_000) -> str:
    """
    Max-Sharpe portfolio optimization.
    Returns formatted Telegram string with weights + share counts.
    Requires: pip install PyPortfolioOpt
    """
    try:
        from pypfopt import expected_returns, risk_models, EfficientFrontier, DiscreteAllocation
        from pypfopt.exceptions import OptimizationError
    except ImportError:
        return (
            "⚠️ PyPortfolioOpt not installed.\n"
            "Add <code>PyPortfolioOpt</code> to requirements.txt and redeploy."
        )

    prices = _fetch_prices(tickers)
    if prices.empty or len(prices.columns) < 2:
        return "❌ Not enough price data to optimize."

    valid = list(prices.columns)
    mu = expected_returns.mean_historical_return(prices)
    S  = risk_models.CovarianceShrinkage(prices).ledoit_wolf()

    ef = EfficientFrontier(mu, S)
    ef.add_constraint(lambda w: w <= 0.15)   # max 15% per position
    ef.add_constraint(lambda w: w >= 0.01)   # min 1%

    try:
        ef.max_sharpe()
    except OptimizationError:
        ef = EfficientFrontier(mu, S)
        ef.add_constraint(lambda w: w <= 0.15)
        ef.min_volatility()

    weights = ef.clean_weights()
    perf    = ef.portfolio_performance(verbose=False)

    # Discrete allocation (exact shares)
    latest_prices = prices.iloc[-1]
    da = DiscreteAllocation(weights, latest_prices, total_portfolio_value=total_value)
    allocation, leftover = da.lp_portfolio()

    exp_ret, vol, sharpe = perf
    lines = [
        f"⚖️ <b>Quant Optimizer</b>",
        f"<i>Max-Sharpe · {len(valid)} names · ${total_value:,.0f} portfolio</i>",
        f"<i>Expected return {exp_ret*100:.1f}% · Vol {vol*100:.1f}% · Sharpe {sharpe:.2f}</i>\n",
        "<b>Allocation</b>",
    ]

    for ticker, shares in sorted(allocation.items(), key=lambda x: weights.get(x[0], 0), reverse=True):
        w       = weights.get(ticker, 0) * 100
        price   = float(latest_prices.get(ticker, 0))
        value   = shares * price
        lines.append(f"• <b>{ticker}</b>  {shares}sh  ${value:,.0f}  ({w:.1f}%)")

    lines.append(f"\n<i>Cash leftover: ${leftover:,.0f}</i>")
    return "\n".join(lines)
