import os
import schedule
import time
import threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def send_morning_briefing():
    """Build and send the full morning briefing."""
    print(f"[{datetime.now().strftime('%H:%M')}] Running morning briefing...")
    
    try:
        from src.tools.prices import get_live_prices
        from src.tools.news_fetcher import get_macro_news
        from src.tools.earnings_calendar import get_earnings_dates
        from src.tools.notify import send_telegram
        import requests

        WATCHLIST = ["NVDA", "TSM", "AVGO", "AMD", "ASML", "ARM", "ALAB", "PLTR", "APP", "CEG"]
        DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

        # Step 1 — Live prices
        prices = get_live_prices(WATCHLIST)

        # Step 2 — Macro news
        macro = get_macro_news()

        # Step 3 — Earnings alerts
        dates = get_earnings_dates(WATCHLIST)
        upcoming = [
            (t, d) for t, d in dates.items()
            if d.get("days_until") is not None and 0 <= d.get("days_until") <= 14
        ]
        upcoming.sort(key=lambda x: x[1]["days_until"])

        # Step 4 — Build context for DeepSeek
        prices_text = ""
        for t, d in prices.items():
            direction = "▲" if (d.get("change_pct") or 0) > 0 else "▼"
            prices_text += f"{direction} {t}: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"

        news_text = ""
        for a in macro[:5]:
            news_text += f"- {a['title']}\n"
            if a.get("content"):
                news_text += f"  {a['content'][:200]}\n"

        earnings_text = ""
        if upcoming:
            for t, d in upcoming:
                earnings_text += f"- {t}: reports in {d['days_until']} days ({d['date']})\n"
        else:
            earnings_text = "No earnings in the next 14 days."

        # Step 5 — DeepSeek synthesis
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }

        prompt = f"""You are an AI investment research assistant. Write a concise morning briefing for an AI infrastructure equity investor.

WATCHLIST PRICES TODAY:
{prices_text}

MACRO & AI NEWS:
{news_text}

UPCOMING EARNINGS (next 14 days):
{earnings_text}

Write a morning briefing covering:
1. Overall market tone for AI infrastructure names (1-2 sentences)
2. Top movers — highlight the 2-3 biggest moves and briefly explain why
3. Key news — what matters from the headlines above and why it affects holdings
4. Earnings watch — flag any upcoming earnings and what to watch for
5. One thing to watch today

Rules:
- Maximum 300 words
- No markdown tables, no ### headers
- Use • for bullet points
- Be direct and specific — no generic statements
- Format for Telegram using <b>bold</b> for emphasis"""

        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
                "temperature": 0.3,
            }
        )

        if response.status_code == 200:
            briefing = response.json()["choices"][0]["message"]["content"]
        else:
            briefing = "Could not generate AI briefing. Raw data below."

        # Step 6 — Format and send
        header = f"🌅 <b>Morning Briefing — {datetime.now().strftime('%A %d %B %Y')}</b>\n\n"
        
        # Add raw prices as quick reference
        price_block = "<b>Watchlist:</b>\n"
        for t, d in prices.items():
            direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
            price_block += f"{direction} <b>{t}</b>: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"

        full_message = header + price_block + "\n" + briefing

        send_telegram(full_message)
        print(f"[{datetime.now().strftime('%H:%M')}] Morning briefing sent.")

    except Exception as e:
        print(f"Morning briefing error: {e}")
        from src.tools.notify import send_telegram
        send_telegram(f"❌ Morning briefing error: {str(e)[:200]}")


def run_scheduler():
    """Run the scheduler — sends briefing at 7am GMT on weekdays."""
    print("📅 Scheduler running...")
    print("Morning briefing scheduled for 07:00 GMT on weekdays.\n")

    # Schedule weekday briefings at 7am GMT
    schedule.every().monday.at("07:00").do(send_morning_briefing)
    schedule.every().tuesday.at("07:00").do(send_morning_briefing)
    schedule.every().wednesday.at("07:00").do(send_morning_briefing)
    schedule.every().thursday.at("07:00").do(send_morning_briefing)
    schedule.every().friday.at("07:00").do(send_morning_briefing)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    # Test mode — send immediately
    print("Test mode — sending briefing now...")
    send_morning_briefing()