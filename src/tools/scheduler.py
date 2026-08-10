import os
import schedule
import time
from datetime import datetime, timedelta, timezone

_HKT = timezone(timedelta(hours=8))


def _now_hkt_str() -> str:
    """Current time in HKT for user-facing message headers — Railway runs UTC,
    so naive datetime.now() labelled 'HKT' was 8h off."""
    return datetime.now(_HKT).strftime("%d %b %Y, %H:%M")
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from src.tools.notion_holdings import get_holdings_cached, FALLBACK_WATCHLIST

load_dotenv()
from src.tools.llm import call_deepseek, tavily_search, clean_news, fmt_snippet


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


# Holiday calendars per market (holidays pkg; NYSE handles observed dates like
# Jul 3 2026). Country calendars approximate the HK/EU/Asia exchange closures.
_MARKET_HOLIDAYS = {
    "US":     ("financial", "NYSE"),
    "HK":     ("country", "HK"),
    "China":  ("country", "CN"),
    "Taiwan": ("country", "TW"),
    "Korea":  ("country", "KR"),
    "EU":     ("country", "DE"),   # Xetra proxy
    "UK":     ("country", "GB"),
}
_holiday_cache: dict = {}


def _is_market_holiday(market: str) -> bool:
    """True if today (UTC date — matches local trading date at all our alert
    times) is an exchange holiday for the market. Unknown market → False."""
    spec = _MARKET_HOLIDAYS.get(market)
    if not spec:
        return False
    try:
        import holidays as _hol
        if market not in _holiday_cache:
            kind, code = spec
            _holiday_cache[market] = (
                _hol.financial_holidays(code) if kind == "financial"
                else _hol.country_holidays(code)
            )
        return datetime.now(timezone.utc).date() in _holiday_cache[market]
    except Exception:
        return False  # never let the holiday check kill an alert cycle


def _is_weekend() -> bool:
    """True on Saturday/Sunday (UTC). `holidays` calendars only cover public
    holidays, not ordinary weekends, so this is a separate check. The daily
    close-alert cron (schedule.every().day.at(...)) fires literally every
    calendar day with no weekday filter of its own — this is what stops it
    firing on a Saturday. Bug found live: HK close alert fired on Sat 11 Jul
    2026 because nothing anywhere in that path checked the day of week."""
    return datetime.now(timezone.utc).weekday() >= 5


def _open_markets() -> list:
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return []
    time_utc = now.hour * 60 + now.minute
    return [
        m for m, (o, c) in MARKET_HOURS_UTC.items()
        if o <= time_utc <= c and not _is_market_holiday(m)
    ]


def _is_market_open() -> bool:
    return len(_open_markets()) > 0


_INDEX_MARKET_OVERRIDES = {"^HSI": "HK", "^KS11": "Korea"}


def _ticker_market(ticker: str) -> str | None:
    """
    Which _open_markets() bucket this ticker trades in. None = always-on
    (24/7 crypto), never gated by market hours.

    Without this, check_price_alerts() checked EVERY held ticker (US
    included) as soon as ANY market was open anywhere — a US ticker's move
    could get reported for the first time during HK trading hours, hours
    after the US session that actually produced the move had already
    closed. Confusing live-bug report from Louis: a "US market alert" that
    fired in the middle of the HK day made no sense because it wasn't
    actually a live US event at all.
    """
    from src.tools.prices import CRYPTO_IDS
    if ticker in CRYPTO_IDS:
        return None
    if ticker in _INDEX_MARKET_OVERRIDES:
        return _INDEX_MARKET_OVERRIDES[ticker]
    if ticker.endswith(".HK"):
        return "HK"
    if ticker.endswith((".SS", ".SZ")):
        return "China"
    if ticker.endswith(".TW"):
        return "Taiwan"
    if ticker.endswith((".KS", ".KQ")):
        return "Korea"
    if ticker.endswith((".DE", ".PA", ".AS", ".MI", ".SW", ".BR")):
        return "EU"
    if ticker.endswith(".L"):
        return "UK"
    return "US"


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
        articles = clean_news(tavily_search(
            "geopolitical risk US China Taiwan Europe Middle East trade tariffs war today",
            max_results=10, search_depth="basic",
        ))
        if not articles:
            return ""

        news_text = "\n".join(
            f"- {a.get('title', '')} — {fmt_snippet(a.get('content', ''), 150)}"
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


def _beta_adjusted_move_check(held_prices: dict, spy_change: float | None) -> str:
    """
    For big movers (|change| >= 5%), check whether the move is explained by
    the stock's own beta to today's broad market move, or represents genuine
    excess movement worth a specific explanation.

    Louis's own catch: a headline claiming "the NAND/DRAM commodity cycle is
    rolling over" because MU/WDC/SNDK fell hard is unfalsifiable narrative
    unless it's checked against whether the WHOLE market sold off today and
    these are just high-beta names amplifying that (the same names would also
    have risen more than the market on the way up -- a symmetric beta effect,
    not evidence of a structural break). Without this check, "big red number"
    silently becomes "confident causal story" every time. This computes the
    beta-implied move (beta x today's SPY change) vs the actual move, so the
    prompt can require real justification before using words like "rolling
    over" or "thesis broken".
    """
    if spy_change is None:
        return "Market benchmark (SPY) unavailable today — cannot beta-adjust moves; do not claim a move is 'thesis-specific' or a 'cycle turn' without another concrete, named catalyst."

    big_movers = [(t, d.get("change_pct")) for t, d in held_prices.items()
                  if d and d.get("change_pct") is not None and abs(d["change_pct"]) >= 5.0]
    if not big_movers:
        return f"S&P 500 (SPY) today: {spy_change:+.2f}%. No individual positions moved ≥5%."

    try:
        import yfinance as yf
        with ThreadPoolExecutor(max_workers=6) as ex:
            betas = dict(zip(
                [t for t, _ in big_movers],
                ex.map(lambda t: yf.Ticker(t).info.get("beta"), [t for t, _ in big_movers]),
            ))
    except Exception:
        betas = {}

    lines = [f"S&P 500 (SPY) today: {spy_change:+.2f}%."]
    for t, chg in big_movers:
        beta = betas.get(t)
        if beta:
            implied = beta * spy_change
            excess = chg - implied
            lines.append(
                f"- {t}: actual {chg:+.2f}%, beta {beta:.2f} implies ~{implied:+.2f}% from market beta alone "
                f"-> excess {excess:+.2f}pp {'(mostly beta, not name-specific news)' if abs(excess) < abs(implied) * 0.5 or abs(excess) < 2 else '(real excess move — a specific catalyst is worth naming)'}"
            )
        else:
            lines.append(f"- {t}: actual {chg:+.2f}% (beta unavailable — cannot beta-adjust, don't assume it's market-wide OR name-specific without other evidence)")
    return "\n".join(lines)


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
                return clean_news(tavily_search(
                    f"earnings results conference call after hours {names_str} yesterday",
                    max_results=8, search_depth="basic",
                ))
            except Exception:
                return []

        # Split Notion holdings into portfolio (held) and watchlist (monitoring only)
        portfolio_data = {t: d for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0}
        watchlist_data = {t: d for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) == 0}
        held_tickers    = list(portfolio_data.keys())
        all_tickers     = list(WATCHLIST_DATA.keys())

        with ThreadPoolExecutor(max_workers=5) as ex:
            f_prices  = ex.submit(get_live_prices, all_tickers + ["SPY"])
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

        spy_change = (prices.get("SPY") or {}).get("change_pct")
        beta_check_text = _beta_adjusted_move_check(held_prices, spy_change)

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
            snip = fmt_snippet(a.get("content", ""), 200)
            if snip:
                news_text += f"  {snip}\n"

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
                snip = fmt_snippet(a.get("content", ""), 200)
                if snip:
                    events_text += f"  {snip}\n"

        prompt = f"""You are an AI investment research assistant. Write a morning briefing for a multi-theme equity investor.

PORTFOLIO PRICES TODAY:
{prices_text}

MACRO & MARKET NEWS:
{news_text}

LAST NIGHT EVENTS (earnings calls, conferences, after-hours):
{events_text if events_text else "None found."}

INDUSTRY READ-THROUGH ALERTS (trigger tickers that moved 5%+ overnight):
{read_through_text if read_through_text else "None."}

GEOPOLITICAL PULSE (1 line per geography):
{geo_pulse if geo_pulse else "None."}

THEME PERFORMANCE:
{chr(10).join(theme_lines) if theme_lines else "No theme data."}

BETA-ADJUSTED MOVE CHECK (for positions that moved ≥5% today):
{beta_check_text}

UPCOMING EARNINGS (next 14 days):
{earnings_text}

Write exactly 3 sections:

<b>📰 Headlines</b>
Filtered overnight headlines — only what genuinely matters. If last night had earnings or events, lead with those. If read-through alerts fired, name the downstream holdings affected. Skip noise.

<b>🌍 What This Means</b>
Two parts in one section:
First — what does this mean FOR MY PORTFOLIO specifically? Name positions, not themes. If NVDA is up because of hyperscaler capex, say which of my holdings benefit and why.
Second — what does it mean for global markets broadly? Cover whichever of equities / commodities / FICC / crypto is actually relevant today. Not a fixed template — only cover what moved.

<b>🤖 AI Sector</b>
Dedicated section for the AI theme given portfolio concentration. What is happening across AI Infrastructure, Memory, Networking, Software & Data today? Any developer signals, earnings commentary, or narrative shifts? What is the sector telling us?

Rules:
- Maximum 350 words total
- No markdown tables, no ### headers
- Use • for bullet points within sections
- Be direct and specific — name tickers, not just themes
- Format for Telegram using <b>bold</b> for tickers and key terms
- CRITICAL, applies to ALL THREE sections above (Headlines, What This Means, AND AI Sector — a sector-wide claim like "AI hardware momentum stalling" needs the exact same scrutiny as a single-name claim): do not manufacture causal stories from price action alone. Before using language implying a structural/cyclical break ("cycle rolling over", "thesis broken", "trend reversing", "momentum stalling", "sector rotation out of AI"), check the BETA-ADJUSTED MOVE CHECK above. If a mover's excess move (beyond what its own beta times today's market move would predict) is small, say plainly that it looks like broad market beta, not a name- or sector-specific event — do NOT invent a cyclical narrative just because the raw percentage looks dramatic. Only use strong causal language when there is BOTH a real excess move AND a specific named catalyst (an actual reported number, guidance change, or news event) from the inputs above — never price action alone."""

        # max_tokens is a hard API-level cutoff (call_deepseek has no
        # finish_reason check or retry-on-truncation) -- 600 was too tight for
        # 3 full sections + the beta-adjustment reasoning now required in the
        # prompt, silently chopping the briefing off mid-sentence whenever the
        # model ran even slightly past its stated 350-word target (common LLM
        # behavior). Bumped with real headroom above the target, not just
        # enough to hit it exactly.
        briefing = call_deepseek(prompt, max_tokens=900, temperature=0.3, timeout=60) or "Could not generate AI briefing."

        header = f"🌅 <b>Morning Briefing — {datetime.now().strftime('%A %d %B %Y')}</b>\n\n"

        # Portfolio section — only positions moving ≥2% overnight, sorted by
        # biggest mover first (was: every held position, unconditionally —
        # for a 47-position book that's mostly noise every single morning;
        # same ≥2% bar the watchlist section below already uses).
        port_rows = []
        for t in held_tickers:
            d = prices.get(t)
            if not d:
                continue
            chg = d.get("change_pct") or 0
            if abs(chg) < 2.0:
                continue
            price = d.get("price")
            direction = "📈" if chg > 0 else "📉"
            line = f"{direction} <b>{fmt(t)}</b>: ${price} ({chg:+.2f}%)"
            avg_cost = portfolio_data.get(t, {}).get("avg_cost")
            if avg_cost and price:
                pnl = (price - avg_cost) / avg_cost * 100
                line += f" · <i>{pnl:+.1f}%</i>"
            port_rows.append((abs(chg), line))
        port_rows.sort(key=lambda x: x[0], reverse=True)
        if port_rows:
            price_block = f"<b>📊 Portfolio movers (≥2%, of {len(portfolio_data)} positions):</b>\n"
            price_block += "\n".join(row for _, row in port_rows[:15]) + "\n"
        else:
            price_block = f"<b>📊 Portfolio:</b> no positions moved ≥2% overnight ({len(portfolio_data)} held).\n"

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

        # Proactive analyst — spot new names in morning news, run mini-dives unprompted
        try:
            from src.tools.proactive_analyst import run_proactive_analysis
            all_news = (macro or []) + (last_night or [])
            known = set(WATCHLIST_DATA.keys())
            proactive_notes = run_proactive_analysis(all_news, known, max_dives=2)
            for note in proactive_notes:
                send_telegram(note)
        except Exception as e:
            print(f"Proactive analyst error: {e}")

        _alerted_today.clear()
        _drop_watch.clear()
        from src.tools.alert_config import clear_alerted_today
        clear_alerted_today(datetime.now().strftime("%Y-%m-%d"))
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
            return clean_news(tavily_search(
                "stock market sector rotation theme investing week",
                max_results=10, search_depth="basic",
            ))

        def fetch_macro_news():
            return clean_news(tavily_search(
                "Fed interest rates CPI jobs inflation macro economic outlook week",
                max_results=8, search_depth="basic",
            ))

        macro_tickers  = list(MACRO_TICKERS.keys())
        sector_tickers = list(SECTOR_ETFS.keys())
        held_tickers   = [t for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0]

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
            f_theme_radar   = ex.submit(
                lambda: __import__("src.tools.theme_radar", fromlist=["run_theme_radar"]).run_theme_radar(held_tickers)
            )

            macro_prices    = f_macro_prices.result()
            sector_prices   = f_sector_prices.result()
            ai_prices       = f_ai_prices.result()
            outside_news    = f_outside_news.result()
            macro_news      = f_macro_news.result()
            earnings        = f_earnings.result()
            momentum_digest = f_momentum.result()
            pnl_block       = f_pnl.result()
            theme_health    = f_theme_health.result()
            theme_radar     = f_theme_radar.result()

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
            snip = fmt_snippet(a.get("content", ""), 150)
            if snip:
                outside_text += f"  {snip}\n"

        # Macro news
        macro_news_text = ""
        for a in macro_news[:4]:
            macro_news_text += f"- {a.get('title', '')}\n"
            snip = fmt_snippet(a.get("content", ""), 150)
            if snip:
                macro_news_text += f"  {snip}\n"

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
        msg = header + pnl_block + "\n" + digest + "\n\n" + picks
        send_telegram(msg)
        if theme_radar:
            send_telegram(theme_radar)

        # Quant screen — separate 3rd message, fully independent of V3
        try:
            from src.tools.quant.signals import run_quant_screen
            all_tickers = list(WATCHLIST_DATA.keys())
            quant_msg = run_quant_screen(all_tickers, top_n=10)
            if quant_msg:
                send_telegram(quant_msg)
        except Exception as qe:
            print(f"[quant screen] error: {qe}")

        print(f"[{datetime.now().strftime('%H:%M')}] Weekly digest sent.")

    except Exception as e:
        print(f"Weekly digest error: {e}")
        from src.tools.notify import send_telegram
        send_telegram(f"❌ Weekly digest error: {str(e)[:200]}")


# ── Thesis Verdict Helper ─────────────────────────────────────────────────────

def _group_context_for_batch(tickers: list) -> dict:
    """
    For tickers in the same alert batch that share a PORTFOLIO_CATEGORIES
    bucket (e.g. MU/WDC/SNDK all "AI-Chips"), do ONE shared news search per
    bucket instead of N independent per-ticker searches.

    Without this, two genuinely correlated names with no saved thesis (see
    _thesis_verdict) get evaluated by two fully independent searches + LLM
    calls with zero awareness of each other — whichever specific articles
    each search happens to surface can produce contradictory-sounding
    verdicts (one "thesis intact", one "thesis concern") for what's actually
    the same sector-wide move. Grounding same-batch, same-category tickers in
    one shared search fixes that at the source. Returns {ticker: shared_context}
    only for tickers worth sharing (category has 2+ tickers in this batch).
    """
    try:
        from src.tools.llm import clean_news, fmt_snippet
    except Exception:
        return {}

    cats = _categorise(tickers)
    context_by_ticker: dict = {}
    for cat, cat_tickers in cats.items():
        if cat == "Other" or len(cat_tickers) < 2:
            continue
        try:
            results = clean_news(tavily_search(f"{cat} stocks selloff drop news today", max_results=5, timeout=8))
            if not results:
                continue
            shared = f"Recent news for the {cat} sector (multiple names in this group moved together today):\n" + "\n".join(
                f"- {r.get('title', '')} {fmt_snippet(r.get('content', ''), 150)}" for r in results
            )
            for t in cat_tickers:
                context_by_ticker[t] = shared
        except Exception:
            continue
    return context_by_ticker


def _thesis_verdict(ticker: str, change: float, thesis: str, price: float, shared_context: str = "", name: str = "") -> str:
    """One-sentence verdict: thesis intact (buy dip) or thesis concern (wait).
    Priority: saved thesis > shared same-batch sector context (see
    _group_context_for_batch) > per-ticker Tavily fallback."""
    try:
        if thesis:
            context = f"Investment thesis on file: {thesis[:300]}"
        elif shared_context:
            context = shared_context
        else:
            # No thesis saved and no batch-mate in the same category —
            # fetch recent news to form a verdict. Relevance-filtered: a
            # search hit isn't proof it's actually about this ticker (see
            # filter_relevant docstring — confirmed live on this exact
            # class of search).
            from src.tools.llm import clean_news, fmt_snippet, filter_relevant
            results = filter_relevant(
                clean_news(tavily_search(f"{ticker} stock drop news today reason", max_results=5, timeout=8)),
                ticker, name,
            )
            if results:
                context = "Recent news:\n" + "\n".join(
                    f"- {r.get('title', '')} {fmt_snippet(r.get('content', ''), 150)}" for r in results
                )
            else:
                context = "No thesis or relevant news available — assess based on ticker name and drop size only."

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
    to_remove = []
    msgs = []
    stabilised_tickers = []
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
            stabilised_tickers.append(ticker)

    if msgs:
        from src.tools.notify import send_telegram_with_buttons
        msg = (
            "🔔 <b>Price Stabilisation Alert</b>\n"
            f"<i>{_now_hkt_str()} HKT</i>\n\n"
            + "\n\n".join(msgs)
            + "\n\n<i>Tap a ticker for the full deep dive ↓</i>"
        )
        rows = [
            [{"text": t, "callback_data": f"deepdive:{t}"} for t in stabilised_tickers[i:i + 3]]
            for i in range(0, len(stabilised_tickers), 3)
        ]
        send_telegram_with_buttons(msg, rows)


# ── Holdings Auto-Reload ─────────────────────────────────────────────────────
# scheduler.py and telegram_bot.py each load their own independent copy of
# Notion holdings at import time (WATCHLIST_DATA here, WATCHLIST/PORTFOLIO/
# WATCHLIST_ONLY/WATCHLIST_TICKERS there) — neither auto-syncs with Notion.
# Previously the only way to pick up a trade, ticker fix, or watchlist add
# was typing "reload" in Telegram. This refreshes both copies on a timer so
# edits made directly in Notion (or by anything other than the bot's own
# buy/sell tools) show up without a manual step.

def auto_reload_holdings():
    """Refresh both modules' in-memory holdings from Notion. Mutates every
    dict in place (never rebinds the module-level name) so any other module
    already holding a reference sees the update immediately — same pattern
    telegram_bot.py's manual 'reload' command uses."""
    try:
        from src.tools.notion_holdings import reload_holdings
        new_data = reload_holdings()

        WATCHLIST_DATA.clear()
        WATCHLIST_DATA.update(new_data)
        WATCHLIST[:] = list(new_data.keys())

        try:
            import src.tools.telegram_bot as _tb
            _tb.WATCHLIST.clear(); _tb.WATCHLIST.update(new_data)
            _tb.WATCHLIST_TICKERS[:] = list(new_data.keys())
            _tb.WATCHLIST_TICKERS_SET.clear(); _tb.WATCHLIST_TICKERS_SET.update(_tb.WATCHLIST_TICKERS)
            _tb.PORTFOLIO.clear(); _tb.PORTFOLIO.update({t: d for t, d in new_data.items() if (d.get("shares") or 0) > 0})
            _tb.WATCHLIST_ONLY.clear(); _tb.WATCHLIST_ONLY.update({t: d for t, d in new_data.items() if (d.get("shares") or 0) == 0})
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M')}] telegram_bot sync skipped: {e}")

        print(f"[{datetime.now().strftime('%H:%M')}] Holdings auto-reloaded ({len(new_data)} names).")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M')}] Holdings auto-reload error: {e}")


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
        from concurrent.futures import ThreadPoolExecutor

        today = datetime.now().strftime("%Y-%m-%d")

        held_data = {t: d for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0}
        all_tickers = list(held_data.keys()) if held_data else WATCHLIST
        # Only check tickers whose own home market is actually open (or that
        # are always-on, like crypto) — see _ticker_market for why this matters.
        tickers_to_check = [t for t in all_tickers if _ticker_market(t) is None or _ticker_market(t) in open_now]
        prices = get_live_prices(tickers_to_check)

        # Check for stabilisation of previously-dropped tickers
        _check_recovery_alerts(prices, held_data)

        from src.tools.alert_config import has_alerted_today, mark_alerted_today
        alert_items = []  # (ticker, change, price, thesis)
        for ticker, data in prices.items():
            if not data:
                continue
            change = data.get("change_pct") or 0
            if abs(change) >= 8.0:
                if has_alerted_today(ticker, today):
                    continue
                thesis = held_data.get(ticker, {}).get("thesis", "")
                alert_items.append((ticker, change, data.get("price") or 0, thesis))
                mark_alerted_today(ticker, today)
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
            from src.tools.notify import send_telegram_with_buttons

            def _ticker_rows(ts: list) -> list:
                return [
                    [{"text": t, "callback_data": f"deepdive:{t}"} for t in ts[i:i + 3]]
                    for i in range(0, len(ts), 3)
                ]

            custom_hits = check_custom_alerts(prices, _custom_alerted, today)
            if custom_hits:
                custom_lines = []
                for t, change, price, threshold, direction in custom_hits:
                    arrow = "📈" if change > 0 else "📉"
                    custom_lines.append(f"{arrow} <b>{fmt(t)}</b>: {change:+.2f}% (${price}) — your {threshold:.1f}% {direction} alert")
                msg = "🔔 <b>Custom Alert Triggered</b>\n\n" + "\n".join(custom_lines) + "\n\n<i>Tap a ticker for the full deep dive ↓</i>"
                send_telegram_with_buttons(msg, _ticker_rows([t for t, *_ in custom_hits]))
            # Watchlist price targets
            wl_hits = check_watchlist_targets(prices, _custom_alerted, today)
            if wl_hits:
                wl_lines = []
                for t, price, target, direction, note in wl_hits:
                    arrow = "📉" if direction == "below" else "📈"
                    note_str = f"\n  <i>{note}</i>" if note else ""
                    wl_lines.append(f"{arrow} <b>{fmt(t)}</b> hit ${price:.2f} (target: {direction} ${target:.2f}){note_str}")
                msg = "🎯 <b>Watchlist Target Hit</b>\n\n" + "\n".join(wl_lines) + "\n\n<i>Time to size in? Tap a ticker for the full deep dive ↓</i>"
                send_telegram_with_buttons(msg, _ticker_rows([t for t, *_ in wl_hits]))
        except Exception as ce:
            print(f"Custom alert check error: {ce}")

        if alert_items:
            # Fetch thesis verdicts in parallel for drops
            drops = [(t, c, p, th) for t, c, p, th in alert_items if c < 0]
            verdicts = {}
            if drops:
                # Tickers with no saved thesis get a shared sector-level search
                # instead of independent per-ticker searches if a batch-mate
                # shares their category — see _group_context_for_batch.
                thesisless = [t for t, c, p, th in drops if not th]
                shared_ctx = _group_context_for_batch(thesisless) if thesisless else {}
                with ThreadPoolExecutor(max_workers=4) as ex:
                    futures = {
                        ex.submit(_thesis_verdict, t, c, th, p, shared_ctx.get(t, ""), WATCHLIST_DATA.get(t, {}).get("name", "")): t
                        for t, c, p, th in drops
                    }
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
            msg += "\n\n<i>Tap a ticker for the full deep dive ↓</i>"

            from src.tools.notify import send_telegram_with_buttons
            alert_tickers = [t for t, _, _, _ in alert_items]
            rows = [
                [{"text": t, "callback_data": f"deepdive:{t}"} for t in alert_tickers[i:i + 3]]
                for i in range(0, len(alert_tickers), 3)
            ]
            send_telegram_with_buttons(msg, rows)
            print(f"[{datetime.now().strftime('%H:%M')}] Sent {len(alert_items)} price alerts.")
        else:
            print(f"[{datetime.now().strftime('%H:%M')}] No new alerts triggered.")

    except Exception as e:
        print(f"Price alert error: {e}")


# ── Portfolio Category Map ────────────────────────────────────────────────────

# 18-group map covering the full portfolio + watchlist (2026-07-06 review,
# spec: ~/Desktop/Portfolio_Groups_Proposal.pdf). Names inside a group trade
# together — same catalyst, same session, same risk factor.
# AI names follow Jensen's 5-layer AI stack (Energy → Chips → Infrastructure →
# Models → Apps); fine detail (memory / semicap / cybersecurity / ...) is a
# sub-tag in the spec PDF, not a separate group. Mag 7 stays its own block;
# cross-category names sit where market consensus puts them. Non-AI unchanged.
PORTFOLIO_CATEGORIES = {
    "Mag 7":                 ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"],
    "AI-Energy":             ["SEI", "GEV", "BE", "OKLO", "CEG", "SMR", "TLN", "VST",
                              "ENPH", "TPZ.TO", "SU.PA", "IREN"],
    "AI-Chips":              ["AMD", "INTC", "TSM", "NVTS", "AVGO", "TXN", "2454.TW",
                              "0981.HK", "HNHPF", "ARM", "ALAB",
                              "ASML", "LRCX", "AMAT",
                              "MU", "WDC", "SNDK", "DRAM", "7709.HK", "CBRS"],
    "AI-Infrastructure":     ["LITE", "GLW", "CRDO", "CSCO", "NOK", "POET", "SIVEF",
                              "ORCL", "CRWV"],
    "AI-Models":             ["2513.HK", "0100.HK"],
    "AI-Apps":               ["IBM", "PLTR", "SNOW", "CRWD", "FIG", "APP"],
    "China Internet":        ["BABA", "9988.HK", "0700.HK", "1024.HK"],
    "Space & Satellites":    ["SPCX", "ASTS", "RKLB", "ASTX"],
    "Defence & Aerospace":   ["GE", "LMT", "2357.HK", "RHM.DE", "BA.L"],
    "Quantum":               ["IONQ", "RGTI", "INFQ", "LAES"],
    "Robotics & Automation": ["CGNX", "2729.HK", "688169.SS"],
    "EV & Future Mobility":  ["UBER", "XPEV", "7489.HK", "601689.SS", "EH", "JOBY", "EVTL", "1810.HK"],
    "Banks & Financials":    ["JPM", "MS", "GS", "2318.HK", "1299.HK"],
    "Crypto & Digital Assets": ["CRCL", "HOOD", "MSTR", "XYZ", "STCK",
                                "BTC", "ETH", "SOL", "MATIC"],
    "Energy & Resources":    ["SLB", "HAL", "VLO", "2899.HK", "1919.HK", "MP",
                              "USAR", "— (SECTOR)"],
    "E-Commerce & Consumer": ["SHOP", "ETSY", "6618.HK", "0780.HK", "3690.HK"],
    "Europe Blue Chips":     ["NVO", "MC.PA", "NESN.SW"],
    "Macro / Index / Hedges": ["GLD", ".VIX", "^HSI", "^KS11", "SCHR"],
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

# Per-ticker shadow detail store — populated at close, retrieved on button tap.
# Persisted to SQLite (survives process restarts/redeploys) and upserted per-ticker
# rather than replaced wholesale, so one market's close doesn't wipe another's
# still-fresh buttons (was a bare in-process dict, reset to {} on every call).
import sqlite3

_SHADOW_DB_DIR = "/app/data" if os.path.exists("/app/data") else "."
_SHADOW_DB_PATH = os.path.join(_SHADOW_DB_DIR, "shadow_detail.db")
_SHADOW_DETAIL_TTL_HOURS = 24


def _shadow_db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_SHADOW_DB_PATH, check_same_thread=False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS shadow_ticker_detail ("
        "ticker TEXT PRIMARY KEY, detail TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    return conn


def _store_shadow_details(details: dict) -> None:
    """Upsert per-ticker shadow detail — merges, never wipes other tickers' entries."""
    if not details:
        return
    now = datetime.now().isoformat()
    conn = _shadow_db_conn()
    with conn:
        conn.executemany(
            "INSERT INTO shadow_ticker_detail (ticker, detail, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET detail=excluded.detail, updated_at=excluded.updated_at",
            [(t, d, now) for t, d in details.items()],
        )
    conn.close()


def get_shadow_detail(ticker: str) -> str | None:
    """Fetch a ticker's shadow-portfolio detail if stored within the TTL window."""
    conn = _shadow_db_conn()
    row = conn.execute(
        "SELECT detail, updated_at FROM shadow_ticker_detail WHERE ticker = ?", (ticker,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    detail, updated_at = row
    try:
        age = datetime.now() - datetime.fromisoformat(updated_at)
    except ValueError:
        return None
    if age > timedelta(hours=_SHADOW_DETAIL_TTL_HOURS):
        return None
    return detail


def _shadow_portfolio_message(summary_lines: list, held: dict, market: str) -> None:
    """
    AI Shadow Portfolio — short verdict message with per-ticker buttons.
    Tapping a ticker button returns the full breakdown for that name.
    Sends directly via send_telegram_with_buttons (no return value).
    """
    try:
        from src.tools.llm import call_deepseek as _ds
        from src.tools.notify import send_telegram_with_buttons

        from src.tools.prices import get_live_prices
        tickers = list(held.keys())
        live = get_live_prices(tickers) if tickers else {}
        pnl_lines = []
        for t, d in held.items():
            avg = d.get("avg_cost", 0)
            if not avg:
                continue
            price = live.get(t, {}).get("price", 0) if isinstance(live.get(t), dict) else live.get(t, 0)
            pnl_pct = ((price - avg) / avg * 100) if price else 0
            pnl_lines.append(f"{t} ({d.get('name', t)}): avg cost ${avg:.2f}, P&L {pnl_pct:+.0f}%")

        context = (
            f"TODAY'S {market} CLOSE:\n" + "\n".join(summary_lines) +
            "\n\nPORTFOLIO (ticker, avg cost, unrealised P&L):\n" + "\n".join(pnl_lines[:25])
        )

        # Single call — structured short summary + per-ticker details
        prompt = (
            context + "\n\n"
            "You are a senior portfolio manager. Output TWO sections separated by ---DETAILS---\n\n"
            "SECTION 1 — SHORT SUMMARY (this goes in the main message):\n"
            "Every ticker MUST be written as <b>TICKER (Name)</b> using the exact name given in the "
            "PORTFOLIO section above — never a bare ticker.\n"
            "Format exactly like this:\n"
            "✅ BUY NOW\n• <b>TICKER (Name)</b> $price — one-line reason\n\n"
            "⏳ SET LIMITS\n• <b>TICKER (Name)</b> — limit $X, one-line reason\n\n"
            "❌ SKIP\n• <b>TICKER (Name)</b> — one-line reason\n\n"
            "💰 Fund it: [which position to trim and why, one line]\n\n"
            "Max 3 tickers per section. Only include sections with actual recommendations.\n"
            "CRITICAL: each ticker must appear in EXACTLY ONE of BUY NOW / SET LIMITS / SKIP — "
            "never the same ticker in two sections. If you want to recommend buying some now AND "
            "adding more on further weakness, put it in BUY NOW ONLY and fold the lower add-level "
            "into that one-line reason (e.g. '$1293 — buy-the-dip, add more toward $1250 if it weakens "
            "further') instead of creating a separate SET LIMITS entry for the same name.\n\n"
            "---DETAILS---\n\n"
            "SECTION 2 — PER-TICKER DETAIL (one block per ticker you mentioned above):\n"
            "Format each block as:\n"
            "TICKER:\n"
            "Current price, % off high. Valuation snapshot (fwd P/E, growth, PEG if relevant). "
            "Thesis in 2 sentences. Entry zone. Specific limit price. Risk to watch. Max 120 words per ticker.\n\n"
            "Only include tickers you mentioned in Section 1."
        )

        raw = _ds(prompt, max_tokens=800, temperature=0.35, timeout=45)
        if not raw or raw.startswith("❌"):
            return

        # Split into summary + details
        parts = raw.split("---DETAILS---", 1)
        summary_text = parts[0].strip()
        details_text = parts[1].strip() if len(parts) > 1 else ""

        import re

        # Parse per-ticker details from Section 2's freeform "TICKER:\n" blocks.
        # Must accept HK-style tickers (digits + ".HK") and index tickers ("^HSI"),
        # not just US letters-only.
        parsed_details: dict = {}
        if details_text:
            blocks = re.split(r'(?:^|\n)([A-Za-z0-9.\^]{1,12}):\n', details_text)
            for i in range(1, len(blocks) - 1, 2):
                ticker = blocks[i].strip()
                detail = blocks[i + 1].strip()
                parsed_details[ticker] = detail

        # Extract ALL tickers mentioned in the summary (from <b>TICKER (Name)</b> or
        # bare <b>TICKER</b> tags), in order, so every ticker gets a button. Capture
        # the full bold tag first, then take just the ticker portion before " (" —
        # matching on [A-Z]{1,6} alone can't match HK tickers like "9988.HK" (leads
        # with a digit, contains a dot).
        bold_tags = re.findall(r'<b>([^<]+)</b>', summary_text)
        seen = set()
        tickers = []
        for tag in bold_tags:
            t = tag.split(" (")[0].strip()
            if t and t not in seen and len(t) <= 12:
                seen.add(t)
                tickers.append(t)

        # Section 1 and Section 2 are two independently LLM-formatted blocks — if
        # Section 2's freeform "TICKER:\n" header drifts even slightly on a given
        # run, that ticker silently gets no parsed detail even though its button
        # (built from Section 1 above) still appears, leading to a dead "No detail
        # available" button. Guarantee every button has *some* backing detail by
        # falling back to that ticker's own summary bullet line.
        line_by_ticker: dict = {}
        for line in summary_text.split("\n"):
            m = re.search(r'<b>([^<]+)</b>', line)
            if m:
                line_by_ticker[m.group(1).split(" (")[0].strip()] = line.strip()
        for t in tickers:
            if t not in parsed_details and t in line_by_ticker:
                parsed_details[t] = line_by_ticker[t] + "\n\n(Full breakdown unavailable this cycle — showing summary line only.)"

        _store_shadow_details(parsed_details)

        rows = []
        for i in range(0, len(tickers), 3):
            rows.append([
                {"text": t, "callback_data": f"shadow:{t}"}
                for t in tickers[i:i+3]
            ])

        msg = f"🧠 <b>AI Shadow Portfolio — {market} Close</b>\n\n{summary_text}"
        if rows:
            msg += "\n\n<i>Tap a ticker for the full breakdown ↓</i>"
            send_telegram_with_buttons(msg, rows)
        else:
            from src.tools.notify import send_telegram
            send_telegram(msg)

    except Exception as e:
        print(f"Shadow portfolio error: {e}")


# ── Market Close Alerts ───────────────────────────────────────────────────────


# ── Market config — one entry per market, drives both open and close ──────────

_MARKET_CFG = {
    "US": {
        "flag":        "🇺🇸",
        "open_time":   "9:30am ET",
        "open_macro":  {"NQ=F": "Nasdaq Fut", "ES=F": "S&P Fut", "^VIX": "VIX", "GC=F": "Gold", "CL=F": "WTI Oil"},
        "news_query":  "US stock market pre-market earnings {date}",
        "news_label":  "📰 Pre-Market News",
        # Tickers included at OPEN (pre-market movers)
        "open_filter": lambda t: not any(t.endswith(s) for s in [".HK", ".SS", ".SZ", ".TW"]),
        # Tickers included at CLOSE (portfolio summary)
        "close_filter": lambda t: not any(t.endswith(s) for s in [".HK", ".SS", ".SZ", ".TW"]),
    },
    "HK": {
        "flag":        "🇭🇰",
        "open_time":   "9:30am HKT",
        "open_macro":  {"^HSI": "Hang Seng", "NQ=F": "Nasdaq Fut", "USDCNH=X": "USD/CNH", "GC=F": "Gold"},
        "news_query":  "Hong Kong stock market Hang Seng China Asia {date}",
        "news_label":  "🌏 Asia News",
        "open_filter": lambda t: t.endswith(".HK") or t.endswith(".SS") or t.endswith(".SZ"),
        "close_filter": lambda t: t.endswith(".HK") or t.endswith(".SS") or t.endswith(".SZ"),
    },
    "EU": {
        "flag":        "🇪🇺",
        "open_time":   "9:00am CET",
        "open_macro":  {"^STOXX50E": "Euro Stoxx 50", "EURUSD=X": "EUR/USD", "GC=F": "Gold"},
        "news_query":  "European stock market DAX FTSE earnings {date}",
        "news_label":  "🌍 European News",
        "open_filter": lambda t: t in {"ASML"},
        "close_filter": lambda t: t in {"ASML"},
    },
}

def _fetch_market_news(query: str, label: str, held: dict | None = None) -> str:
    """
    Market news block for the open alert: fetch real news articles (Tavily
    topic=news, last 2 days), then LLM-compress into trader-relevant bullets —
    raw search snippets are SEO noise and page chrome. Returns the formatted
    HTML block, or "" when nothing solid: an empty section beats gibberish.

    `held` = {ticker: name} for this market's positions. Without it the output
    was generic wire-copy ("China stocks rebound on AI and chip rally — may
    drive HK tech names higher") that never said WHICH stocks moved, WHY, or
    which of the user's actual positions it reads through to. Two causes, both
    fixed here: the prompt had no idea what the user owns, and a 22-word-per-
    line cap made naming names + cause + read-through physically impossible.
    """
    try:
        results = tavily_search(query, max_results=10, search_depth="basic",
                                topic="news", days=2)
        articles = clean_news(results)
        if not articles:
            return ""

        news_text = "\n".join(
            f"- {a.get('title', '')} — {fmt_snippet(a.get('content', ''), 200)}"
            for a in articles[:8]
        )
        held = held or {}
        holdings_line = (
            "The reader HOLDS these positions in this market:\n"
            + "\n".join(f"- {t} ({n})" for t, n in list(held.items())[:25])
            + "\n\n"
        ) if held else ""

        bullets = call_deepseek(
            f"{holdings_line}"
            "From these raw news search results, extract up to 4 distinct facts that "
            "matter for a trader at today's market open.\n\n"
            "Each bullet MUST be specific and answer three things:\n"
            "  1. WHAT specifically happened — name the actual companies/tickers or the "
            "concrete data point. Never a vague aggregate like 'China stocks rebounded' "
            "or 'tech rallied' without naming which ones.\n"
            "  2. WHY it happened — the actual driver stated in the source.\n"
            "  3. SO WHAT for this reader — which of THEIR held positions listed above it "
            "reads through to, and in which direction. If it genuinely doesn't touch any "
            "of their names, say 'no direct read-through to your book' rather than "
            "inventing a connection.\n\n"
            "Format: '• <b>[topic]</b>: [what + why] — [read-through to their positions]'\n"
            "Up to 45 words per bullet. Prefer 2 specific bullets over 4 vague ones.\n"
            "Only use facts present in the sources below — do not add context from memory. "
            "Ignore SEO pages, index/chart pages, ads, disclaimers, and anything stale. "
            "No preamble. If nothing genuinely newsworthy, reply exactly: NONE\n\n"
            f"{news_text}",
            max_tokens=500, temperature=0.2,
        )
        if not bullets or bullets.startswith("❌") or bullets.strip().upper() == "NONE":
            return ""
        lines = [ln.strip() for ln in bullets.splitlines() if ln.strip().startswith("•")][:4]
        if not lines:
            return ""
        return f"\n<b>{label}</b>\n" + "\n".join(lines) + "\n"
    except Exception:
        return ""


def send_market_close_alert(market: str):
    """Theme-grouped portfolio close summary. Config-driven per market."""
    if _is_weekend():
        print(f"[{datetime.now().strftime('%H:%M')}] Weekend — close alert skipped.")
        return
    if _is_market_holiday(market):
        print(f"[{datetime.now().strftime('%H:%M')}] {market} holiday — close alert skipped.")
        return
    print(f"[{datetime.now().strftime('%H:%M')}] Market close alert: {market}")
    try:
        from src.tools.prices import get_live_prices
        from src.tools.notify import send_telegram

        cfg  = _MARKET_CFG.get(market, _MARKET_CFG["US"])
        held = {t: d for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0}
        tickers = [t for t in held if cfg["close_filter"](t)]

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
            f"🔔 {cfg['flag']} <b>{market} Close — Portfolio Summary</b>\n"
            f"<i>{_now_hkt_str()} HKT</i>\n"
            f"<i>{total_winners} up · {total_losers} down</i>\n\n"
            + "\n".join(cat_blocks)
            + synthesis
        )

        send_telegram(msg)

        # Second message: AI Shadow Portfolio (sends itself with buttons).
        # Must pass the market-filtered dict, not the full cross-market `held` —
        # _shadow_portfolio_message has no filter of its own, so passing the
        # unfiltered book here is what let US names leak into an HK Close message.
        market_held = {t: held[t] for t in tickers}
        _shadow_portfolio_message(summary_lines, market_held, market)
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
            all_articles += clean_news(tavily_search(
                f"breaking news {top_held_names} today",
                max_results=10, search_depth="basic",
            ))
        except Exception as e:
            print(f"News search 1 error: {e}")

        # Search 2: macro / geopolitical breaking news
        try:
            all_articles += clean_news(tavily_search(
                "breaking news market moving geopolitical trade policy interest rates today",
                max_results=10, search_depth="basic",
            ))
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
            f"{i+1}. {a.get('title', '')} — {fmt_snippet(a.get('content', ''), 150)}"
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
            f"<i>{_now_hkt_str()} HKT</i>\n\n"
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
        msg += f"<i>{_now_hkt_str()} HKT</i>\n\n"

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
    """Config-driven market open brief. Add a new market by adding an entry to _MARKET_CFG."""
    if _is_weekend():
        print(f"[{datetime.now().strftime('%H:%M')}] Weekend — open alert skipped.")
        return
    if _is_market_holiday(market):
        print(f"[{datetime.now().strftime('%H:%M')}] {market} holiday — open alert skipped.")
        return
    print(f"[{datetime.now().strftime('%H:%M')}] Market open alert: {market}")
    try:
        from src.tools.prices import get_live_prices, normalize_ticker
        from src.tools.notify import send_telegram
        import yfinance as yf

        cfg  = _MARKET_CFG.get(market, _MARKET_CFG["US"])
        held = {t: d for t, d in WATCHLIST_DATA.items() if (d.get("shares") or 0) > 0}
        mkt_tickers = [t for t in held if cfg["open_filter"](t)]

        # ── Parallel data fetches ──────────────────────────────────────────────
        def _pre_market_moves():
            """US only — yfinance fast_info pre-market price."""
            moves = {}
            if market != "US":
                return moves
            for ticker in mkt_tickers[:15]:
                try:
                    yfk = normalize_ticker(ticker)
                    if not yfk or yfk.startswith("CRYPTO:"):
                        continue
                    fi   = yf.Ticker(yfk).fast_info
                    pre  = getattr(fi, "pre_market_price", None)
                    prev = getattr(fi, "previous_close", None)
                    if pre and prev and prev > 0 and pre != prev:
                        moves[ticker] = {"pre_price": pre, "prev_close": prev,
                                         "pre_pct": (pre - prev) / prev * 100}
                except Exception:
                    pass
            return moves

        def _earnings_today():
            try:
                from src.tools.earnings_calendar import get_earnings_dates
                dates = get_earnings_dates(list(WATCHLIST_DATA.keys()))
                today = datetime.now().strftime("%Y-%m-%d")
                out = []
                for t, info in dates.items():
                    if (info.get("date") or "").startswith(today):
                        when = info.get("when", "")
                        out.append(f"{fmt(t)}{(' (' + when + ')') if when else ''}")
                return out
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=3) as ex:
            f_pre    = ex.submit(_pre_market_moves)
            f_prices = ex.submit(get_live_prices, mkt_tickers)
            f_macro  = ex.submit(get_live_prices, list(cfg["open_macro"].keys()))
            f_earn   = ex.submit(_earnings_today)
            pre_moves      = f_pre.result(timeout=20)
            prices         = f_prices.result(timeout=20)
            macro_prices   = f_macro.result(timeout=15)
            earnings_today = f_earn.result(timeout=15)

        # ── Build message ──────────────────────────────────────────────────────
        now_str = _now_hkt_str()
        msg = f"🔔 {cfg['flag']} <b>{market} Open</b> — {cfg['open_time']}\n<i>{now_str} HKT</i>\n\n"

        # Section 1 — Macro snapshot
        macro_lines = []
        for sym, label in cfg["open_macro"].items():
            p   = macro_prices.get(sym, {})
            chg = p.get("change_pct")
            if chg is not None:
                arrow = "▲" if chg > 0 else "▼"
                macro_lines.append(f"  {arrow} {label}: {chg:+.1f}%")
        if macro_lines:
            msg += f"<b>🌐 Macro</b>\n" + "\n".join(macro_lines) + "\n"

        # Section 2 — Earnings today
        msg += f"\n<b>📅 Reporting Today</b>\n"
        if earnings_today:
            for item in earnings_today[:6]:
                msg += f"• {item}\n"
        else:
            msg += "<i>Nothing from your watchlist today</i>\n"

        # Section 3 — Market news (from config query, junk filtered)
        today_str = datetime.now().strftime("%B %d %Y")
        # Pass this market's held names so the news block can state the actual
        # read-through to the book instead of generic wire commentary.
        _held_here = {
            t: WATCHLIST_DATA.get(t, {}).get("name", t)
            for t in mkt_tickers
        } if mkt_tickers else {}
        news_block = _fetch_market_news(
            cfg["news_query"].format(date=today_str), cfg["news_label"], _held_here
        )
        if news_block:
            msg += news_block

        # Section 4 — Positions grouped by sector/theme (same categories as the close alert)
        if mkt_tickers:
            pre_available = bool(pre_moves)
            if pre_available:
                msg += f"\n<b>📊 Pre-Market Movers</b> <i>(vs prev close)</i>\n"
            else:
                msg += f"\n<b>📊 Your {market} Positions</b> <i>(last close)</i>\n"

            def _pos_line(ticker: str):
                """Returns (sort_key, line) or None if no price available."""
                d        = held.get(ticker, {})
                avg_cost = d.get("avg_cost", 0)
                if ticker in pre_moves:
                    pm    = pre_moves[ticker]
                    pct   = pm["pre_pct"]
                    arrow = "▲" if pct > 0 else "▼"
                    emoji = "🟢" if pct > 0 else "🔴"
                    line  = f"  {emoji} <b>{ticker}</b> {arrow}{abs(pct):.1f}% pre-mkt (${pm['pre_price']:.2f})"
                    if abs(pct) >= 3.0:
                        sh5  = int(5000  / pm["pre_price"])
                        sh10 = int(10000 / pm["pre_price"])
                        line += f"\n    💡 {'add' if pct < 0 else 'trim'}: $5k={sh5}sh · $10k={sh10}sh"
                    return (abs(pct), line)
                p     = prices.get(ticker, {})
                price = p.get("price")
                if price and avg_cost:
                    pnl   = (price - avg_cost) / avg_cost * 100
                    emoji = "🟢" if pnl > 0 else "🔴"
                    return (0, f"  {emoji} <b>{ticker}</b> ${price:.2f} · cost P&L {pnl:+.1f}%")
                if price:
                    return (0, f"  ⚪ <b>{ticker}</b> ${price:.2f}")
                return None

            cat_blocks = []
            for cat, cat_tickers in _categorise(mkt_tickers).items():
                lines = [pl for pl in (_pos_line(t) for t in cat_tickers) if pl]
                if not lines:
                    continue
                lines.sort(key=lambda x: x[0], reverse=True)  # biggest pre-mkt mover first
                cat_blocks.append(f"<b>{cat}</b>\n" + "\n".join(ln for _, ln in lines))
            msg += "\n".join(cat_blocks) + "\n"

        send_telegram(msg)
        print(f"[{datetime.now().strftime('%H:%M')}] {market} open alert sent.")

    except Exception as e:
        print(f"Market open alert error ({market}): {e}")


# ── Monthly 复盘 ──────────────────────────────────────────────────────────────

def _maybe_send_monthly_review():
    """Run on the 1st of each month at 9am HKT — auto-push 复盘 to Telegram."""
    if datetime.now().day != 1:
        return
    try:
        from src.tools.notion_holdings import get_journal_entries
        from src.tools.llm import call_deepseek
        from src.tools.notify import send_telegram

        entries = get_journal_entries()
        closed = [e for e in entries if e.get("status", "").lower() == "closed" and e.get("realised_pnl") is not None]
        open_  = [e for e in entries if e.get("status", "").lower() == "open"]

        if not closed and not open_:
            return

        closed_lines = []
        for e in sorted(closed, key=lambda x: x.get("opened", ""), reverse=True)[:20]:
            t = e.get("ticker", "?")
            pnl_pct = e.get("realised_pnl_pct", 0)
            rationale = e.get("rationale", "")[:120]
            opened = e.get("opened", "")
            closed_date = e.get("closed", "")
            icon = "🟢" if pnl_pct > 0 else "🔴"
            closed_lines.append(f"{icon} {t}: {pnl_pct:+.1f}% | opened {opened} closed {closed_date} | {rationale}")

        open_lines = [f"• {e.get('ticker', '?')}: {e.get('rationale', '')[:80]}" for e in open_[:10]]

        context = ""
        if closed_lines:
            context += "CLOSED TRADES:\n" + "\n".join(closed_lines) + "\n\n"
        if open_lines:
            context += "OPEN POSITIONS:\n" + "\n".join(open_lines) + "\n\n"

        prompt = (
            "You are reviewing a portfolio's recent trade history as a post-mortem.\n\n"
            + context
            + "Write a structured 复盘 (review) covering:\n\n"
            "<b>🏆 Best Decision</b> — which closed trade worked and what drove it. Was it thesis-driven or lucky timing?\n"
            "<b>💀 Worst Decision</b> — which closed trade failed and why. Was the thesis wrong or was it execution?\n"
            "<b>📊 Pattern</b> — one observation about what the closed trades reveal about decision-making tendencies\n"
            "<b>📌 3 Things to Do Differently</b> — specific, actionable, named (not generic advice)\n\n"
            "Max 250 words. Be honest and direct. Use <b>bold</b> for tickers. No flattery."
        )

        result = call_deepseek(prompt, max_tokens=450, temperature=0.4, timeout=40)
        if not result or result.startswith("❌"):
            return

        wins = sum(1 for e in closed if (e.get("realised_pnl") or 0) > 0)
        avg_pnl = (sum(e.get("realised_pnl_pct") or 0 for e in closed) / len(closed)) if closed else 0

        msg = (
            f"📅 <b>Monthly 复盘 — {datetime.now().strftime('%B %Y')}</b>\n"
            f"<i>{len(closed)} closed · {wins} wins · avg {avg_pnl:+.1f}% · {len(open_)} still open</i>\n\n"
            + result
        )
        send_telegram(msg)
        print(f"Monthly 复盘 sent for {datetime.now().strftime('%B %Y')}")
    except Exception as e:
        print(f"Monthly review error: {e}")


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

    # Holdings auto-reload — every 30 mins, so Notion edits (trades, ticker
    # fixes, watchlist adds) reach both scheduler.py and telegram_bot.py
    # without a manual "reload" in Telegram
    schedule.every(30).minutes.do(auto_reload_holdings)

    # Breaking news — every 2 hours, 7am-11pm HKT
    schedule.every(2).hours.do(check_breaking_news)

    # Market close alerts (UTC times)
    schedule.every().day.at("08:05").do(lambda: send_market_close_alert("HK"))   # HK close 16:00 HKT
    schedule.every().day.at("15:35").do(lambda: send_market_close_alert("EU"))   # EU close 23:35 HKT
    schedule.every().day.at("20:05").do(lambda: send_market_close_alert("US"))   # US close 04:05 HKT+1

    # Monthly 复盘 — 1st of each month, 9am HKT (01:00 UTC)
    schedule.every().day.at("01:00").do(_maybe_send_monthly_review)

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