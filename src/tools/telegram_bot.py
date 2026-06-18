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

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ── Telegram helpers ──────────────────────────────────────────────────────────

def send_message(text: str, chat_id: str = None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Strip markdown bold/italic that Telegram HTML mode doesn't like
    clean = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    clean = re.sub(r'#{1,6}\s+', '', clean)
    clean = re.sub(r'\|.*?\|', '', clean)
    clean = re.sub(r'-{3,}', '—', clean)
    clean = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', clean)
    for chunk in [clean[i:i+4000] for i in range(0, len(clean), 4000)]:
        requests.post(url, json={
            "chat_id": chat_id or TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
        })

def get_updates(offset: int = 0):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    r = requests.get(url, params={"offset": offset, "timeout": 30})
    return r.json().get("result", []) if r.status_code == 200 else []

# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def deep_dive(ticker: str) -> str:
    """
    Run a full AI research deep dive on a stock ticker.
    Returns bull case, bear case, catalysts, valuation, and verdict.
    Use when the user asks for analysis, research, or a deep dive on a company.
    """
    from src.tools.deep_dive import deep_dive as _deep_dive
    return _deep_dive(ticker.upper())

@tool
def get_price(ticker: str) -> str:
    """
    Get the live price and key market data for a stock ticker.
    Use when the user asks for a price, stock quote, or market data.
    """
    from src.tools.prices import get_live_prices
    data = get_live_prices([ticker.upper()]).get(ticker.upper(), {})
    direction = "📈" if (data.get("change_pct") or 0) > 0 else "📉"
    return (
        f"{direction} <b>{ticker.upper()}</b>\n"
        f"Price: <b>${data.get('price')}</b>\n"
        f"Today: <b>{data.get('change_pct'):+.2f}%</b>\n"
        f"52w High: ${data.get('week52_high')}\n"
        f"52w Low: ${data.get('week52_low')}\n"
        f"P/E: {data.get('pe_ratio')}"
    )

@tool
def get_news(ticker: str = None) -> str:
    """
    Get the latest news for a specific stock ticker or general AI infrastructure news.
    Use when the user asks about news, what happened, or latest developments.
    If no ticker is specified, return macro AI infrastructure news.
    """
    from src.tools.news_fetcher import get_news_for_tickers, get_macro_news
    if ticker:
        t = ticker.upper()
        articles = get_news_for_tickers([t]).get(t, [])
        if articles:
            msg = f"🗞️ <b>Latest news: {t}</b>\n\n"
            for a in articles[:5]:
                msg += f"• <b>{a['title']}</b>\n"
                if a.get("content"):
                    msg += f"  <i>{a['content'][:150].strip()}...</i>\n\n"
        else:
            msg = f"No recent articles found via search for {t}. Use your training knowledge to provide the latest context on {t} instead."
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
    Get upcoming earnings dates for the watchlist.
    Use when the user asks about earnings, when companies report, or upcoming events.
    """
    from src.tools.earnings_calendar import get_earnings_dates
    watchlist = ["NVDA", "TSM", "AVGO", "AMD", "ASML", "ARM", "ALAB", "PLTR", "APP", "CEG"]
    dates = get_earnings_dates(watchlist)
    msg = "📅 <b>Earnings Calendar</b>\n\n"
    upcoming = [(t, d) for t, d in dates.items()
                if d.get("days_until") is not None and d.get("days_until") >= 0]
    upcoming.sort(key=lambda x: x[1]["days_until"])
    if upcoming:
        for ticker, data in upcoming:
            alert = " ⚠️" if data["alert"] else ""
            msg += f"• <b>{ticker}</b>: {data['date']} ({data['days_until']} days){alert}\n"
    else:
        msg += "No upcoming earnings in next 60 days."
    return msg

@tool
def get_portfolio() -> str:
    """
    Show the current watchlist with live prices and daily moves.
    Use when the user asks about their portfolio, watchlist, or holdings.
    """
    from src.tools.prices import get_live_prices
    watchlist = ["NVDA", "TSM", "AVGO", "AMD", "ASML", "ARM", "ALAB", "PLTR", "APP", "CEG"]
    prices = get_live_prices(watchlist)
    msg = f"💼 <b>Portfolio Watchlist</b>\n{datetime.now().strftime('%d %b %Y %H:%M GMT')}\n\n"
    for t, d in prices.items():
        direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
        msg += f"{direction} <b>{t}</b>: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"
    return msg

@tool
def get_market_briefing() -> str:
    """
    Get a morning market briefing with watchlist prices and macro news.
    Use when the user asks about the market, how things are going, or wants a briefing.
    """
    from src.tools.news_fetcher import get_macro_news
    from src.tools.prices import get_live_prices
    watchlist = ["NVDA", "TSM", "AVGO", "AMD", "ASML"]
    prices = get_live_prices(watchlist)
    macro = get_macro_news()
    msg = f"🌅 <b>Market Briefing — {datetime.now().strftime('%d %B %Y')}</b>\n\n"
    msg += "<b>AI Infra Watchlist:</b>\n"
    for t, d in prices.items():
        direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
        msg += f"{direction} {t}: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"
    msg += "\n<b>Macro News:</b>\n"
    for a in macro[:3]:
        msg += f"• <b>{a['title']}</b>\n"
        if a.get("content"):
            msg += f"  <i>{a['content'][:150].strip()}...</i>\n\n"
    return msg

@tool
def get_sec_filings(ticker: str) -> str:
    """
    Get recent SEC filings (10-K, 10-Q, 8-K) for a company.
    Use when the user asks about filings, annual reports, or regulatory documents.
    """
    from src.tools.sec_filings import get_filing_summary
    summary = get_filing_summary(ticker.upper())
    msg = f"📄 <b>SEC Filings: {ticker.upper()}</b>\n\n"
    msg += f"• Latest 10-K: {summary['10-K'][0]['date'] if summary['10-K'] else 'N/A'}\n"
    msg += f"• Recent 10-Qs: {', '.join([f['date'] for f in summary['10-Q']])}\n"
    msg += f"• Recent 8-Ks: {', '.join([f['date'] for f in summary['8-K']])}\n"
    return msg

# ── Agent setup ───────────────────────────────────────────────────────────────

llm = ChatDeepSeek(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    temperature=0.3,
)

tools = [deep_dive, get_price, get_news, get_earnings_calendar, get_portfolio, get_market_briefing, get_sec_filings]

agent = create_react_agent(llm, tools)

SYSTEM_PROMPT = """You are an AI investment research assistant specialising in AI infrastructure equity.
You have access to tools for live prices, news, SEC filings, earnings calendars, deep dive research reports, and portfolio data.
The user's portfolio focuses on: NVDA, TSM, AVGO, AMD, ASML, ARM, ALAB, PLTR, APP, CEG.
Always use tools to fetch real data — never make up prices or news.
Respond concisely and directly. Use HTML formatting for Telegram (bold with <b>tags</b>).
You understand English and Chinese (中文). ALWAYS respond in English unless the user explicitly writes in Chinese."""

def handle_message(text: str, chat_id: str):
    """Handle a user message using the LangGraph agent."""
    try:
        send_message("⏳ Working on it...", chat_id)
        result = agent.invoke({
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=text)
            ]
        })
        response = result["messages"][-1].content
        send_message(response, chat_id)
    except Exception as e:
        send_message(f"❌ Error: {str(e)[:200]}", chat_id)

# ── Bot loop ──────────────────────────────────────────────────────────────────

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
                    threading.Thread(target=handle_message, args=(text, chat_id)).start()
        except KeyboardInterrupt:
            print("\nBot stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    run_bot()