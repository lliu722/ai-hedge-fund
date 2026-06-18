import os
import schedule
import time
from datetime import datetime
from dotenv import load_dotenv
from src.tools.notion_holdings import get_holdings_from_notion, FALLBACK_WATCHLIST

load_dotenv()


def load_watchlist():
    try:
        return get_holdings_from_notion()
    except Exception:
        return FALLBACK_WATCHLIST


WATCHLIST_DATA = load_watchlist()
WATCHLIST = list(WATCHLIST_DATA.keys())


def fmt(ticker: str) -> str:
    t = ticker.upper()
    name = WATCHLIST_DATA.get(t, {}).get("name", "")
    return f"{t} ({name})" if name else t


def send_morning_briefing():
    """Build and send the full morning briefing."""
    print(f"[{datetime.now().strftime('%H:%M')}] Running morning briefing...")
    try:
        from src.tools.prices import get_live_prices
        from src.tools.news_fetcher import get_macro_news
        from src.tools.earnings_calendar import get_earnings_dates
        from src.tools.notify import send_telegram
        import requests

        DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
        prices = get_live_prices(WATCHLIST)
        macro = get_macro_news()
        dates = get_earnings_dates(WATCHLIST)

        upcoming = [
            (t, d) for t, d in dates.items()
            if d.get("days_until") is not None and 0 <= d.get("days_until") <= 14
        ]
        upcoming.sort(key=lambda x: x[1]["days_until"])

        prices_text = ""
        for t, d in prices.items():
            direction = "▲" if (d.get("change_pct") or 0) > 0 else "▼"
            prices_text += f"{direction} {fmt(t)}: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"

        news_text = ""
        for a in macro[:5]:
            news_text += f"- {a['title']}\n"
            if a.get("content"):
                news_text += f"  {a['content'][:200]}\n"

        earnings_text = ""
        if upcoming:
            for t, d in upcoming:
                earnings_text += f"- {fmt(t)}: reports in {d['days_until']} days ({d['date']})\n"
        else:
            earnings_text = "No earnings in the next 14 days."

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
            briefing = "Could not generate AI briefing."

        header = f"🌅 <b>Morning Briefing — {datetime.now().strftime('%A %d %B %Y')}</b>\n\n"
        price_block = "<b>Watchlist:</b>\n"
        for t, d in prices.items():
            direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
            price_block += f"{direction} <b>{fmt(t)}</b>: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"

        send_telegram(header + price_block + "\n" + briefing)
        print(f"[{datetime.now().strftime('%H:%M')}] Morning briefing sent.")

    except Exception as e:
        print(f"Morning briefing error: {e}")
        from src.tools.notify import send_telegram
        send_telegram(f"❌ Morning briefing error: {str(e)[:200]}")


def check_price_alerts():
    """Check for significant price moves and alert if >5%."""
    print(f"[{datetime.now().strftime('%H:%M')}] Checking price alerts...")
    try:
        from src.tools.prices import get_live_prices
        from src.tools.notify import send_telegram

        prices = get_live_prices(WATCHLIST)
        alerts = []

        for ticker, data in prices.items():
            change = data.get("change_pct") or 0
            if abs(change) >= 5.0:
                direction = "📈" if change > 0 else "📉"
                alerts.append(
                    f"{direction} <b>{fmt(ticker)}</b>: {change:+.2f}% (${data.get('price')})"
                )

        if alerts:
            msg = "🚨 <b>Price Alert — 5%+ Move</b>\n\n"
            msg += "\n".join(alerts)
            msg += "\n\n<i>Reply 'deep dive [ticker]' for full analysis.</i>"
            send_telegram(msg)
            print(f"[{datetime.now().strftime('%H:%M')}] Sent {len(alerts)} price alerts.")
        else:
            print(f"[{datetime.now().strftime('%H:%M')}] No alerts triggered.")

    except Exception as e:
        print(f"Price alert error: {e}")


def run_scheduler():
    """Run the scheduler."""
    print("📅 Scheduler running...")
    print("• Morning briefing: 07:00 GMT weekdays")
    print("• Price alerts: every 30 mins\n")

    # Morning briefing — weekdays 7am GMT
    schedule.every().monday.at("07:00").do(send_morning_briefing)
    schedule.every().tuesday.at("07:00").do(send_morning_briefing)
    schedule.every().wednesday.at("07:00").do(send_morning_briefing)
    schedule.every().thursday.at("07:00").do(send_morning_briefing)
    schedule.every().friday.at("07:00").do(send_morning_briefing)

    # Price alerts — every 30 minutes
    schedule.every(30).minutes.do(check_price_alerts)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "price":
        print("Testing price alerts...")
        check_price_alerts()
    else:
        print("Testing morning briefing...")
        send_morning_briefing()