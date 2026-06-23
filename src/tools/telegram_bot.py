import os
import re
import json
import requests
import threading
from datetime import datetime
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain_deepseek import ChatDeepSeek
from src.tools.notion_holdings import get_holdings_cached, FALLBACK_WATCHLIST

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ── Quick-action button layout ────────────────────────────────────────────────
MAIN_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "💼 Portfolio",  "callback_data": "portfolio"},
            {"text": "🌅 Briefing",   "callback_data": "briefing"},
        ],
        [
            {"text": "📅 Earnings",   "callback_data": "earnings"},
            {"text": "🔍 Deep Dive",  "callback_data": "deepdive"},
        ],
    ]
}


def load_watchlist():
    try:
        return get_holdings_cached()
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
Always use tools to fetch real data — never make up prices or news.

CRITICAL FORMATTING RULES — follow exactly, no exceptions:
- NEVER use markdown tables (no | pipe characters ever)
- NEVER use ### or ## or # headers
- NEVER use --- dividers
- NEVER use bullet points with - (use • instead)
- Use <b>text</b> for bold only
- Use <i>text</i> for italics only
- When showing prices, show each ticker on its own line: 📈 <b>{fmt("NVDA")}</b>: $204.65 (+1.33%)
- Always show tickers with company names, e.g. {fmt("NVDA")} not just NVDA
- Keep responses clean — plain text with <b>bold</b> for emphasis
- ALWAYS respond in English unless the user explicitly writes in Chinese"""

# ── Telegram Helpers ──────────────────────────────────────────────────────────

def clean_for_telegram(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'#{1,6}\s+', '', text)
    text = re.sub(r'\|[^\n]+\|', '', text)
    text = re.sub(r'-{3,}', '—', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def send_message(text: str, chat_id: str = None, show_buttons: bool = True):
    """Send a message with optional quick-action buttons."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    cleaned = clean_for_telegram(text)
    chunks = [cleaned[i:i+4000] for i in range(0, len(cleaned), 4000)]
    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": chat_id or TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
        }
        if show_buttons and i == len(chunks) - 1:
            payload["reply_markup"] = json.dumps(MAIN_KEYBOARD)
        requests.post(url, json=payload)


def answer_callback(callback_query_id: str):
    """Acknowledge a button tap so Telegram stops showing the loading spinner."""
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
        json={"callback_query_id": callback_query_id}
    )


def get_updates(offset: int = 0) -> list:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    r = requests.get(url, params={
        "offset": offset,
        "timeout": 30,
        "allowed_updates": ["message", "callback_query"]
    })
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
    msg = f"💼 <b>Portfolio Watchlist</b>\n<i>{datetime.now().strftime('%d %b %Y, %H:%M')}</i>\n\n"
    for t, d in prices.items():
        if not d:
            continue
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
        if not d:
            continue
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

memory = MemorySaver()
agent = create_react_agent(llm, tools, checkpointer=memory)


# ── Button Callback Handler ───────────────────────────────────────────────────

def handle_callback(callback_data: str, chat_id: str, callback_query_id: str):
    """Handle a button tap."""
    answer_callback(callback_query_id)

    if callback_data == "portfolio":
        send_message("⏳ Loading portfolio...", chat_id, show_buttons=False)
        handle_message("show my portfolio", chat_id)

    elif callback_data == "briefing":
        send_message("⏳ Generating briefing...", chat_id, show_buttons=False)
        handle_message("morning briefing", chat_id)

    elif callback_data == "earnings":
        send_message("⏳ Loading earnings calendar...", chat_id, show_buttons=False)
        handle_message("any earnings coming up", chat_id)

    elif callback_data == "deepdive":
        send_message(
            "🔍 <b>Deep Dive</b>\n\nWhich ticker would you like to research?\n\n"
            "<i>Just type the ticker symbol, e.g. NVDA or ASML</i>",
            chat_id,
            show_buttons=False
        )


# ── Message Handler ───────────────────────────────────────────────────────────

def handle_message(text: str, chat_id: str):
    try:
        lowered = text.strip().lower()

        # /start command
        if lowered == "/start":
            send_message(
                "🤖 <b>AI Investor — Welcome</b>\n\n"
                "Your personal AI research analyst. Ask me anything about your portfolio "
                "or tap a button below to get started.",
                chat_id
            )
            return

        # Manual scheduler triggers
        if lowered in ("send briefing", "test briefing"):
            from src.tools.scheduler import send_morning_briefing
            send_message("⏳ Generating briefing now...", chat_id, show_buttons=False)
            send_morning_briefing()
            return

        if lowered in ("send alert", "test alert", "check alerts"):
            from src.tools.scheduler import check_price_alerts
            send_message("⏳ Checking price alerts now...", chat_id, show_buttons=False)
            check_price_alerts()
            return

        if lowered in ("weekly digest", "send digest", "weekly report"):
            from src.tools.scheduler import send_weekly_digest
            send_message("⏳ Generating weekly digest...", chat_id, show_buttons=False)
            send_weekly_digest()
            return

        if lowered in ("picks", "recommendations", "what should i buy", "stock picks", "ai picks"):
            from src.tools.recommendations import get_recommendations
            send_message("⏳ Running AI stock picks — Cathie Wood, Druckenmiller, Damodaran debating...", chat_id, show_buttons=False)
            result = get_recommendations()
            send_message(result, chat_id)
            return

        send_message("⏳ Working on it...", chat_id, show_buttons=False)
        result = agent.invoke(
            {
                "messages": [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=text),
                ]
            },
            config={"configurable": {"thread_id": chat_id}}
        )
        response = result["messages"][-1].content
        send_message(response, chat_id)

    except Exception as e:
        send_message(f"❌ Something went wrong: {str(e)[:200]}", chat_id)


# ── Bot Loop ──────────────────────────────────────────────────────────────────

def run_bot():
    print("🤖 AI Investor Bot (LangGraph) is running...")
    send_message(
        "🤖 <b>AI Investor is online</b>\n\n"
        "Your personal research analyst is ready. "
        "Ask me anything or tap a button below.",
        show_buttons=True
    )
    offset = 0
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1

                # Handle button taps
                if "callback_query" in update:
                    cq = update["callback_query"]
                    chat_id = str(cq["message"]["chat"]["id"])
                    callback_data = cq.get("data", "")
                    callback_query_id = cq["id"]
                    print(f"[{datetime.now().strftime('%H:%M')}] Button: {callback_data}")
                    threading.Thread(
                        target=handle_callback,
                        args=(callback_data, chat_id, callback_query_id)
                    ).start()
                    continue

                # Handle text messages
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


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        from src.tools.scheduler import run_scheduler
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        print("📅 Scheduler thread started.")
    except Exception as e:
        print(f"Could not start scheduler thread: {e}")

    run_bot()