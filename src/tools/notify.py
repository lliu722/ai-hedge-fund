import os
import re
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Client-side socket timeout on every Telegram send. Without it, a stalled or
# half-open connection blocks the calling thread forever. These sends run on
# the SCHEDULER thread (alerts, briefings, close summaries) — one hung send
# wedges the scheduler and every future alert stops silently, with nothing
# logged. Same failure class as the getUpdates() hang fixed 2026-08-10, on the
# send path instead of the receive path.
_SEND_TIMEOUT = 20


def clean_for_telegram(text: str) -> str:
    """
    Convert LLM-generated markdown to Telegram HTML (parse_mode="HTML" has no
    idea what **bold** or # headers mean -- they go out as literal characters
    otherwise). send_message() in telegram_bot.py always ran this; send_telegram()
    here never did, so any scheduled message (morning briefing, alerts, etc.)
    built from raw LLM text could ship with literal "**word**" asterisks whenever
    the model slipped into markdown despite prompt instructions to use <b> tags.
    Moved here and applied inside send_telegram/send_telegram_with_buttons so
    every call site gets it automatically instead of each one having to remember.
    """
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'#{1,6}\s+', '', text)
    text = re.sub(r'\|[^\n]+\|', '', text)
    text = re.sub(r'-{3,}', '—', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def send_telegram(message: str) -> bool:
    """Send a message to your Telegram bot. Auto-splits at 4096 chars."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Telegram credentials not found in .env")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    message = clean_for_telegram(message)

    # Split into chunks of 4096 chars, breaking on newlines where possible
    chunks = []
    while len(message) > 4096:
        split_at = message.rfind("\n", 0, 4096)
        if split_at == -1:
            split_at = 4096
        chunks.append(message[:split_at])
        message = message[split_at:].lstrip("\n")
    chunks.append(message)

    ok = True
    for chunk in chunks:
        try:
            response = requests.post(
                url,
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"},
                timeout=_SEND_TIMEOUT,
            )
            if response.status_code != 200:
                print(f"Telegram error: {response.text}")
                ok = False
        except Exception as e:
            print(f"Telegram exception: {e}")
            ok = False
    return ok


def send_telegram_with_buttons(message: str, buttons: list[list[dict]]) -> bool:
    """Send a Telegram message with inline keyboard buttons.
    buttons = [[{"text": "NVDA", "callback_data": "shadow:NVDA"}, ...], ...]
    """
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    try:
        import json
        payload = {
            "chat_id": chat_id,
            "text": clean_for_telegram(message)[:4096],
            "parse_mode": "HTML",
            "reply_markup": json.dumps({"inline_keyboard": buttons}),
        }
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=_SEND_TIMEOUT,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram button message error: {e}")
        return False


def send_price_alert(ticker: str, price: float, change_pct: float) -> bool:
    """Send a price movement alert."""
    direction = "📈" if change_pct > 0 else "📉"
    message = (
        f"{direction} <b>{ticker} Price Alert</b>\n"
        f"Price: <b>${price:.2f}</b>\n"
        f"Change: <b>{change_pct:+.2f}%</b>\n"
        f"Time: {datetime.now().strftime('%H:%M GMT')}"
    )
    return send_telegram(message)

def send_filing_alert(ticker: str, form_type: str, date: str) -> bool:
    """Send an SEC filing alert."""
    message = (
        f"📄 <b>New SEC Filing: {ticker}</b>\n"
        f"Form: <b>{form_type}</b>\n"
        f"Filed: {date}\n"
        f"Fetching and summarising now..."
    )
    return send_telegram(message)

def send_earnings_alert(ticker: str, days_until: int, date: str) -> bool:
    """Send an earnings proximity alert."""
    message = (
        f"⏰ <b>Earnings Alert: {ticker}</b>\n"
        f"Reports in <b>{days_until} days</b>\n"
        f"Date: {date}"
    )
    return send_telegram(message)

def send_morning_briefing(briefing: str) -> bool:
    """Send the daily morning briefing."""
    header = f"🌅 <b>Morning Briefing — {datetime.now().strftime('%A %d %B %Y')}</b>\n\n"
    return send_telegram(header + briefing)

if __name__ == "__main__":
    print("Testing Telegram notifications...")
    result = send_telegram(
        "🤖 <b>AI Investor System — Test Message</b>\n"
        "Your notification system is working correctly.\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    if result:
        print("✅ Message sent — check your Telegram!")
    else:
        print("❌ Failed to send message")