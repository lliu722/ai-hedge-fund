import os
import re
import requests
import threading
from datetime import datetime
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langchain_deepseek import ChatDeepSeek
from src.tools.notion_holdings import get_holdings_from_notion, FALLBACK_WATCHLIST

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def load_watchlist():
    try:
        return get_holdings_from_notion()
    except Exception:
        return FALLBACK_WATCHLIST


WATCHLIST = load_watchlist()
WATCHLIST_TICKERS = list(WATCHLIST.keys())


def fmt(ticker: str) -> str:
    t = ticker.upper()
    name = WATCHLIST.get(t, {}).get("name", "")
    return f"{t} ({name})" if name else t


# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are an AI investment research assistant specialising in AI infrastructure equity.
You have access to tools for live prices, news, SEC filings, earnings calendars, deep dive research reports, and portfolio data.
The user's portfolio focuses on: {", ".join(fmt(t) for t in WATCHLIST_TICKERS)}.
Always use tools to fetch real data — never make up prices or news.

CRITICAL FORMATTING RULES — follow exactly, no exceptions:
- NEVER use markdown tables (no | pipe characters ever)
- NEVER use ### or ## or # headers
- NEVER use --- dividers
- NEVER use bullet points with - (use • instead)
- Use <b>text</b> for bold only
- Use <i>text</i> for italics only
- When showing prices or portfolio, show each ticker on its own line: 📈 <b>{fmt("NVDA")}</b>: $204.65 (+1.33%)
- Always show tickers with company names, e.g. {fmt("NVDA")} not just NVDA
- Keep responses clean — plain text with <b>bold</b> for emphasis
- ALWAYS respond in English unless the user explicitly writes in Chinese"""

# ── Telegram Helpers ──────────────────────────────────────────────────────────

def clean_for_telegram(text: str) -> str:
    """Strip all markdown formatting that breaks Telegram HTML mode."""
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)   # **bold** → <b>bold</b>
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)         # *italic* → <i>italic</i>
    text = re.sub(r'#{1,6}\s+', '', text)                    # ## headers → removed
    text = re.sub(r'\|[^\n]+\|', '', text)                   # | tables | → removed
    text = re.sub(r'-{3,}', '—', text)                       # --- → —
    text = re.sub(r'\n{3,}', '\n\n', text)                   # triple newlines → double
    return text.strip()

def send_message(text: str, chat_id: str = None):
    """Send a message to Telegram, splitting if over 4000 chars."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    cleaned = clean_for_telegram(text)
    chunks = [cleaned[i:i+4000] for i in range(0, len(cleaned), 4000)]
    for chunk in chunks:
        requests.post(url, json={
            "chat_id": chat_id or TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
        })

def get_updates(offset: int = 0) -> list:
    """Poll Telegram for new messages."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    r = requests.get(url, params={"offset": offset, "timeout": 30})
    return r.json().get("result", []) if r.status_code == 200 else []

# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def deep_dive(ticker: str) -> str:
    """
    Run a full AI research deep dive on a stock ticker.
    Returns bull case, bear case, catalysts, valuation, and a buy/sell verdict.
    Use when the user asks for analysis, research, a deep dive, or wants to understand a company.
    """
    from src.tools.deep_dive import deep_dive as _deep_dive
    return _deep_dive(ticker.upper())

@tool
def get_price(ticker: str) -> str:
    """
    Get the live price and key market data for a stock ticker.
    Use when the user asks for a price, stock quote, or market data for a specific company.
    """
    from src.tools.prices import get_live_prices
    data = get_live_prices([ticker.upper()]).get(ticker.upper(), {})
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
    Get the latest news for a specific stock ticker or general AI infrastructure macro news.
    Use when the user asks about news, what happened, or latest developments.
    If no ticker is specified, return macro AI infrastructure news.
    """
    from src.tools.news_fetcher import get_news_for_tickers, get_macro_news
    if ticker:
        t = ticker.upper()
        articles = get_news_for_tickers([t]).get(t, [])
        if articles:
            msg = f"🗞 <b>Latest news: {fmt(t)}</b>\n\n"
            for a in articles[:5]:
                msg += f"• <b>{a['title']}</b>\n"
                if a.get("content"):
                    msg += f"  <i>{a['content'][:150].strip()}...</i>\n\n"
            return msg
        else:
            return f"No recent search results for {fmt(t)}. Provide a brief summary from your training knowledge about recent {fmt(t)} developments instead."
    else:
        articles = get_macro_news()
        msg = "🌍 <b>AI Infrastructure & Macro News</b>\n\n"
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
    dates = get_earnings_dates(WATCHLIST_TICKERS)
    msg = "📅 <b>Earnings Calendar</b>\n\n"
    upcoming = [
        (t, d) for t, d in dates.items()
        if d.get("days_until") is not None and d.get("days_until") >= 0
    ]
    upcoming.sort(key=lambda x: x[1]["days_until"])
    if upcoming:
        for ticker, data in upcoming:
            alert = " ⚠️ SOON" if data["alert"] else ""
            msg += f"• <b>{fmt(ticker)}</b>: {data['date']} ({data['days_until']} days){alert}\n"
    else:
        msg += "No upcoming earnings found in next 60 days."
    return msg

@tool
def get_portfolio() -> str:
    """
    Show the current watchlist with live prices and daily percentage moves.
    Use when the user asks about their portfolio, watchlist, holdings, or how stocks are doing.
    """
    from src.tools.prices import get_live_prices
    prices = get_live_prices(WATCHLIST_TICKERS)
    msg = f"💼 <b>Portfolio Watchlist</b>\n<i>{datetime.now().strftime('%d %b %Y, %H:%M GMT')}</i>\n\n"
    for t, d in prices.items():
        direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
        msg += f"{direction} <b>{fmt(t)}</b>: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"
    return msg

@tool
def get_market_briefing() -> str:
    """
    Get a market briefing with top watchlist moves and macro news.
    Use when the user asks about the market, morning briefing, how things are today, or what happened overnight.
    """
    from src.tools.news_fetcher import get_macro_news
    from src.tools.prices import get_live_prices
    prices = get_live_prices(WATCHLIST_TICKERS[:5])
    macro = get_macro_news()
    msg = f"🌅 <b>Market Briefing — {datetime.now().strftime('%d %B %Y')}</b>\n\n"
    msg += "<b>Top Watchlist Moves:</b>\n"
    for t, d in prices.items():
        direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
        msg += f"{direction} <b>{fmt(t)}</b>: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"
    msg += "\n<b>Macro & AI News:</b>\n"
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
    msg = f"📄 <b>SEC Filings: {fmt(ticker)}</b>\n\n"
    msg += f"• Latest 10-K: {summary['10-K'][0]['date'] if summary['10-K'] else 'N/A'}\n"
    msg += f"• Recent 10-Qs: {', '.join([f['date'] for f in summary['10-Q']]) or 'N/A'}\n"
    msg += f"• Recent 8-Ks: {', '.join([f['date'] for f in summary['8-K']]) or 'N/A'}\n"
    return msg

# ── Agent Setup ───────────────────────────────────────────────────────────────

llm = ChatDeepSeek(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    temperature=0.3,
)

tools = [
    deep_dive,
    get_price,
    get_news,
    get_earnings_calendar,
    get_portfolio,
    get_market_briefing,
    get_sec_filings,
]

agent = create_react_agent(llm, tools)

# ── Message Handler ───────────────────────────────────────────────────────────

def handle_message(text: str, chat_id: str):
    """Handle a user message using the LangGraph agent."""
    try:
        send_message("⏳ Working on it...", chat_id)
        result = agent.invoke({
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=text),
            ]
        })
        response = result["messages"][-1].content
        send_message(response, chat_id)
    except Exception as e:
        send_message(f"❌ Something went wrong: {str(e)[:200]}", chat_id)

# ── Bot Loop ──────────────────────────────────────────────────────────────────

def run_bot():
    print("🤖 AI Investor Bot (LangGraph) is running...")
    print("Press Ctrl+C to stop.\n")
    offset = 0
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id", ""))
                text = message.get("text", "")
                if text and chat_id:
                    print(f"[{datetime.now().strftime('%H:%M')}] {text}")
                    threading.Thread(
                        target=handle_message,
                        args=(text, chat_id)
                    ).start()
        except KeyboardInterrupt:
            print("\nBot stopped.")
            break
        except Exception as e:
            print(f"Loop error: {e}")

if __name__ == "__main__":
    run_bot()