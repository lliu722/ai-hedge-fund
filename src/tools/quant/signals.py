"""
Signal generation and Telegram formatting for the quant screen.
Wraps factors.score_universe() and formats output for the bot.
"""
import pandas as pd

from src.tools.quant.factors import score_universe


SIGNAL_ICON = {"BUY": "🟢", "WATCH": "🟡", "AVOID": "🔴"}


def run_quant_screen(tickers: list[str], top_n: int = 10) -> str:
    """
    Run factor screen on universe, return formatted Telegram message.
    Shows top_n names by composite score.
    """
    if not tickers:
        return "❌ No tickers provided."

    df = score_universe(tickers)
    if df.empty:
        return "❌ Could not fetch factor data."

    buys   = df[df["signal"] == "BUY"]
    avoids = df[df["signal"] == "AVOID"]
    total  = len(df)

    lines = [
        f"📐 <b>Quant Factor Screen</b>",
        f"<i>{total} names · momentum 40% · quality 30% · value 30%</i>\n",
    ]

    # Top names
    lines.append("<b>Top ranked</b>")
    for _, row in df.head(top_n).iterrows():
        icon   = SIGNAL_ICON.get(row["signal"], "⚪")
        ticker = row["ticker"]
        score  = row["composite"]
        mom    = row["mom_12_1"]
        mom_str = f"{mom*100:+.0f}%m" if pd.notna(mom) else "—"
        rsi    = row["rsi"]
        rsi_str = f"RSI {rsi:.0f}" if pd.notna(rsi) else ""
        name   = (row.get("name") or ticker)[:20]
        lines.append(f"{icon} <b>{ticker}</b> <i>{name}</i>  score {score:+.2f}  {mom_str}  {rsi_str}")

    # Bottom names (avoid)
    if not avoids.empty:
        lines.append("\n<b>Bottom ranked (avoid)</b>")
        for _, row in df.tail(5).iterrows():
            icon   = SIGNAL_ICON.get(row["signal"], "⚪")
            ticker = row["ticker"]
            score  = row["composite"]
            lines.append(f"{icon} <b>{ticker}</b>  score {score:+.2f}")

    lines.append(f"\n<i>🟢 {len(buys)} buy · 🟡 {total - len(buys) - len(avoids)} watch · 🔴 {len(avoids)} avoid</i>")
    return "\n".join(lines)


def run_single_signal(ticker: str, tickers_universe: list[str]) -> str:
    """
    Factor breakdown for a single ticker, ranked within its universe.
    """
    if ticker not in tickers_universe:
        tickers_universe = [ticker] + tickers_universe

    df = score_universe(tickers_universe)
    if df.empty:
        return f"❌ Could not score {ticker}."

    row = df[df["ticker"] == ticker]
    if row.empty:
        return f"❌ {ticker} not found in results."

    row  = row.iloc[0]
    rank = df[df["ticker"] == ticker].index[0] + 1
    total = len(df)
    icon  = SIGNAL_ICON.get(row["signal"], "⚪")

    mom    = row["mom_12_1"]
    inv_pe = row["inv_pe"]
    qual   = row["quality"]
    rsi    = row["rsi"]

    lines = [
        f"📐 <b>Quant Signal: {ticker}</b>",
        f"{icon} <b>{row['signal']}</b>  composite score {row['composite']:+.2f}  |  rank #{rank} of {total}\n",
        "<b>Factor breakdown</b>",
        f"• Momentum (12-1m):  {f'{mom*100:+.1f}%' if pd.notna(mom) else 'N/A'}  →  z {row['z_mom']:+.2f}",
        f"• Value (1/fwd PE):  {f'{1/inv_pe:.1f}x PE' if pd.notna(inv_pe) and inv_pe > 0 else 'N/A'}  →  z {row['z_value']:+.2f}",
        f"• Quality (ROE+margin): {f'{qual*100:.0f}%' if pd.notna(qual) else 'N/A'}  →  z {row['z_quality']:+.2f}",
        f"• RSI (14):  {f'{rsi:.1f}' if pd.notna(rsi) else 'N/A'}",
        f"\n<i>Weights: 40% momentum · 30% quality · 30% value</i>",
        f"<i>Signal cutoffs: top 20% = BUY · bottom 20% = AVOID</i>",
    ]
    return "\n".join(lines)
