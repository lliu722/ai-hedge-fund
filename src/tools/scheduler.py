import os
import schedule
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from src.tools.notion_holdings import get_holdings_cached, FALLBACK_WATCHLIST

load_dotenv()


def load_watchlist():
    try:
        return get_holdings_cached()
    except Exception:
        return FALLBACK_WATCHLIST


WATCHLIST_DATA = load_watchlist()
WATCHLIST = list(WATCHLIST_DATA.keys())

# Focused list for morning briefing — fast and relevant
BRIEFING_TICKERS = [
    "NVDA", "TSM", "AVGO", "AMD", "ASML", "ARM", "ALAB", "PLTR", "APP", "CEG",
    "CRDO", "MSFT", "META", "ASTS", "RKLB", "VST", "TLN", "MP", "MSTR", "BTC"
]

# Macro indices and sector ETFs for weekly digest
MACRO_TICKERS = {
    "SPY":      "S&P 500",
    "QQQ":      "Nasdaq 100",
    "GLD":      "Gold",
    "USO":      "Oil",
    "DX-Y.NYB": "US Dollar",
    "BTC-USD":  "Bitcoin",
    "GC=F":    "Gold",
    "CL=F":    "WTI Oil",
    "BZ=F":    "Brent Oil",
    "HG=F":    "Copper",
    "NG=F":    "Natural Gas",
    "SI=F":    "Silver",
    "TLT":      "20Y Treasuries",
    "^VIX":     "Volatility (VIX)",
}

SECTOR_ETFS = {
    "XLK":  "Technology",
    "XLE":  "Energy",
    "XLF":  "Financials",
    "XLV":  "Healthcare",
    "XLI":  "Industrials",
    "XLB":  "Materials",
    "ARKK": "Innovation / High Growth",
    "SMH":  "Semiconductors",
    "ICLN": "Clean Energy",
    "IYZ":  "Telecom",
}

# Tracks which tickers have already been alerted today — resets at morning briefing
_alerted_today = {}

# ── Market Hours (UTC) ────────────────────────────────────────────────────────
MARKET_HOURS_UTC = {
    "Korea":  (0*60+0,   6*60+30),
    "HK":     (1*60+30,  8*60+0),
    "China":  (1*60+30,  7*60+0),
    "Taiwan": (1*60+0,   5*60+30),
    "EU":     (7*60+0,  15*60+30),
    "UK":     (8*60+0,  16*60+30),
    "US":     (13*60+30, 20*60+0),
}


def _open_markets() -> list:
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return []
    time_utc = now.hour * 60 + now.minute
    return [m for m, (o, c) in MARKET_HOURS_UTC.items() if o <= time_utc <= c]


def _is_market_open() -> bool:
    return len(_open_markets()) > 0


def fmt(ticker: str) -> str:
    t = ticker.upper()
    name = WATCHLIST_DATA.get(t, {}).get("name", "")
    return f"{t} ({name})" if name else t


# ── Morning Briefing ──────────────────────────────────────────────────────────

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

        _alerted_today.clear()
        print(f"[{datetime.now().strftime('%H:%M')}] Daily alert cache cleared.")

    except Exception as e:
        print(f"Morning briefing error: {e}")
        from src.tools.notify import send_telegram
        send_telegram(f"❌ Morning briefing error: {str(e)[:200]}")


# ── Weekly Macro Digest ───────────────────────────────────────────────────────

def send_weekly_digest():
    """Build and send the Sunday weekly macro + thematic digest."""
    print(f"[{datetime.now().strftime('%H:%M')}] Running weekly digest...")
    try:
        from src.tools.prices import get_live_prices
        from src.tools.earnings_calendar import get_earnings_dates
        from src.tools.notify import send_telegram
        import requests

        DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

        # Fetch macro indices, sector ETFs, AI watchlist, news in parallel
        def fetch_outside_news():
            r = requests.get(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {os.getenv('TAVILY_API_KEY')}"},
                json={
                    "query": "stock market sector rotation theme investing week",
                    "max_results": 8,
                    "search_depth": "basic",
                },
                timeout=10
            )
            return r.json().get("results", []) if r.status_code == 200 else []

        def fetch_macro_news():
            r = requests.get(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {os.getenv('TAVILY_API_KEY')}"},
                json={
                    "query": "Fed interest rates CPI jobs inflation macro economic outlook week",
                    "max_results": 5,
                    "search_depth": "basic",
                },
                timeout=10
            )
            return r.json().get("results", []) if r.status_code == 200 else []

        macro_tickers = list(MACRO_TICKERS.keys())
        sector_tickers = list(SECTOR_ETFS.keys())

        with ThreadPoolExecutor(max_workers=5) as ex:
            f_macro_prices = ex.submit(get_live_prices, macro_tickers)
            f_sector_prices = ex.submit(get_live_prices, sector_tickers)
            f_ai_prices = ex.submit(get_live_prices, BRIEFING_TICKERS)
            f_outside_news = ex.submit(fetch_outside_news)
            f_macro_news = ex.submit(fetch_macro_news)
            f_earnings = ex.submit(get_earnings_dates, BRIEFING_TICKERS)

            macro_prices = f_macro_prices.result()
            sector_prices = f_sector_prices.result()
            ai_prices = f_ai_prices.result()
            outside_news = f_outside_news.result()
            macro_news = f_macro_news.result()
            earnings = f_earnings.result()

        # Build macro summary
        macro_text = ""
        for ticker, label in MACRO_TICKERS.items():
            d = macro_prices.get(ticker, {})
            if d and d.get("price"):
                direction = "▲" if (d.get("change_pct") or 0) > 0 else "▼"
                macro_text += f"{direction} {label}: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"

        # Build sector summary — sort by % change
        sector_moves = []
        for ticker, label in SECTOR_ETFS.items():
            d = sector_prices.get(ticker, {})
            if d and d.get("change_pct") is not None:
                sector_moves.append((label, d.get("change_pct"), d.get("price")))
        sector_moves.sort(key=lambda x: x[1], reverse=True)

        sector_text = ""
        for label, chg, price in sector_moves:
            direction = "▲" if chg > 0 else "▼"
            sector_text += f"{direction} {label}: {chg:+.2f}%\n"

        # Build AI watchlist weekly summary
        ai_text = ""
        for t, d in ai_prices.items():
            if not d:
                continue
            direction = "▲" if (d.get("change_pct") or 0) > 0 else "▼"
            ai_text += f"{direction} {fmt(t)}: {d.get('change_pct'):+.2f}%\n"

        # Upcoming earnings next 7 days
        upcoming = [
            (t, d) for t, d in earnings.items()
            if d.get("days_until") is not None and 0 <= d.get("days_until") <= 7
        ]
        upcoming.sort(key=lambda x: x[1]["days_until"])
        earnings_text = ""
        if upcoming:
            for t, d in upcoming:
                earnings_text += f"- {fmt(t)}: {d['date']} ({d['days_until']} days)\n"
        else:
            earnings_text = "No major earnings in the next 7 days."

        # Outside AI news
        outside_text = ""
        for a in outside_news[:5]:
            outside_text += f"- {a.get('title', '')}\n"
            if a.get("content"):
                outside_text += f"  {a['content'][:150]}\n"

        # Macro news
        macro_news_text = ""
        for a in macro_news[:4]:
            macro_news_text += f"- {a.get('title', '')}\n"
            if a.get("content"):
                macro_news_text += f"  {a['content'][:150]}\n"

        prompt = f"""You are a senior investment research analyst. Write a weekly digest for an AI infrastructure equity investor.

MACRO MARKETS THIS WEEK:
{macro_text}

SECTOR PERFORMANCE (ETFs):
{sector_text}

AI INFRASTRUCTURE WATCHLIST:
{ai_text}

EARNINGS NEXT 7 DAYS:
{earnings_text}

WHAT'S HOT OUTSIDE AI THIS WEEK:
{outside_text}

MACRO & ECONOMIC NEWS:
{macro_news_text}

Write a weekly digest covering these 5 sections:

1. MACRO PICTURE
How did global markets perform this week? What does it mean for risk appetite? (2-3 sentences)

2. AI INFRASTRUCTURE THIS WEEK
How did the core AI names perform? Any standout moves worth noting? (2-3 sentences)

3. WHAT'S HOT OUTSIDE AI
What sectors or themes moved meaningfully this week outside AI? Focus on real moves in liquid names — not micro-cap noise. What might this signal? (3-4 sentences)

4. EARNINGS WATCH NEXT WEEK
What's reporting and what to watch for. (2-3 sentences)

5. ONE THEME TO WATCH
One emerging idea or macro development that isn't consensus yet but is worth monitoring. Be specific and opinionated. (2-3 sentences)

Rules:
- Maximum 400 words total
- No markdown tables, no ### headers, no --- dividers
- Use • for bullet points
- Be direct and opinionated — no generic statements
- Format for Telegram using <b>bold</b> for emphasis
- ALWAYS respond in English"""

        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 800,
                "temperature": 0.4,
            }
        )

        digest = response.json()["choices"][0]["message"]["content"] if response.status_code == 200 else "Could not generate weekly digest."

        header = f"📊 <b>Weekly Digest — {datetime.now().strftime('%d %B %Y')}</b>\n\n"
        from src.tools.recommendations import get_recommendations
        picks = get_recommendations()
        send_telegram(header + digest + "\n\n" + picks)
        print(f"[{datetime.now().strftime('%H:%M')}] Weekly digest sent.")

    except Exception as e:
        print(f"Weekly digest error: {e}")
        from src.tools.notify import send_telegram
        send_telegram(f"❌ Weekly digest error: {str(e)[:200]}")


# ── Price Alerts ──────────────────────────────────────────────────────────────

def check_price_alerts():
    """Check for 8%+ moves — market hours only, once per ticker per day."""
    print(f"[{datetime.now().strftime('%H:%M')}] Checking price alerts...")

    open_now = _open_markets()
    if not open_now:
        print(f"[{datetime.now().strftime('%H:%M')}] All markets closed — skipping alerts.")
        return
    print(f"[{datetime.now().strftime('%H:%M')}] Open markets: {', '.join(open_now)}")

    try:
        from src.tools.prices import get_live_prices
        from src.tools.notify import send_telegram

        today = datetime.now().strftime("%Y-%m-%d")

        held = [t for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0]
        tickers_to_check = held if held else WATCHLIST
        prices = get_live_prices(tickers_to_check)

        alerts = []
        for ticker, data in prices.items():
            if not data:
                continue
            change = data.get("change_pct") or 0
            if abs(change) >= 8.0:
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


# ── On-Demand Alert Check ─────────────────────────────────────────────────────

def check_alerts_report() -> str:
    """On-demand version of price alerts — always returns a summary with top movers."""
    try:
        from src.tools.prices import get_live_prices
        today = datetime.now().strftime("%Y-%m-%d")
        held = [t for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0]
        tickers = held if held else WATCHLIST
        prices = get_live_prices(tickers)

        moves = []
        alerts = []
        for ticker, data in prices.items():
            if not data or data.get("change_pct") is None:
                continue
            change = data.get("change_pct") or 0
            moves.append((ticker, change, data.get("price")))
            if abs(change) >= 8.0:
                already = _alerted_today.get(ticker) == today
                direction = "📈" if change > 0 else "📉"
                tag = " <i>(already alerted)</i>" if already else ""
                alerts.append(f"{direction} <b>{fmt(ticker)}</b>: {change:+.2f}% (${data.get('price')}){tag}")
                if not already:
                    _alerted_today[ticker] = today

        moves.sort(key=lambda x: abs(x[1]), reverse=True)
        top = moves[:8]

        msg = f"🔍 <b>Alert Check — {len(tickers)} held positions</b>\n"
        msg += f"<i>{datetime.now().strftime('%d %b %Y, %H:%M')}</i>\n\n"

        if alerts:
            msg += "🚨 <b>8%+ Moves:</b>\n"
            msg += "\n".join(alerts) + "\n\n"

        msg += "<b>Top Movers Today:</b>\n"
        for ticker, change, price in top:
            direction = "📈" if change > 0 else "📉"
            msg += f"{direction} <b>{fmt(ticker)}</b>: {change:+.2f}% (${price})\n"

        if not alerts:
            msg += "\n<i>No positions above 8% threshold.</i>"

        return msg

    except Exception as e:
        return f"❌ Alert check error: {str(e)[:200]}"


# ── Scheduler ─────────────────────────────────────────────────────────────────

def run_scheduler():
    """Run the scheduler."""
    print("📅 Scheduler running...")
    print("• Morning briefing: 07:00 HKT Mon–Fri (23:00 UTC Sun–Thu)")
    print("• Weekly digest: 18:00 HKT Sunday (10:00 UTC Sunday)")
    print("• Price alerts: every 30 mins during market hours\n")

    # Morning briefing — 7am HKT = 23:00 UTC previous day
    schedule.every().sunday.at("23:00").do(send_morning_briefing)
    schedule.every().monday.at("23:00").do(send_morning_briefing)
    schedule.every().tuesday.at("23:00").do(send_morning_briefing)
    schedule.every().wednesday.at("23:00").do(send_morning_briefing)
    schedule.every().thursday.at("23:00").do(send_morning_briefing)

    # Weekly digest — 6pm HKT Sunday = 10:00 UTC Sunday
    schedule.every().sunday.at("10:00").do(send_weekly_digest)

    # Price alerts — every 30 mins during market hours
    schedule.every(30).minutes.do(check_price_alerts)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "price":
        print("Testing price alerts...")
        check_price_alerts()
    elif len(sys.argv) > 1 and sys.argv[1] == "digest":
        print("Testing weekly digest...")
        send_weekly_digest()
    else:
        print("Testing morning briefing...")
        send_morning_briefing()