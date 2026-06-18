import os
import json
import requests
import threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

def send_message(text: str, chat_id: str = None):
    """Send a message via Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id or TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    requests.post(url, json=payload)

def understand_intent(message: str) -> dict:
    """
    Use DeepSeek to understand what the user is asking for.
    Returns a structured intent with action and parameters.
    """
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    system = """You are an intent classifier for an AI investment research assistant.
Classify the user message into one of these actions:
- deep_dive: user wants a research report on a specific company
- price: user wants current price/market data for a ticker
- news: user wants latest news on a company or topic
- earnings: user wants upcoming earnings dates
- briefing: user wants a market overview or morning briefing
- portfolio: user wants to see their portfolio summary
- help: user is unsure what to ask

Respond ONLY with valid JSON in this exact format:
{"action": "action_name", "ticker": "TICKER_OR_NULL", "query": "original query"}

Examples:
"what's going on with nvidia" -> {"action": "deep_dive", "ticker": "NVDA", "query": "what's going on with nvidia"}
"give me the price of ASML" -> {"action": "price", "ticker": "ASML", "query": "give me the price of ASML"}
"any earnings coming up" -> {"action": "earnings", "ticker": null, "query": "any earnings coming up"}
"how is the market today" -> {"action": "briefing", "ticker": null, "query": "how is the market today"}
"最新的NVDA消息" -> {"action": "news", "ticker": "NVDA", "query": "最新的NVDA消息"}
"AVGO的深度分析" -> {"action": "deep_dive", "ticker": "AVGO", "query": "AVGO的深度分析"}"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": message}
        ],
        "max_tokens": 100,
        "temperature": 0.1,
    }
    response = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers=headers,
        json=payload,
    )
    if response.status_code == 200:
        content = response.json()["choices"][0]["message"]["content"]
        # Clean up any markdown
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    return {"action": "help", "ticker": None, "query": message}

def handle_message(message: str, chat_id: str):
    """Route a message to the right tool and send back a response."""
    send_message("⏳ Processing...", chat_id)

    try:
        intent = understand_intent(message)
        action = intent.get("action")
        ticker = intent.get("ticker")

        if action == "deep_dive" and ticker:
            send_message(f"🔬 Running deep dive on <b>{ticker}</b>...\nThis takes about 60 seconds.", chat_id)
            from src.tools.deep_dive import deep_dive
            report = deep_dive(ticker)
            # Split long messages for Telegram (4096 char limit)
            if len(report) > 4000:
                chunks = [report[i:i+4000] for i in range(0, len(report), 4000)]
                for chunk in chunks:
                    send_message(chunk, chat_id)
            else:
                send_message(report, chat_id)

        elif action == "price" and ticker:
            from src.tools.prices import get_live_prices
            prices = get_live_prices([ticker])
            data = prices.get(ticker, {})
            direction = "📈" if (data.get("change_pct") or 0) > 0 else "📉"
            msg = (
                f"{direction} <b>{ticker}</b>\n"
                f"Price: <b>${data.get('price')}</b>\n"
                f"Today: <b>{data.get('change_pct'):+.2f}%</b>\n"
                f"52w High: ${data.get('week52_high')}\n"
                f"52w Low: ${data.get('week52_low')}\n"
                f"P/E: {data.get('pe_ratio')}"
            )
            send_message(msg, chat_id)

        elif action == "news":
            from src.tools.news_fetcher import get_news_for_tickers, get_macro_news
            if ticker:
                news = get_news_for_tickers([ticker])
                articles = news.get(ticker, [])
                if articles:
                    msg = f"🗞️ <b>Latest news: {ticker}</b>\n\n"
                    for a in articles[:5]:
                        msg += f"• {a['title']}\n"
                else:
                    msg = f"No recent news found for {ticker}."
            else:
                articles = get_macro_news()
                msg = "🌍 <b>Macro & AI Infrastructure News</b>\n\n"
                for a in articles[:5]:
                    msg += f"• {a['title']}\n"
            send_message(msg, chat_id)

        elif action == "earnings":
            from src.tools.earnings_calendar import get_earnings_dates
            watchlist = ["NVDA", "TSM", "AVGO", "AMD", "ASML", "ARM", "ALAB", "PLTR", "APP", "CEG"]
            dates = get_earnings_dates(watchlist)
            msg = "📅 <b>Earnings Calendar</b>\n\n"
            upcoming = [(t, d) for t, d in dates.items() if d.get("days_until") is not None and d.get("days_until") >= 0]
            upcoming.sort(key=lambda x: x[1]["days_until"])
            if upcoming:
                for ticker, data in upcoming:
                    alert = " ⚠️" if data["alert"] else ""
                    msg += f"• <b>{ticker}</b>: {data['date']} ({data['days_until']} days){alert}\n"
            else:
                msg += "No upcoming earnings found in next 60 days."
            send_message(msg, chat_id)

        elif action == "briefing":
            from src.tools.news_fetcher import get_macro_news
            from src.tools.prices import get_live_prices
            watchlist = ["NVDA", "TSM", "AVGO", "AMD", "ASML"]
            prices = get_live_prices(watchlist)
            macro = get_macro_news()
            msg = f"🌅 <b>Market Briefing — {datetime.now().strftime('%d %B %Y')}</b>\n\n"
            msg += "<b>Your Watchlist:</b>\n"
            for t, d in prices.items():
                direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
                msg += f"{direction} {t}: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"
            msg += "\n<b>Macro News:</b>\n"
            for a in macro[:3]:
                msg += f"• {a['title']}\n"
            send_message(msg, chat_id)

        elif action == "portfolio":
            from src.tools.prices import get_live_prices
            watchlist = ["NVDA", "TSM", "AVGO", "AMD", "ASML", "ARM", "ALAB", "PLTR", "APP", "CEG"]
            prices = get_live_prices(watchlist)
            msg = f"💼 <b>Portfolio Watchlist</b>\n{datetime.now().strftime('%H:%M GMT')}\n\n"
            for t, d in prices.items():
                direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
                msg += f"{direction} <b>{t}</b>: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"
            send_message(msg, chat_id)

        else:
            msg = (
                "🤖 <b>AI Investor — What I can do:</b>\n\n"
                "• <b>Deep dive</b> — 'deep dive NVDA' or '分析一下ASML'\n"
                "• <b>Price</b> — 'AVGO price' or 'what's AMD at'\n"
                "• <b>News</b> — 'latest NVDA news' or '最新消息'\n"
                "• <b>Earnings</b> — 'any earnings coming up'\n"
                "• <b>Briefing</b> — 'morning briefing' or 'how's the market'\n"
                "• <b>Portfolio</b> — 'show my portfolio'\n\n"
                "Just talk naturally — English or 中文 both work."
            )
            send_message(msg, chat_id)

    except Exception as e:
        send_message(f"❌ Error: {str(e)[:200]}", chat_id)

def get_updates(offset: int = 0) -> list:
    """Poll Telegram for new messages."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"offset": offset, "timeout": 30, "allowed_updates": ["message"]}
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json().get("result", [])
    return []

def run_bot():
    """Main bot loop — polls for messages and handles them."""
    print("🤖 AI Investor Bot is running...")
    print("Send a message to your Telegram bot to get started.")
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
                    print(f"[{datetime.now().strftime('%H:%M')}] Received: {text}")
                    # Handle in a thread so bot stays responsive
                    thread = threading.Thread(
                        target=handle_message,
                        args=(text, chat_id)
                    )
                    thread.start()

        except KeyboardInterrupt:
            print("\nBot stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    run_bot()