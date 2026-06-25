"""
Paper trading tracker for the quant system.
Tracks simulated positions in SQLite, separate from the live Notion portfolio.
"""
import os
import sqlite3
from datetime import datetime

import yfinance as yf

_DB_PATH = "/app/data/research.db" if os.path.exists("/app/data") else "research.db"


def _init_db():
    with sqlite3.connect(_DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS quant_paper_trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT NOT NULL,
                direction   TEXT NOT NULL DEFAULT 'LONG',
                signal      TEXT,
                open_price  REAL,
                open_date   TEXT,
                close_price REAL,
                close_date  TEXT,
                shares      REAL DEFAULT 1,
                status      TEXT DEFAULT 'OPEN',
                note        TEXT
            )
        """)


def open_position(ticker: str, signal: str = "BUY", shares: float = 100, note: str = "") -> str:
    _init_db()
    t = yf.Ticker(ticker)
    price = None
    try:
        info  = t.fast_info
        price = float(info.last_price or 0)
    except Exception:
        pass

    if not price:
        return f"❌ Could not fetch price for {ticker}."

    today = datetime.now().strftime("%Y-%m-%d")
    with sqlite3.connect(_DB_PATH) as con:
        # Close any existing open position for this ticker first
        con.execute(
            "UPDATE quant_paper_trades SET status='REPLACED', close_date=? WHERE ticker=? AND status='OPEN'",
            (today, ticker)
        )
        con.execute(
            "INSERT INTO quant_paper_trades (ticker, signal, open_price, open_date, shares, status, note) "
            "VALUES (?, ?, ?, ?, ?, 'OPEN', ?)",
            (ticker, signal, price, today, shares, note)
        )

    value = price * shares
    return f"📋 Opened paper position: <b>{ticker}</b> {shares:.0f}sh @ ${price:.2f} (${value:,.0f}) · signal {signal}"


def close_position(ticker: str) -> str:
    _init_db()
    t = yf.Ticker(ticker)
    price = None
    try:
        price = float(t.fast_info.last_price or 0)
    except Exception:
        pass

    if not price:
        return f"❌ Could not fetch price for {ticker}."

    today = datetime.now().strftime("%Y-%m-%d")
    with sqlite3.connect(_DB_PATH) as con:
        rows = con.execute(
            "SELECT id, open_price, shares FROM quant_paper_trades WHERE ticker=? AND status='OPEN'",
            (ticker,)
        ).fetchall()
        if not rows:
            return f"❌ No open paper position found for {ticker}."

        row_id, open_price, shares = rows[0]
        pnl     = (price - open_price) * shares
        pnl_pct = ((price - open_price) / open_price) * 100 if open_price else 0

        con.execute(
            "UPDATE quant_paper_trades SET status='CLOSED', close_price=?, close_date=? WHERE id=?",
            (price, today, row_id)
        )

    icon = "🟢" if pnl >= 0 else "🔴"
    return (
        f"{icon} Closed paper position: <b>{ticker}</b>\n"
        f"Entry ${open_price:.2f} → Exit ${price:.2f}\n"
        f"P&L: {pnl_pct:+.1f}% (${pnl:+,.0f})"
    )


def get_paper_portfolio() -> str:
    _init_db()
    with sqlite3.connect(_DB_PATH) as con:
        open_rows = con.execute(
            "SELECT ticker, signal, open_price, open_date, shares FROM quant_paper_trades "
            "WHERE status='OPEN' ORDER BY open_date DESC"
        ).fetchall()
        closed_rows = con.execute(
            "SELECT ticker, open_price, close_price, shares, close_date FROM quant_paper_trades "
            "WHERE status='CLOSED' ORDER BY close_date DESC LIMIT 10"
        ).fetchall()

    if not open_rows and not closed_rows:
        return "📋 No paper trades yet. Use <code>quant open TICKER</code> to start."

    lines = ["📋 <b>Quant Paper Portfolio</b>\n"]

    if open_rows:
        lines.append("<b>Open positions</b>")
        total_pnl = 0.0
        for ticker, signal, open_price, open_date, shares in open_rows:
            try:
                curr = float(yf.Ticker(ticker).fast_info.last_price or open_price)
            except Exception:
                curr = open_price
            pnl     = (curr - open_price) * shares
            pnl_pct = ((curr - open_price) / open_price * 100) if open_price else 0
            icon    = "🟢" if pnl >= 0 else "🔴"
            total_pnl += pnl
            lines.append(
                f"{icon} <b>{ticker}</b>  {shares:.0f}sh  entry ${open_price:.2f} → ${curr:.2f}  "
                f"<b>{pnl_pct:+.1f}%</b> (${pnl:+,.0f})  [{signal}]"
            )
        t_icon = "🟢" if total_pnl >= 0 else "🔴"
        lines.append(f"\n{t_icon} <b>Total unrealised: ${total_pnl:+,.0f}</b>")

    if closed_rows:
        lines.append("\n<b>Recent closed</b>")
        for ticker, open_price, close_price, shares, close_date in closed_rows:
            if open_price and close_price:
                pnl_pct = (close_price - open_price) / open_price * 100
                pnl     = (close_price - open_price) * shares
                icon    = "🟢" if pnl >= 0 else "🔴"
                lines.append(f"{icon} <b>{ticker}</b>  {pnl_pct:+.1f}% (${pnl:+,.0f})  closed {close_date}")

    return "\n".join(lines)
