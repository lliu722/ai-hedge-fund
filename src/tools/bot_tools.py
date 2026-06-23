"""
bot_tools.py — All @tool functions for the LangGraph agent.
Add new tools here. Register them in telegram_bot.py tools list.
"""
from datetime import datetime
from langchain_core.tools import tool
from src.tools.bot_helpers import fmt, WATCHLIST, WATCHLIST_TICKERS, PORTFOLIO, WATCHLIST_ONLY


@tool
def deep_dive(ticker: str) -> str:
    """
    Run a full AI research deep dive on a stock ticker.
    Returns bull case, bear case, catalysts, valuation, and a buy/sell verdict.
    Use when the user asks for analysis, research, a deep dive, or wants to understand a company.
    """
    from src.tools.deep_dive import deep_dive as _dd
    return _dd(ticker.upper())


@tool
def get_price(ticker: str) -> str:
    """
    Get the live price and key market data for a stock ticker.
    Use when the user asks for a price, stock quote, or market data for a specific company.
    """
    from src.tools.prices import get_live_prices
    data = get_live_prices([ticker.upper()], detailed=True).get(ticker.upper(), {})
    if not data:
        return f"Could not fetch price for {fmt(ticker)}."
    direction = "📈" if (data.get("change_pct") or 0) > 0 else "📉"
    return (
        f"{direction} <b>{fmt(ticker)}</b>\n"
        f"Price: <b>${data.get('price')}</b>\n"
        f"Today: <b>{data.get('change_pct'):+.2f}%</b>\n"
        f"52w High: ${data.get('week52_high')}\n"
        f"52w Low: ${data.get('week52_low')}\n"
        f"P/E: {data.get('pe_ratio')}"
    )


@tool
def get_news(ticker: str = None) -> str:
    """
    Get the latest news for a specific stock ticker or general macro news.
    Use when the user asks about news, what happened, or latest developments.
    If no ticker is specified, return macro news.
    """
    from src.tools.news_fetcher import get_news_for_tickers, get_macro_news
    if ticker:
        t        = ticker.upper()
        articles = get_news_for_tickers([t]).get(t, [])
        if articles:
            msg = f"🗞 <b>Latest news: {fmt(t)}</b>\n\n"
            for a in articles[:5]:
                msg += f"• <b>{a['title']}</b>\n"
                if a.get("content"):
                    msg += f"  <i>{a['content'][:150].strip()}...</i>\n\n"
            return msg
        return f"No recent results for {fmt(t)}. Summarise from training knowledge instead."
    articles = get_macro_news()
    msg = "🌍 <b>Market & Macro News</b>\n\n"
    for a in articles[:5]:
        msg += f"• <b>{a['title']}</b>\n"
        if a.get("content"):
            msg += f"  <i>{a['content'][:150].strip()}...</i>\n\n"
    return msg


@tool
def get_earnings_calendar() -> str:
    """
    Get upcoming earnings dates for all watchlist stocks.
    Use when the user asks about earnings, when companies report, or upcoming events.
    """
    from src.tools.earnings_calendar import get_earnings_dates
    dates    = get_earnings_dates(WATCHLIST_TICKERS)
    msg      = "📅 <b>Earnings Calendar</b>\n\n"
    upcoming = [(t, d) for t, d in dates.items()
                if d.get("days_until") is not None and d.get("days_until") >= 0]
    upcoming.sort(key=lambda x: x[1]["days_until"])
    if upcoming:
        for ticker, data in upcoming:
            alert = " ⚠️ SOON" if data["alert"] else ""
            msg  += f"• <b>{fmt(ticker)}</b>: {data['date']} ({data['days_until']} days){alert}\n"
    else:
        msg += "No upcoming earnings found in next 60 days."
    return msg


@tool
def get_portfolio() -> str:
    """
    Show actual held positions with live prices and P&L vs average cost.
    Use when the user asks about their portfolio, actual holdings, or positions with real money invested.
    """
    from src.tools.prices import get_live_prices
    prices      = get_live_prices(list(PORTFOLIO.keys()))
    msg         = f"💼 <b>Portfolio — {len(PORTFOLIO)} Held Positions</b>\n"
    msg        += f"<i>{datetime.now().strftime('%d %b %Y, %H:%M')}</i>\n\n"
    total_value = 0
    for t, d in prices.items():
        if not d: continue
        shares    = PORTFOLIO.get(t, {}).get("shares", 0)
        avg_cost  = PORTFOLIO.get(t, {}).get("avg_cost", 0)
        price     = d.get("price") or 0
        value     = shares * price
        total_value += value
        pnl       = ((price - avg_cost) / avg_cost * 100) if avg_cost else 0
        direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
        msg      += f"{direction} <b>{fmt(t)}</b>: ${price} ({d.get('change_pct'):+.2f}%) • P&L: {pnl:+.1f}%\n"
    if total_value > 0:
        msg += f"\n<i>Total market value: ${total_value:,.0f}</i>"
    return msg


@tool
def get_watchlist() -> str:
    """
    Show watchlist monitoring names — stocks being watched but not yet held.
    Use when the user asks about their watchlist, names they are monitoring, or stocks they are watching but haven't bought.
    """
    from src.tools.prices import get_live_prices
    prices = get_live_prices(list(WATCHLIST_ONLY.keys()))
    msg    = f"👁 <b>Watchlist — {len(WATCHLIST_ONLY)} Monitoring</b>\n"
    msg   += f"<i>{datetime.now().strftime('%d %b %Y, %H:%M')}</i>\n\n"
    for t, d in prices.items():
        if not d: continue
        rating    = WATCHLIST_ONLY.get(t, {}).get("rating", "")
        direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
        rtag      = f" <i>[{rating}]</i>" if rating else ""
        msg      += f"{direction} <b>{fmt(t)}</b>: ${d.get('price')} ({d.get('change_pct'):+.2f}%){rtag}\n"
    return msg


@tool
def get_market_briefing() -> str:
    """
    Get a market briefing with top moves and macro news.
    Use when the user asks about the market, morning briefing, how things are today, or what happened overnight.
    """
    from src.tools.news_fetcher import get_macro_news
    from src.tools.prices import get_live_prices
    prices = get_live_prices(list(PORTFOLIO.keys())[:8])
    macro  = get_macro_news()
    msg    = f"🌅 <b>Market Briefing — {datetime.now().strftime('%d %B %Y')}</b>\n\n"
    msg   += "<b>Top Portfolio Moves:</b>\n"
    for t, d in prices.items():
        if not d: continue
        direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
        msg      += f"{direction} <b>{fmt(t)}</b>: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"
    msg += "\n<b>Macro & Market News:</b>\n"
    for a in macro[:3]:
        msg += f"• <b>{a['title']}</b>\n"
        if a.get("content"):
            msg += f"  <i>{a['content'][:150].strip()}...</i>\n\n"
    return msg


@tool
def get_sec_filings(ticker: str) -> str:
    """
    Get recent SEC filings (10-K annual, 10-Q quarterly, 8-K earnings) for a company.
    Use when the user asks about filings, annual reports, earnings documents, or regulatory filings.
    """
    from src.tools.sec_filings import get_filing_summary
    summary = get_filing_summary(ticker.upper())
    msg     = f"📄 <b>SEC Filings: {fmt(ticker)}</b>\n\n"
    msg    += f"• Latest 10-K: {summary['10-K'][0]['date'] if summary['10-K'] else 'N/A'}\n"
    msg    += f"• Recent 10-Qs: {', '.join([f['date'] for f in summary['10-Q']]) or 'N/A'}\n"
    msg    += f"• Recent 8-Ks: {', '.join([f['date'] for f in summary['8-K']]) or 'N/A'}\n"
    return msg


@tool
def get_ficc_data() -> str:
    """
    Get live FICC data: US yield curve, credit spreads, policy rates, and key FX pairs.
    Use when the user asks about interest rates, bonds, the yield curve, credit spreads,
    the dollar, FX rates, or macro financial conditions.
    """
    from src.tools.ficc import get_ficc_message
    return get_ficc_message()
