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

# Tracks tickers that had a big drop and are being watched for stabilisation
# {ticker: {"drop_pct": float, "price_at_drop": float, "recovery_alerted": bool}}
_drop_watch: dict = {}

# Tracks seen news headlines to avoid duplicate pushes — keyed by title[:80]
_seen_headlines: set = set()

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


# ── Geopolitical Pulse ───────────────────────────────────────────────────────

def fetch_geopolitical_pulse() -> str:
    """
    Fetch geopolitical news and compress to 4 geography lines (1 sentence each).
    Public — used by both the morning briefing and the on-demand bot tool.
    """
    import requests as _req
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
    try:
        r = _req.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {TAVILY_API_KEY}", "Content-Type": "application/json"},
            json={
                "query": "geopolitical risk US China Taiwan Europe Middle East trade tariffs war today",
                "max_results": 8,
                "search_depth": "basic",
            },
            timeout=10,
        )
        articles = r.json().get("results", []) if r.status_code == 200 else []
        if not articles:
            return ""

        news_text = "\n".join(
            f"- {a.get('title', '')} — {a.get('content', '')[:150]}"
            for a in articles[:7]
        )

        prompt = (
            "From this news, write exactly 4 lines — one per geography.\n"
            "Format each line as: [Geography]: [1 sentence on the key risk/development and its market implication]\n"
            "Geographies to cover: US Policy, China/Taiwan, Europe, Middle East\n"
            "If nothing relevant for a geography, write: [Geography]: No significant development.\n"
            "Be specific. Max 25 words per line. No bullet points, no preamble.\n\n"
            f"NEWS:\n{news_text}"
        )

        r2 = _req.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 180,
                "temperature": 0.2,
            },
            timeout=15,
        )
        if r2.status_code == 200:
            return r2.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Geopolitical pulse error: {e}")
    return ""


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

        def _fetch_geopolitical_pulse():
            """1-sentence per geography geopolitical snapshot for the morning briefing."""
            return fetch_geopolitical_pulse()

        def _fetch_last_night_events():
            """Tavily search for earnings/conference results from last night."""
            held = [d.get("name", t) for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0]
            names_str = " ".join(held[:8])
            try:
                r = requests.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {os.getenv('TAVILY_API_KEY')}", "Content-Type": "application/json"},
                    json={
                        "query": f"earnings results conference call after hours {names_str} yesterday",
                        "max_results": 5,
                        "search_depth": "basic",
                    },
                    timeout=10,
                )
                return r.json().get("results", []) if r.status_code == 200 else []
            except Exception:
                return []

        # All held tickers for theme sweep
        held_tickers = [t for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0]

        with ThreadPoolExecutor(max_workers=6) as ex:
            f_prices = ex.submit(get_live_prices, BRIEFING_TICKERS)
            f_held_prices = ex.submit(get_live_prices, held_tickers)
            f_macro = ex.submit(get_macro_news)
            f_dates = ex.submit(get_earnings_dates, BRIEFING_TICKERS)
            f_events = ex.submit(_fetch_last_night_events)
            f_geo = ex.submit(_fetch_geopolitical_pulse)
            prices = f_prices.result()
            held_prices = f_held_prices.result()
            macro = f_macro.result()
            dates = f_dates.result()
            last_night = f_events.result()
            geo_pulse = f_geo.result()

        # Read-through: check if any trigger tickers moved big overnight
        from src.tools.read_through import get_morning_read_through
        read_through_text = get_morning_read_through(held_prices, held_tickers)

        # Build theme performance summary (non-AI themes highlighted)
        from src.tools.themes import get_tickers_by_theme, THEME_THESIS
        by_theme = get_tickers_by_theme(WATCHLIST_DATA)
        theme_lines = []
        for theme, tickers in sorted(by_theme.items()):
            moves = []
            for t in tickers:
                d = held_prices.get(t, {})
                if d and d.get("change_pct") is not None:
                    moves.append(d["change_pct"])
            if not moves:
                continue
            avg = sum(moves) / len(moves)
            icon = "▲" if avg > 0 else "▼"
            theme_lines.append(f"{icon} {theme}: avg {avg:+.1f}% ({len(moves)} positions)")

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

        events_text = ""
        if last_night:
            for a in last_night[:4]:
                events_text += f"- {a.get('title', '')}\n"
                if a.get("content"):
                    events_text += f"  {a['content'][:200]}\n"

        prompt = f"""You are an AI investment research assistant. Write a concise morning briefing for an AI infrastructure equity investor.

WATCHLIST PRICES TODAY:
{prices_text}

MACRO & AI NEWS:
{news_text}

UPCOMING EARNINGS (next 14 days):
{earnings_text}

EVENTS FROM LAST NIGHT (earnings calls, conferences, after-hours):
{events_text if events_text else "None found."}

INDUSTRY READ-THROUGH ALERTS (trigger tickers that moved 5%+ overnight):
{read_through_text if read_through_text else "None."}

GEOPOLITICAL PULSE (1 line per geography):
{geo_pulse if geo_pulse else "None."}

THEME PERFORMANCE ACROSS ALL THESES:
{chr(10).join(theme_lines) if theme_lines else "No theme data."}

Write a morning briefing covering:
1. LAST NIGHT'S EVENTS — if anything happened after hours yesterday (earnings, conferences, guidance), cover it FIRST: what happened, market reaction, what it means for the position. If industry read-through alerts are present, name the specific downstream holdings affected. Skip if nothing found.
2. GEOPOLITICAL PULSE — use the 4-line geo snapshot above. Flag any geography with active risk that could move markets today. Skip if all lines are "No significant development."
3. THEME SWEEP — one line per active theme: is the thesis on track, and what's driving it today? Cover ALL themes not just AI (Memory Cycle, Energy & Power, Banks & Rates, Space etc.)
4. Top movers — highlight the 2-3 biggest moves and briefly explain why (name the specific thesis driver, not just "market moved")
5. Earnings watch — flag any upcoming earnings and what to watch for
6. One thing to watch today

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
            },
            timeout=60,
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
        _drop_watch.clear()
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
            r = requests.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {os.getenv('TAVILY_API_KEY')}", "Content-Type": "application/json"},
                json={
                    "query": "stock market sector rotation theme investing week",
                    "max_results": 8,
                    "search_depth": "basic",
                },
                timeout=10
            )
            return r.json().get("results", []) if r.status_code == 200 else []

        def fetch_macro_news():
            r = requests.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {os.getenv('TAVILY_API_KEY')}", "Content-Type": "application/json"},
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
            },
            timeout=60,
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


# ── Thesis Verdict Helper ─────────────────────────────────────────────────────

def _thesis_verdict(ticker: str, change: float, thesis: str, price: float) -> str:
    """One-sentence verdict: thesis intact (buy dip) or thesis concern (wait)."""
    if not thesis:
        return ""
    try:
        import requests
        prompt = (
            f"{ticker} is down {abs(change):.1f}% today (now ${price:.2f}).\n"
            f"Investment thesis on file: {thesis[:300]}\n\n"
            f"Is this drop a buy-the-dip opportunity (thesis intact) or a signal the thesis may be impaired?\n"
            f"Reply in ONE short sentence starting with either '🟢 Thesis intact:' or '🔴 Thesis concern:'"
        )
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 80, "temperature": 0.2},
            timeout=15,
        )
        if r.status_code == 200:
            return "\n   " + r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return ""


def _check_recovery_alerts(prices: dict, held_data: dict):
    """
    After a big drop, watch for price stabilisation and push a 'ready to add' alert.
    Stabilised = currently between -3% and +3% (price found its floor).
    """
    if not _drop_watch:
        return
    from src.tools.notify import send_telegram
    to_remove = []
    msgs = []
    for ticker, watch in _drop_watch.items():
        if watch.get("recovery_alerted"):
            to_remove.append(ticker)
            continue
        d = prices.get(ticker, {})
        if not d or d.get("change_pct") is None:
            continue
        chg = d.get("change_pct") or 0
        if -3.0 <= chg <= 3.0:
            price = d.get("price")
            orig_drop = watch["drop_pct"]
            thesis = held_data.get(ticker, {}).get("thesis", "")
            verdict = "🟢 Thesis intact — this may be an add point." if thesis else ""
            msgs.append(
                f"📍 <b>{fmt(ticker)}</b> has stabilised after yesterday's {orig_drop:+.1f}% drop.\n"
                f"   Now: ${price} ({chg:+.2f}% today)\n"
                f"   {verdict}"
            )
            _drop_watch[ticker]["recovery_alerted"] = True

    if msgs:
        send_telegram(
            "🔔 <b>Price Stabilisation Alert</b>\n"
            f"<i>{datetime.now().strftime('%d %b %Y, %H:%M')}</i>\n\n"
            + "\n\n".join(msgs)
            + "\n\n<i>Reply 'portfolio advisor [ticker]' for add/size/trim analysis.</i>"
        )


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
        from concurrent.futures import ThreadPoolExecutor

        today = datetime.now().strftime("%Y-%m-%d")

        held_data = {t: d for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0}
        tickers_to_check = list(held_data.keys()) if held_data else WATCHLIST
        prices = get_live_prices(tickers_to_check)

        # Check for stabilisation of previously-dropped tickers
        _check_recovery_alerts(prices, held_data)

        alert_items = []  # (ticker, change, price, thesis)
        for ticker, data in prices.items():
            if not data:
                continue
            change = data.get("change_pct") or 0
            if abs(change) >= 8.0:
                if _alerted_today.get(ticker) == today:
                    continue
                thesis = held_data.get(ticker, {}).get("thesis", "")
                alert_items.append((ticker, change, data.get("price") or 0, thesis))
                _alerted_today[ticker] = today
                # Track drops for recovery watch
                if change < -8.0:
                    _drop_watch[ticker] = {
                        "drop_pct": change,
                        "price_at_drop": data.get("price") or 0,
                        "recovery_alerted": False,
                    }

        if alert_items:
            # Fetch thesis verdicts in parallel for drops
            drops = [(t, c, p, th) for t, c, p, th in alert_items if c < 0 and th]
            verdicts = {}
            if drops:
                with ThreadPoolExecutor(max_workers=4) as ex:
                    futures = {ex.submit(_thesis_verdict, t, c, th, p): t for t, c, p, th in drops}
                    for f, t in futures.items():
                        try:
                            verdicts[t] = f.result(timeout=20)
                        except Exception:
                            verdicts[t] = ""

            lines = []
            for ticker, change, price, thesis in alert_items:
                direction = "📈" if change > 0 else "📉"
                verdict = verdicts.get(ticker, "")
                lines.append(f"{direction} <b>{fmt(ticker)}</b>: {change:+.2f}% (${price}){verdict}")

            msg = "🚨 <b>Price Alert — 8%+ Move</b>\n\n"
            msg += "\n\n".join(lines)
            msg += "\n\n<i>Reply 'deep dive [ticker]' for full analysis.</i>"
            send_telegram(msg)
            print(f"[{datetime.now().strftime('%H:%M')}] Sent {len(alert_items)} price alerts.")
        else:
            print(f"[{datetime.now().strftime('%H:%M')}] No new alerts triggered.")

    except Exception as e:
        print(f"Price alert error: {e}")


# ── Portfolio Category Map ────────────────────────────────────────────────────

PORTFOLIO_CATEGORIES = {
    "Memory / Storage":     ["MU", "WDC", "SNDK", "DRAM"],
    "AI Infrastructure":    ["NVDA", "AMD", "TSM", "ASML", "ALAB", "CRDO", "ARM", "AVGO"],
    "Networking":           ["GLW", "CSCO", "NOK"],
    "Energy / Power":       ["GEV", "BE", "SEI", "OKLO", "CEG", "VST", "TLN"],
    "Banks / Financials":   ["JPM", "MS", "GS", "GE"],
    "Space":                ["RKLB", "ASTS", "SPCX"],
    "Software / Data":      ["PLTR", "APP", "MSTR", "GOOGL", "MSFT", "META"],
    "Defence / Industrials":["LMT"],
    "Quantum":              ["IONQ"],
    "Telecom / Optical":    ["LITE"],
    "Crypto":               ["BTC", "ETH", "SOL"],
}


def _categorise(tickers: list) -> dict:
    """Map a list of tickers to their categories. Uncategorised go to 'Other'."""
    result = {cat: [] for cat in PORTFOLIO_CATEGORIES}
    result["Other"] = []
    ticker_to_cat = {}
    for cat, members in PORTFOLIO_CATEGORIES.items():
        for t in members:
            ticker_to_cat[t] = cat
    for t in tickers:
        cat = ticker_to_cat.get(t, "Other")
        result[cat].append(t)
    return {k: v for k, v in result.items() if v}


# ── Post-Market Advice ────────────────────────────────────────────────────────

def _post_market_advice(summary_lines: list, held: dict) -> str:
    """Generate targeted buy/trim/hold advice based on today's close moves."""
    try:
        import requests
        DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

        # Build P&L context for held positions
        pnl_lines = []
        for t, d in held.items():
            shares = d.get("shares", 0)
            avg_cost = d.get("avg_cost", 0)
            name = d.get("name", t)
            if avg_cost:
                pnl_lines.append(f"{t} ({name}): avg cost ${avg_cost:.2f}, {shares} shares")

        prompt = (
            "You are a portfolio manager reviewing today's close. Give specific, actionable advice.\n\n"
            "TODAY'S CATEGORY MOVES:\n"
            + "\n".join(summary_lines) + "\n\n"
            "PORTFOLIO POSITIONS (avg costs):\n"
            + "\n".join(pnl_lines[:20]) + "\n\n"
            "Based on today's moves and the portfolio's average costs, give three sections:\n\n"
            "<b>🟢 Consider Adding</b> — names that dipped today and remain in thesis, good add point\n"
            "<b>🔴 Consider Trimming</b> — names up significantly where taking some profit makes sense\n"
            "<b>⚪ Hold / Watch</b> — key names to monitor tomorrow and why\n\n"
            "Rules: max 200 words, 2-3 names per section max, be specific about WHY (reference today's move or P&L), "
            "use <b>bold</b> for tickers. No generic advice."
        )

        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 350,
                "temperature": 0.3,
            },
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Post-market advice error: {e}")
    return ""


# ── Market Close Alerts ───────────────────────────────────────────────────────

def send_market_close_alert(market: str):
    """Send end-of-day portfolio summary grouped by category for the closing market."""
    print(f"[{datetime.now().strftime('%H:%M')}] Market close alert: {market}")
    try:
        import requests
        from src.tools.prices import get_live_prices
        from src.tools.notify import send_telegram
        DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

        # Determine which tickers to include based on market
        held = {t: d for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0}

        if market == "HK":
            tickers = [t for t in held if t.endswith(".HK") or t.endswith(".SS") or t.endswith(".SZ")]
        elif market == "EU":
            eu_names = ["ASML"]  # expand as needed
            tickers = [t for t in held if t in eu_names]
        else:  # US (default)
            tickers = [t for t in held if not any(t.endswith(s) for s in [".HK", ".SS", ".SZ", ".TW"])]

        if not tickers:
            print(f"No held positions for {market} close.")
            return

        prices = get_live_prices(tickers)
        categories = _categorise(tickers)

        # Build category blocks
        cat_blocks = []
        summary_lines = []  # for DeepSeek context
        total_winners = total_losers = 0

        for cat, cat_tickers in categories.items():
            moves = []
            for t in cat_tickers:
                d = prices.get(t, {})
                if not d or d.get("change_pct") is None:
                    continue
                chg = d.get("change_pct") or 0
                price = d.get("price")
                shares = held.get(t, {}).get("shares", 0)
                avg_cost = held.get(t, {}).get("avg_cost", 0)
                pnl = ((price - avg_cost) / avg_cost * 100) if avg_cost and price else 0
                moves.append((t, chg, price, pnl))
                if chg > 0:
                    total_winners += 1
                else:
                    total_losers += 1

            if not moves:
                continue

            moves.sort(key=lambda x: abs(x[1]), reverse=True)
            avg_chg = sum(m[1] for m in moves) / len(moves)
            direction = "📈" if avg_chg >= 0 else "📉"

            block = f"{direction} <b>{cat}</b> ({avg_chg:+.1f}% avg)\n"
            for t, chg, price, pnl in moves:
                icon = "▲" if chg > 0 else "▼"
                block += f"  {icon} <b>{fmt(t)}</b>: {chg:+.2f}% • P&L: {pnl:+.1f}%\n"
            cat_blocks.append(block)

            summary_lines.append(f"{cat}: avg {avg_chg:+.1f}% ({', '.join(f'{t} {c:+.1f}%' for t, c, _, _ in moves[:3])})")

        if not cat_blocks:
            return

        # DeepSeek synthesis
        synthesis = ""
        try:
            r = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [{
                        "role": "user",
                        "content": (
                            f"Portfolio {market} market close summary. Be direct, 2-3 sentences max.\n\n"
                            f"Category performance:\n" + "\n".join(summary_lines) +
                            f"\n\nWhat does today's pattern mean? Any category or stock to watch tomorrow? "
                            f"Format for Telegram using <b>bold</b> for tickers/themes."
                        )
                    }],
                    "max_tokens": 150,
                    "temperature": 0.3,
                },
                timeout=30,
            )
            if r.status_code == 200:
                synthesis = "\n" + r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"Synthesis error: {e}")

        msg = (
            f"🔔 <b>{market} Close — Portfolio Summary</b>\n"
            f"<i>{datetime.now().strftime('%d %b %Y, %H:%M')}</i>\n"
            f"<i>{total_winners} up · {total_losers} down</i>\n\n"
            + "\n".join(cat_blocks)
            + synthesis
        )

        # For US close: append buy/trim/hold advice based on today's moves
        if market == "US":
            advice = _post_market_advice(summary_lines, held)
            if advice:
                msg += f"\n\n{advice}"

        send_telegram(msg)
        print(f"[{datetime.now().strftime('%H:%M')}] {market} close alert sent.")

    except Exception as e:
        print(f"Market close alert error: {e}")


# ── Breaking News Alerts ──────────────────────────────────────────────────────

def check_breaking_news():
    """
    Push genuinely market-moving news to Telegram — runs every 2 hours, 7am-11pm HKT.
    2 Tavily searches: held company news + macro/geopolitical.
    DeepSeek filters for only high-impact headlines (score 8+/10).
    Deduplicates via _seen_headlines set.
    """
    # Only run 7am–11pm HKT (23:00–15:00 UTC)
    now_utc = datetime.now(timezone.utc)
    utc_mins = now_utc.hour * 60 + now_utc.minute
    # 23:00–23:59 UTC = after midnight UTC but counts as morning HKT
    # 00:00–15:00 UTC = 8am–11pm HKT
    in_window = (utc_mins >= 23 * 60) or (utc_mins <= 15 * 60)
    if not in_window:
        print(f"[{datetime.now().strftime('%H:%M')}] Breaking news: outside HKT window, skipping.")
        return

    print(f"[{datetime.now().strftime('%H:%M')}] Checking breaking news...")
    try:
        import requests
        DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
        TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

        # Build company name list from top held positions
        held = [(t, d) for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0]
        top_held_names = " ".join(
            d.get("name", t) for t, d in held[:8]
        )

        all_articles = []

        # Search 1: held company breaking news
        try:
            r1 = requests.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {TAVILY_API_KEY}", "Content-Type": "application/json"},
                json={"query": f"breaking news {top_held_names} today", "max_results": 8, "search_depth": "basic"},
                timeout=10,
            )
            if r1.status_code == 200:
                all_articles += r1.json().get("results", [])
        except Exception as e:
            print(f"News search 1 error: {e}")

        # Search 2: macro / geopolitical breaking news
        try:
            r2 = requests.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {TAVILY_API_KEY}", "Content-Type": "application/json"},
                json={
                    "query": "breaking news market moving geopolitical trade policy interest rates today",
                    "max_results": 8,
                    "search_depth": "basic",
                },
                timeout=10,
            )
            if r2.status_code == 200:
                all_articles += r2.json().get("results", [])
        except Exception as e:
            print(f"News search 2 error: {e}")

        if not all_articles:
            print(f"[{datetime.now().strftime('%H:%M')}] Breaking news: no articles returned.")
            return

        # Dedup against already-seen headlines
        new_articles = []
        for a in all_articles:
            key = a.get("title", "")[:80]
            if key and key not in _seen_headlines:
                new_articles.append(a)
                _seen_headlines.add(key)

        if not new_articles:
            print(f"[{datetime.now().strftime('%H:%M')}] Breaking news: all {len(all_articles)} headlines already seen.")
            return

        # Ask DeepSeek to filter for genuinely market-moving news
        headlines_text = "\n".join(
            f"{i+1}. {a.get('title', '')} — {a.get('content', '')[:150]}"
            for i, a in enumerate(new_articles)
        )

        filter_prompt = f"""You are a senior portfolio manager's news filter.
Review these headlines and identify ONLY those that are genuinely market-moving for an AI infrastructure equity portfolio
(holdings include: NVDA, TSM, MU, ASML, AMD, GEV, NVDA, GLW, BE, INTC, GS, JPM, banks, energy, memory/storage).

Score each headline 1-10 for market impact. Return ONLY headlines scoring 8 or above.

For each qualifying headline, reply in this exact format:
📰 [headline title]
<i>[1 sentence: why this matters for the portfolio]</i>

If nothing scores 8+, reply exactly: NO_BREAKING_NEWS

Headlines to review:
{headlines_text}"""

        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": filter_prompt}],
                "max_tokens": 400,
                "temperature": 0.2,
            },
            timeout=30,
        )

        if r.status_code != 200:
            print(f"DeepSeek filter error: {r.status_code}")
            return

        filtered = r.json()["choices"][0]["message"]["content"].strip()

        if "NO_BREAKING_NEWS" in filtered:
            print(f"[{datetime.now().strftime('%H:%M')}] Breaking news: nothing market-moving filtered through.")
            return

        from src.tools.notify import send_telegram
        msg = (
            f"🚨 <b>Breaking News Alert</b>\n"
            f"<i>{datetime.now().strftime('%d %b %Y, %H:%M HKT')}</i>\n\n"
            f"{filtered}"
        )
        send_telegram(msg)
        print(f"[{datetime.now().strftime('%H:%M')}] Breaking news alert sent.")

    except Exception as e:
        print(f"Breaking news check error: {e}")


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

    # Breaking news — every 2 hours, 7am-11pm HKT
    schedule.every(2).hours.do(check_breaking_news)

    # Market close alerts (UTC times)
    schedule.every().day.at("08:05").do(lambda: send_market_close_alert("HK"))   # HK close 16:00 HKT
    schedule.every().day.at("15:35").do(lambda: send_market_close_alert("EU"))   # EU close 23:35 HKT
    schedule.every().day.at("20:05").do(lambda: send_market_close_alert("US"))   # US close 04:05 HKT+1

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