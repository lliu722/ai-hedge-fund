import os
import schedule
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from src.tools.notion_holdings import get_holdings_cached, FALLBACK_WATCHLIST

load_dotenv()
from src.tools.llm import call_deepseek, tavily_search


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

# Dedup cache for custom alerts — key: "TICKER:direction:YYYY-MM-DD"
_custom_alerted: dict = {}

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


# mirrors fmt() in telegram_bot.py — intentional, each uses its own loaded WATCHLIST_DATA
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
    try:
        articles = tavily_search(
            "geopolitical risk US China Taiwan Europe Middle East trade tariffs war today",
            max_results=8,
            search_depth="basic",
        )
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

        return call_deepseek(prompt, max_tokens=180, temperature=0.2, timeout=15)
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

        def _fetch_geopolitical_pulse():
            """1-sentence per geography geopolitical snapshot for the morning briefing."""
            return fetch_geopolitical_pulse()

        def _fetch_last_night_events():
            """Tavily search for earnings/conference results from last night."""
            held = [d.get("name", t) for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0]
            names_str = " ".join(held[:8])
            try:
                return tavily_search(
                    f"earnings results conference call after hours {names_str} yesterday",
                    max_results=5,
                    search_depth="basic",
                )
            except Exception:
                return []

        # Split Notion holdings into portfolio (held) and watchlist (monitoring only)
        portfolio_data = {t: d for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0}
        watchlist_data = {t: d for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) == 0}
        held_tickers    = list(portfolio_data.keys())
        all_tickers     = list(WATCHLIST_DATA.keys())

        with ThreadPoolExecutor(max_workers=5) as ex:
            f_prices  = ex.submit(get_live_prices, all_tickers)
            f_macro   = ex.submit(get_macro_news)
            f_dates   = ex.submit(get_earnings_dates, held_tickers)
            f_events  = ex.submit(_fetch_last_night_events)
            f_geo     = ex.submit(_fetch_geopolitical_pulse)
            prices      = f_prices.result()
            held_prices = {t: prices[t] for t in held_tickers if t in prices}
            macro       = f_macro.result()
            dates       = f_dates.result()
            last_night  = f_events.result()
            geo_pulse   = f_geo.result()

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

        # prices_text for DeepSeek prompt = held positions only
        prices_text = ""
        for t in held_tickers:
            d = prices.get(t)
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

        briefing = call_deepseek(prompt, max_tokens=600, temperature=0.3, timeout=60) or "Could not generate AI briefing."

        header = f"🌅 <b>Morning Briefing — {datetime.now().strftime('%A %d %B %Y')}</b>\n\n"

        # Portfolio section — all held positions, sorted by biggest mover first
        port_rows = []
        for t in held_tickers:
            d = prices.get(t)
            if not d:
                continue
            chg = d.get("change_pct") or 0
            price = d.get("price")
            direction = "📈" if chg > 0 else "📉"
            line = f"{direction} <b>{fmt(t)}</b>: ${price} ({chg:+.2f}%)"
            avg_cost = portfolio_data.get(t, {}).get("avg_cost")
            if avg_cost and price:
                pnl = (price - avg_cost) / avg_cost * 100
                line += f" · <i>{pnl:+.1f}%</i>"
            port_rows.append((abs(chg), line))
        port_rows.sort(key=lambda x: x[0], reverse=True)
        price_block = f"<b>📊 Portfolio ({len(portfolio_data)} positions):</b>\n"
        price_block += "\n".join(row for _, row in port_rows) + "\n"

        # Watchlist section — only movers ≥2%, sorted by abs move, capped at 15
        wl_rows = []
        for t in watchlist_data:
            d = prices.get(t)
            if not d:
                continue
            chg = d.get("change_pct") or 0
            if abs(chg) >= 2.0:
                direction = "📈" if chg > 0 else "📉"
                wl_rows.append((abs(chg), f"{direction} <b>{fmt(t)}</b>: ${d.get('price')} ({chg:+.2f}%)"))
        wl_rows.sort(key=lambda x: x[0], reverse=True)
        if wl_rows:
            price_block += f"\n<b>👁 Watchlist movers (≥2%):</b>\n"
            price_block += "\n".join(row for _, row in wl_rows[:15]) + "\n"

        send_telegram(header + price_block + "\n" + briefing)
        print(f"[{datetime.now().strftime('%H:%M')}] Morning briefing sent.")

        _alerted_today.clear()
        _drop_watch.clear()
        print(f"[{datetime.now().strftime('%H:%M')}] Daily alert cache cleared.")

    except Exception as e:
        print(f"Morning briefing error: {e}")
        from src.tools.notify import send_telegram
        send_telegram(f"❌ Morning briefing error: {str(e)[:200]}")


# ── Weekly P&L Block ─────────────────────────────────────────────────────────

def _compute_portfolio_pnl() -> str:
    """
    Build the weekly P&L block:
    • Unrealised P&L — all held positions vs average cost (total + per category)
    • Realised P&L — journal entries closed in the last 7 days
    """
    try:
        from src.tools.prices import get_live_prices
        from src.tools.notion_holdings import get_journal_entries
        from datetime import timedelta

        held = {t: d for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0}
        if not held:
            return ""

        prices = get_live_prices(list(held.keys()))

        # ── Unrealised ────────────────────────────────────────────────────────
        total_value = total_cost = 0.0
        winners = losers = 0
        cat_pnl: dict = {}  # category → {value, cost}

        rows = []
        for t, d in held.items():
            price = (prices.get(t) or {}).get("price") or 0
            shares = d.get("shares") or 0
            avg = d.get("avg_cost") or 0
            value = shares * price
            cost = shares * avg
            pnl_dollar = value - cost
            pnl_pct = (pnl_dollar / cost * 100) if cost else 0
            total_value += value
            total_cost += cost
            (winners if pnl_pct >= 0 else losers).__class__  # just counting
            if pnl_pct >= 0:
                winners += 1
            else:
                losers += 1

            # Category bucket
            sector = d.get("sector", "Other")
            if sector not in cat_pnl:
                cat_pnl[sector] = {"value": 0.0, "cost": 0.0}
            cat_pnl[sector]["value"] += value
            cat_pnl[sector]["cost"] += cost

            rows.append((t, value, pnl_dollar, pnl_pct))

        rows.sort(key=lambda x: x[2])  # worst to best

        total_pnl = total_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"

        msg = f"💼 <b>Portfolio P&L Snapshot</b>\n"
        msg += f"{pnl_emoji} <b>Total: ${total_value:,.0f}</b> · Unrealised P&L <b>${total_pnl:+,.0f} ({total_pnl_pct:+.1f}%)</b>\n"
        msg += f"<i>{winners} winners · {losers} losers across {len(rows)} positions</i>\n\n"

        # Top 3 winners and losers
        best  = [r for r in rows if r[2] >= 0][-3:][::-1]
        worst = rows[:3]
        if best:
            msg += "<b>Top winners:</b>\n"
            for t, val, dpnl, ppnl in best:
                msg += f"  🟢 <b>{fmt(t)}</b>: ${dpnl:+,.0f} ({ppnl:+.1f}%) · ${val:,.0f}\n"
        if worst:
            msg += "<b>Biggest drags:</b>\n"
            for t, val, dpnl, ppnl in worst:
                msg += f"  🔴 <b>{fmt(t)}</b>: ${dpnl:+,.0f} ({ppnl:+.1f}%) · ${val:,.0f}\n"

        # Category breakdown
        cat_sorted = sorted(cat_pnl.items(), key=lambda x: x[1]["value"] - x[1]["cost"], reverse=True)
        msg += "\n<b>By sector:</b>\n"
        for cat, cv in cat_sorted:
            cpnl = cv["value"] - cv["cost"]
            cpct = (cpnl / cv["cost"] * 100) if cv["cost"] else 0
            emoji = "🟢" if cpnl >= 0 else "🔴"
            msg += f"  {emoji} {cat}: ${cpnl:+,.0f} ({cpct:+.1f}%)\n"

        # ── Realised (journal, last 7 days) ──────────────────────────────────
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        entries = get_journal_entries(status="Closed", limit=50)
        realised = []
        for page in entries:
            props = page.get("properties", {})
            exit_date = (props.get("Exit Date") or {}).get("date", {})
            exit_date_str = (exit_date or {}).get("start", "") if exit_date else ""
            if exit_date_str < cutoff:
                continue
            ticker_rt = props.get("Ticker", {}).get("rich_text", [])
            ticker = ticker_rt[0]["plain_text"] if ticker_rt else "?"
            pnl = props.get("Realized PnL Pct", {}).get("number")
            shares = props.get("Shares", {}).get("number") or 0
            entry_p = props.get("Entry Price", {}).get("number") or 0
            exit_p = props.get("Exit Price", {}).get("number") or 0
            dollar_pnl = shares * (exit_p - entry_p) if entry_p else 0
            if pnl is not None:
                realised.append((ticker, pnl, dollar_pnl, exit_date_str))

        if realised:
            total_realised = sum(r[2] for r in realised)
            realised_emoji = "🟢" if total_realised >= 0 else "🔴"
            msg += f"\n<b>Realised this week:</b> {realised_emoji} ${total_realised:+,.0f}\n"
            for t, ppnl, dpnl, dt in sorted(realised, key=lambda x: x[0]):
                emoji = "🟢" if ppnl >= 0 else "🔴"
                msg += f"  {emoji} <b>{t}</b>: ${dpnl:+,.0f} ({ppnl:+.1f}%) — closed {dt}\n"
        else:
            msg += "\n<i>No closed trades this week.</i>\n"

        return msg

    except Exception as e:
        return f"<i>P&L block unavailable: {str(e)[:80]}</i>\n"


# ── Weekly Macro Digest ───────────────────────────────────────────────────────

def send_weekly_digest():
    """Build and send the Sunday weekly macro + thematic digest."""
    print(f"[{datetime.now().strftime('%H:%M')}] Running weekly digest...")
    try:
        from src.tools.prices import get_live_prices
        from src.tools.earnings_calendar import get_earnings_dates
        from src.tools.notify import send_telegram

        # Fetch macro indices, sector ETFs, AI watchlist, news in parallel
        def fetch_outside_news():
            return tavily_search(
                "stock market sector rotation theme investing week",
                max_results=8,
                search_depth="basic",
            )

        def fetch_macro_news():
            return tavily_search(
                "Fed interest rates CPI jobs inflation macro economic outlook week",
                max_results=5,
                search_depth="basic",
            )

        macro_tickers = list(MACRO_TICKERS.keys())
        sector_tickers = list(SECTOR_ETFS.keys())

        from src.tools.momentum import get_weekly_momentum_digest

        def compute_theme_health():
            """Score each theme 0–10 on weekly momentum + breadth."""
            try:
                from src.tools.themes import THESIS_MAP
                # Group held tickers by theme
                theme_tickers: dict[str, list] = {}
                for t, d in WATCHLIST_DATA.items():
                    if (d.get("shares") or 0) <= 0:
                        continue
                    theme = THESIS_MAP.get(t, "Other")
                    theme_tickers.setdefault(theme, []).append(t)
                if not theme_tickers:
                    return ""
                # Get prices for all held tickers
                all_held = [t for tlist in theme_tickers.values() for t in tlist]
                prices_all = get_live_prices(all_held)
                scores = {}
                for theme, tickers_in_theme in theme_tickers.items():
                    if len(tickers_in_theme) < 2:
                        continue
                    moves = [prices_all.get(t, {}).get("change_pct") or 0 for t in tickers_in_theme]
                    avg_move = sum(moves) / len(moves)
                    breadth = sum(1 for m in moves if m > 0) / len(moves)  # % positive
                    # Score 0–10: avg move contributes 60%, breadth 40%
                    move_score   = min(10, max(0, 5 + avg_move * 0.6))
                    breadth_score = breadth * 10
                    score = round(move_score * 0.6 + breadth_score * 0.4, 1)
                    scores[theme] = {
                        "score": score, "avg_move": avg_move,
                        "breadth": breadth, "n": len(tickers_in_theme)
                    }
                if not scores:
                    return ""
                lines = ["<b>🧭 Theme Health Scores (this week)</b>"]
                for theme, s in sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True):
                    bar = "█" * int(s["score"] / 2) + "░" * (5 - int(s["score"] / 2))
                    emoji = "🟢" if s["score"] >= 7 else ("🟡" if s["score"] >= 4 else "🔴")
                    lines.append(
                        f"{emoji} <b>{theme}</b> {bar} {s['score']}/10 "
                        f"({s['avg_move']:+.1f}% avg · {int(s['breadth']*100)}% positive · {s['n']} names)"
                    )
                return "\n".join(lines)
            except Exception as e:
                return f"Theme health error: {e}"

        with ThreadPoolExecutor(max_workers=9) as ex:
            f_macro_prices  = ex.submit(get_live_prices, macro_tickers)
            f_sector_prices = ex.submit(get_live_prices, sector_tickers)
            f_ai_prices     = ex.submit(get_live_prices, BRIEFING_TICKERS)
            f_outside_news  = ex.submit(fetch_outside_news)
            f_macro_news    = ex.submit(fetch_macro_news)
            f_earnings      = ex.submit(get_earnings_dates, BRIEFING_TICKERS)
            f_momentum      = ex.submit(get_weekly_momentum_digest)
            f_pnl           = ex.submit(_compute_portfolio_pnl)
            f_theme_health  = ex.submit(compute_theme_health)

            macro_prices    = f_macro_prices.result()
            sector_prices   = f_sector_prices.result()
            ai_prices       = f_ai_prices.result()
            outside_news    = f_outside_news.result()
            macro_news      = f_macro_news.result()
            earnings        = f_earnings.result()
            momentum_digest = f_momentum.result()
            pnl_block       = f_pnl.result()
            theme_health    = f_theme_health.result()

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

DEVELOPER SIGNAL (GitHub commit velocity + arXiv paper volume this week):
{momentum_digest}

Write a weekly digest covering these 6 sections:

1. MACRO PICTURE
How did global markets perform this week? What does it mean for risk appetite? (2-3 sentences)

2. AI INFRASTRUCTURE THIS WEEK
How did the core AI names perform? Any standout moves worth noting? (2-3 sentences)

3. WHAT'S HOT OUTSIDE AI
What sectors or themes moved meaningfully this week outside AI? Focus on real moves in liquid names — not micro-cap noise. What might this signal? (3-4 sentences)

4. EARNINGS WATCH NEXT WEEK
What's reporting and what to watch for. (2-3 sentences)

5. DEVELOPER SIGNAL
Use the GitHub + arXiv momentum data below. Which theme has the most accelerating developer activity this week? What does it signal for that thesis 6-12 months out? (2-3 sentences)

6. ONE THEME TO WATCH
One emerging idea or macro development that isn't consensus yet but is worth monitoring. Be specific and opinionated. (2-3 sentences)

Rules:
- Maximum 500 words total
- No markdown tables, no ### headers, no --- dividers
- Use • for bullet points
- Be direct and opinionated — no generic statements
- Format for Telegram using <b>bold</b> for emphasis
- ALWAYS respond in English"""

        digest = call_deepseek(prompt, max_tokens=1000, temperature=0.4, timeout=60) or "Could not generate weekly digest."

        header = f"📊 <b>Weekly Digest — {datetime.now().strftime('%d %B %Y')}</b>\n\n"
        if theme_health:
            header += theme_health + "\n\n"
        from src.tools.recommendations import get_recommendations
        picks = get_recommendations()
        send_telegram(header + pnl_block + "\n" + digest + "\n\n" + picks)
        print(f"[{datetime.now().strftime('%H:%M')}] Weekly digest sent.")

    except Exception as e:
        print(f"Weekly digest error: {e}")
        from src.tools.notify import send_telegram
        send_telegram(f"❌ Weekly digest error: {str(e)[:200]}")


# ── Thesis Verdict Helper ─────────────────────────────────────────────────────

def _thesis_verdict(ticker: str, change: float, thesis: str, price: float) -> str:
    """One-sentence verdict: thesis intact (buy dip) or thesis concern (wait).
    If no thesis stored, fetches context from Tavily and generates verdict from public info."""
    try:
        if thesis:
            context = f"Investment thesis on file: {thesis[:300]}"
        else:
            # No thesis saved — fetch recent news to form a verdict
            results = tavily_search(f"{ticker} stock drop news today reason", max_results=3, timeout=8)
            if results:
                context = "Recent news:\n" + "\n".join(
                    f"- {r.get('title', '')} {r.get('content', '')[:150]}" for r in results
                )
            else:
                context = "No thesis or news available — assess based on ticker name and drop size only."

        prompt = (
            f"{ticker} is down {abs(change):.1f}% today (now ${price:.2f}).\n"
            f"{context}\n\n"
            f"Is this drop a buy-the-dip opportunity (thesis intact) or a signal the thesis may be impaired?\n"
            f"Reply in ONE short sentence starting with either '🟢 Thesis intact:' or '🔴 Thesis concern:'"
        )
        result = call_deepseek(prompt, max_tokens=80, temperature=0.2, timeout=15)
        if result and not result.startswith("❌"):
            return "\n   " + result
    except Exception as e:
        print(f"[scheduler:thesis_verdict] {e}")
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

        # ── Custom threshold alerts ───────────────────────────────────────────
        try:
            from src.tools.alert_config import check_custom_alerts, check_watchlist_targets
            custom_hits = check_custom_alerts(prices, _custom_alerted, today)
            if custom_hits:
                custom_lines = []
                for t, change, price, threshold, direction in custom_hits:
                    arrow = "📈" if change > 0 else "📉"
                    custom_lines.append(f"{arrow} <b>{fmt(t)}</b>: {change:+.2f}% (${price}) — your {threshold:.1f}% {direction} alert")
                send_telegram("🔔 <b>Custom Alert Triggered</b>\n\n" + "\n".join(custom_lines))
            # Watchlist price targets
            wl_hits = check_watchlist_targets(prices, _custom_alerted, today)
            if wl_hits:
                wl_lines = []
                for t, price, target, direction, note in wl_hits:
                    arrow = "📉" if direction == "below" else "📈"
                    note_str = f"\n  <i>{note}</i>" if note else ""
                    wl_lines.append(f"{arrow} <b>{fmt(t)}</b> hit ${price:.2f} (target: {direction} ${target:.2f}){note_str}")
                send_telegram("🎯 <b>Watchlist Target Hit</b>\n\n" + "\n".join(wl_lines) + "\n\n<i>Time to size in?</i>")
        except Exception as ce:
            print(f"Custom alert check error: {ce}")

        if alert_items:
            # Fetch thesis verdicts in parallel for drops
            drops = [(t, c, p, th) for t, c, p, th in alert_items if c < 0]
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

        result = call_deepseek(prompt, max_tokens=350, temperature=0.3, timeout=30)
        if result and not result.startswith("❌"):
            return result
    except Exception as e:
        print(f"Post-market advice error: {e}")
    return ""


# ── Market Close Alerts ───────────────────────────────────────────────────────

def send_market_close_alert(market: str):
    """Send end-of-day portfolio summary grouped by category for the closing market."""
    print(f"[{datetime.now().strftime('%H:%M')}] Market close alert: {market}")
    try:
        from src.tools.prices import get_live_prices
        from src.tools.notify import send_telegram

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
            synth_prompt = (
                f"Portfolio {market} market close summary. Be direct, 2-3 sentences max.\n\n"
                f"Category performance:\n" + "\n".join(summary_lines) +
                f"\n\nWhat does today's pattern mean? Any category or stock to watch tomorrow? "
                f"Format for Telegram using <b>bold</b> for tickers/themes."
            )
            synth_result = call_deepseek(synth_prompt, max_tokens=150, temperature=0.3, timeout=30)
            if synth_result and not synth_result.startswith("❌"):
                synthesis = "\n" + synth_result
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
        # Build company name list from top held positions
        held = [(t, d) for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0]
        top_held_names = " ".join(
            d.get("name", t) for t, d in held[:8]
        )

        all_articles = []

        # Search 1: held company breaking news
        try:
            all_articles += tavily_search(
                f"breaking news {top_held_names} today",
                max_results=8,
                search_depth="basic",
            )
        except Exception as e:
            print(f"News search 1 error: {e}")

        # Search 2: macro / geopolitical breaking news
        try:
            all_articles += tavily_search(
                "breaking news market moving geopolitical trade policy interest rates today",
                max_results=8,
                search_depth="basic",
            )
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

        filtered = call_deepseek(filter_prompt, max_tokens=400, temperature=0.2, timeout=30)
        if not filtered or filtered.startswith("❌"):
            print(f"DeepSeek filter error: {filtered}")
            return

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


# ── Market Open Alerts ────────────────────────────────────────────────────────

def send_market_open_alert(market: str):
    """
    Fire just before market open with a tight, action-focused brief:
    - Your held positions + pre-market % move (US) or prior-session move (HK)
    - Today's earnings calls for names you hold or watch
    - Economic calendar (Tavily) + overnight macro headline
    No DeepSeek synthesis — raw data is faster and more useful at open time.
    """
    print(f"[{datetime.now().strftime('%H:%M')}] Market open alert: {market}")
    try:
        from src.tools.prices import get_live_prices, normalize_ticker
        from src.tools.notify import send_telegram
        import yfinance as yf

        held = {t: d for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0}

        # ── Segment tickers by market ──────────────────────────────────────────
        if market == "HK":
            mkt_tickers = [t for t in held if t.endswith(".HK") or t.endswith(".SS") or t.endswith(".SZ")]
            mkt_label = "🇭🇰 HK Open"
            mkt_time  = "9:30am HKT"
        else:  # US
            mkt_tickers = [t for t in held if not any(t.endswith(s) for s in [".HK", ".SS", ".SZ", ".TW"])]
            mkt_label = "🇺🇸 US Open"
            mkt_time  = "9:30am ET"

        if not mkt_tickers:
            print(f"No held positions for {market} open alert.")
            return

        # ── Parallel fetches ───────────────────────────────────────────────────
        def fetch_pre_market_moves():
            """Pre-market price vs previous close for US tickers via yfinance fast_info.
            Returns only tickers where pre_market_price is actually available."""
            moves = {}
            if market != "US":
                return moves
            for ticker in mkt_tickers[:15]:
                try:
                    yfk = normalize_ticker(ticker)
                    if not yfk or yfk.startswith("CRYPTO:"):
                        continue
                    fi = yf.Ticker(yfk).fast_info
                    pre  = getattr(fi, "pre_market_price", None)
                    prev = getattr(fi, "previous_close", None)
                    # Only record if yfinance actually returned a pre-market price
                    if pre and prev and prev > 0 and pre != prev:
                        pct = (pre - prev) / prev * 100
                        moves[ticker] = {"pre_price": pre, "prev_close": prev, "pre_pct": pct}
                except Exception:
                    pass
            return moves

        def fetch_regular_prices():
            return get_live_prices(mkt_tickers)

        def fetch_earnings_today():
            """Use earnings_calendar.py to get tickers reporting today — no Tavily."""
            try:
                from src.tools.earnings_calendar import get_earnings_dates
                all_tickers = list(WATCHLIST_DATA.keys())
                dates = get_earnings_dates(all_tickers)
                today = datetime.now().strftime("%Y-%m-%d")
                reporting = []
                for t, info in dates.items():
                    d = info.get("date", "")
                    when = info.get("when", "")
                    if d and d.startswith(today):
                        label = fmt(t)
                        timing = f" ({when})" if when else ""
                        reporting.append(f"{label}{timing}")
                return reporting
            except Exception as e:
                print(f"[open_alert] earnings fetch error: {e}")
                return []

        def fetch_market_news():
            """Actual news for our held names + macro — specific query with today's date."""
            today_str = datetime.now().strftime("%B %d %Y")
            top_names = " ".join(
                d.get("name", t) for t, d in list(held.items())[:6]
            )
            if market == "HK":
                query = f"Hong Kong stock market open {today_str} China news"
            else:
                query = f"stock market pre-market {today_str} {top_names}"
            results = tavily_search(query, max_results=6, search_depth="basic")
            # Filter out generic calendar/schedule pages — only keep actual news
            junk_keywords = ("calendar", "schedule", "investing.com", "tradingview",
                             "barchart", "yahoo finance", "r/stock")
            return [
                r for r in results
                if not any(k in r.get("title", "").lower() for k in junk_keywords)
            ][:4]

        def fetch_economic_events():
            """Specific economic events due today — date-anchored query."""
            if market == "HK":
                return []  # HK open is 9:20am — econ data rarely at that time
            today_str = datetime.now().strftime("%B %d %Y")
            results = tavily_search(
                f"US economic data release {today_str} CPI jobs GDP Fed",
                max_results=4, search_depth="basic"
            )
            junk_keywords = ("calendar", "schedule", "indicator release", "release schedule",
                             "bureau of economic", "guggenheim", "bea.gov")
            return [
                r for r in results
                if not any(k in r.get("title", "").lower() for k in junk_keywords)
                and len(r.get("content", "")) > 100  # must have actual content
            ][:3]

        with ThreadPoolExecutor(max_workers=4) as ex:
            f_pre    = ex.submit(fetch_pre_market_moves)
            f_prices = ex.submit(fetch_regular_prices)
            f_earn   = ex.submit(fetch_earnings_today)
            f_news   = ex.submit(fetch_market_news)
            f_econ   = ex.submit(fetch_economic_events)

            pre_moves = f_pre.result(timeout=20)
            prices    = f_prices.result(timeout=20)
            earnings_today = f_earn.result(timeout=15)
            market_news    = f_news.result(timeout=15)
            econ_events    = f_econ.result(timeout=15)

        pre_market_available = len(pre_moves) > 0

        # ── Build message ──────────────────────────────────────────────────────
        now_str = datetime.now().strftime("%d %b %Y, %H:%M")
        msg = f"🔔 <b>{mkt_label}</b> — {mkt_time}\n<i>{now_str} HKT</i>\n\n"

        # Section 1: positions
        if market == "US" and pre_market_available:
            msg += f"<b>📊 Pre-Market Movers</b> <i>(vs prev close)</i>\n"
        elif market == "US":
            msg += f"<b>📊 Your US Positions</b> <i>(last close · pre-mkt data unavailable)</i>\n"
        else:
            msg += f"<b>📊 Your HK Positions</b> <i>(last close)</i>\n"

        position_lines = []
        for ticker in mkt_tickers:
            d = held.get(ticker, {})
            avg_cost = d.get("avg_cost", 0)

            if market == "US" and ticker in pre_moves:
                # Real pre-market data
                pm = pre_moves[ticker]
                pct = pm["pre_pct"]
                icon = "▲" if pct > 0 else "▼"
                emoji = "🟢" if pct > 0 else "🔴"
                line = f"{emoji} <b>{ticker}</b> {icon}{abs(pct):.1f}% pre-mkt (${pm['pre_price']:.2f})"
                if abs(pct) >= 3.0 and pm["pre_price"] > 0:
                    sh5  = int(5000  / pm["pre_price"])
                    sh10 = int(10000 / pm["pre_price"])
                    action = "add" if pct < 0 else "trim"
                    line += f"\n  💡 {action}: $5k={sh5}sh · $10k={sh10}sh"
                position_lines.append((abs(pct), line))
            else:
                # Last close — show price + cost P&L only, NO session % (would be misleading)
                p = prices.get(ticker, {})
                price = p.get("price")
                if price and avg_cost:
                    pnl = (price - avg_cost) / avg_cost * 100
                    emoji = "🟢" if pnl > 0 else "🔴"
                    position_lines.append((0, f"{emoji} <b>{ticker}</b> ${price:.2f} · cost P&L {pnl:+.1f}%"))
                elif price:
                    position_lines.append((0, f"⚪ <b>{ticker}</b> ${price:.2f}"))

        # Sort: pre-market movers first (by abs move), then rest alphabetically
        position_lines.sort(key=lambda x: x[0], reverse=True)
        if position_lines:
            msg += "\n".join(line for _, line in position_lines[:12]) + "\n"
        else:
            msg += "<i>No price data available yet</i>\n"

        # Section 2: earnings today — from our own calendar, not Tavily
        if earnings_today:
            msg += f"\n<b>📅 Reporting Today</b>\n"
            for item in earnings_today[:6]:
                msg += f"• {item}\n"
        else:
            msg += f"\n<b>📅 Reporting Today</b>\n<i>No earnings from your watchlist today</i>\n"

        # Section 3: economic events — only if actual content found
        if econ_events:
            msg += f"\n<b>📋 Economic Events Today</b>\n"
            for item in econ_events:
                title = item.get("title", "")[:90]
                snippet = item.get("content", "")[:120].strip()
                msg += f"• {title}\n"
                if snippet:
                    msg += f"  <i>{snippet}</i>\n"

        # Section 4: actual market news (filtered)
        if market_news:
            label = "🌙 Overnight News" if market == "HK" else "🌅 Pre-Market News"
            msg += f"\n<b>{label}</b>\n"
            for item in market_news:
                title = item.get("title", "")[:90]
                snippet = item.get("content", "")[:120].strip()
                msg += f"• {title}\n"
                if snippet:
                    msg += f"  <i>{snippet}</i>\n"

        send_telegram(msg)
        print(f"[{datetime.now().strftime('%H:%M')}] {market} open alert sent.")

    except Exception as e:
        print(f"Market open alert error ({market}): {e}")


# ── Scheduler ─────────────────────────────────────────────────────────────────

def run_scheduler():
    """Run the scheduler."""
    print("📅 Scheduler running...")
    print("• Morning briefing: 07:00 HKT Mon–Fri (23:00 UTC Sun–Thu)")
    print("• HK open alert:    09:20 HKT Mon–Fri (01:20 UTC)")
    print("• US open alert:    09:20 ET  Mon–Fri (13:20 UTC)")
    print("• HK close:         16:05 HKT (08:05 UTC)")
    print("• EU close:         23:35 HKT (15:35 UTC)")
    print("• US close:         04:05 HKT+1 (20:05 UTC)")
    print("• Weekly digest:    18:00 HKT Sunday (10:00 UTC)")
    print("• Price alerts:     every 30 mins during market hours\n")

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

    # Market open alerts (UTC times, Mon–Fri)
    # HK open: 9:20am HKT = 01:20 UTC
    schedule.every().monday.at("01:20").do(lambda: send_market_open_alert("HK"))
    schedule.every().tuesday.at("01:20").do(lambda: send_market_open_alert("HK"))
    schedule.every().wednesday.at("01:20").do(lambda: send_market_open_alert("HK"))
    schedule.every().thursday.at("01:20").do(lambda: send_market_open_alert("HK"))
    schedule.every().friday.at("01:20").do(lambda: send_market_open_alert("HK"))
    # US open: 9:20am ET = 13:20 UTC (EDT) — ~5 min early Nov–Mar, acceptable
    schedule.every().monday.at("13:20").do(lambda: send_market_open_alert("US"))
    schedule.every().tuesday.at("13:20").do(lambda: send_market_open_alert("US"))
    schedule.every().wednesday.at("13:20").do(lambda: send_market_open_alert("US"))
    schedule.every().thursday.at("13:20").do(lambda: send_market_open_alert("US"))
    schedule.every().friday.at("13:20").do(lambda: send_market_open_alert("US"))

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