import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def send_telegram(message: str) -> bool:
    """Send a message to your Telegram bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Telegram credentials not found in .env")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            return True
        else:
            print(f"Telegram error: {response.text}")
            return False
    except Exception as e:
        print(f"Telegram exception: {e}")
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