import os
import schedule
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
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

# Focused list for morning briefing — fast and relevant
BRIEFING_TICKERS = [
    "NVDA", "TSM", "AVGO", "AMD", "ASML", "ARM", "ALAB", "PLTR", "APP", "CEG",
    "CRDO", "MSFT", "META", "ASTS", "RKLB", "VST", "TLN", "MP", "MSTR", "BTC"
]

# Tracks which tickers have already been alerted today — resets automatically at midnight
_alerted_today = {}


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

        # Fetch prices, news, earnings in parallel
        with ThreadPoolExecutor(max_workers=3) as ex:
            f_prices = ex.submit(get_live_prices, BRIEFING_TICKERS)
            f_macro = ex.submit(get_macro_news)
            f_dates = ex.submit(get_earnings_dates, BRIEFING_TICKERS)
            prices = f_prices.result()
            macro = f_macro.result()
            dates = f_dates.result()

        upcoming = [
            (t, d) for t, d in dates.items()
            if d.get("days_until") is not None and 0 <= d.get("days_until") <= 14
        ]
        upcoming.sort(key=lambda x: x[1]["days_until"])

        prices_text = ""
        for t, d in prices.items():
            if not d:
                continue
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
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
                "temperature": 0.3,
            }
        )

        briefing = response.json()["choices"][0]["message"]["content"] if response.status_code == 200 else "Could not generate AI briefing."

        header = f"🌅 <b>Morning Briefing — {datetime.now().strftime('%A %d %B %Y')}</b>\n\n"
        price_block = "<b>Watchlist:</b>\n"
        for t, d in prices.items():
            if not d:
                continue
            direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
            price_block += f"{direction} <b>{fmt(t)}</b>: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"

        send_telegram(header + price_block + "\n" + briefing)
        print(f"[{datetime.now().strftime('%H:%M')}] Morning briefing sent.")

        # Reset daily alert cache at morning briefing time (start of new trading day)
        _alerted_today.clear()
        print(f"[{datetime.now().strftime('%H:%M')}] Daily alert cache cleared.")

    except Exception as e:
        print(f"Morning briefing error: {e}")
        from src.tools.notify import send_telegram
        send_telegram(f"❌ Morning briefing error: {str(e)[:200]}")


def check_price_alerts():
    """Check for 8%+ moves — alert once per ticker per day only."""
    print(f"[{datetime.now().strftime('%H:%M')}] Checking price alerts...")
    try:
        from src.tools.prices import get_live_prices
        from src.tools.notify import send_telegram

        today = datetime.now().strftime("%Y-%m-%d")

        # Only alert on names actually held (shares > 0)
        held = [t for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0]
        tickers_to_check = held if held else WATCHLIST
        prices = get_live_prices(tickers_to_check)

        alerts = []
        for ticker, data in prices.items():
            if not data:
                continue
            change = data.get("change_pct") or 0
            if abs(change) >= 8.0:
                # Skip if already alerted for this ticker today
                if _alerted_today.get(ticker) == today:
                    continue
                direction = "📈" if change > 0 else "📉"
                alerts.append(
                    f"{direction} <b>{fmt(ticker)}</b>: {change:+.2f}% (${data.get('price')})"
                )
                _alerted_today[ticker] = today

        if alerts:
            msg = "🚨 <b>Price Alert — 8%+ Move</b>\n\n"
            msg += "\n".join(alerts)
            msg += "\n\n<i>Reply 'deep dive [ticker]' for full analysis.</i>"
            send_telegram(msg)
            print(f"[{datetime.now().strftime('%H:%M')}] Sent {len(alerts)} price alerts.")
        else:
            print(f"[{datetime.now().strftime('%H:%M')}] No new alerts triggered.")

    except Exception as e:
        print(f"Price alert error: {e}")


def run_scheduler():
    """Run the scheduler — morning briefing at 7am HKT, price alerts every 30 mins."""
    print("📅 Scheduler running...")
    print("• Morning briefing: 07:00 HKT Mon–Fri (23:00 UTC Sun–Thu)")
    print("• Price alerts: every 30 mins (8%+ moves, once per ticker per day)\n")

    # 7am HK time = 23:00 UTC previous day. Railway runs on UTC.
    schedule.every().sunday.at("23:00").do(send_morning_briefing)
    schedule.every().monday.at("23:00").do(send_morning_briefing)
    schedule.every().tuesday.at("23:00").do(send_morning_briefing)
    schedule.every().wednesday.at("23:00").do(send_morning_briefing)
    schedule.every().thursday.at("23:00").do(send_morning_briefing)

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