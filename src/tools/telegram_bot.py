import os
import re
import json
import requests
import threading
from datetime import datetime
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
try:
    from langgraph.checkpoint.sqlite import SqliteSaver as _CheckpointSaver
    import os as _os
    _DB_DIR = "/app/data" if _os.path.exists("/app") else "."
    _os.makedirs(_DB_DIR, exist_ok=True)
    _MEMORY_BACKEND = "sqlite"
except ImportError:
    from langgraph.checkpoint.memory import MemorySaver as _CheckpointSaver
    _MEMORY_BACKEND = "memory"
from langchain_deepseek import ChatDeepSeek
from src.tools.notion_holdings import get_holdings_cached, FALLBACK_WATCHLIST
from src.tools.llm import call_deepseek, tavily_search
from src.tools.research_library import save_research

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ── State trackers ────────────────────────────────────────────────────────────
_last_ticker: dict = {}
_last_response: dict = {}


def load_watchlist():
    try:
        return get_holdings_cached()
    except Exception:
        return FALLBACK_WATCHLIST


WATCHLIST = load_watchlist()
WATCHLIST_TICKERS = list(WATCHLIST.keys())
WATCHLIST_TICKERS_SET = set(WATCHLIST_TICKERS)

# Pre-split into held positions and monitoring names
PORTFOLIO = {t: d for t, d in WATCHLIST.items() if (d.get("shares") or 0) > 0}
WATCHLIST_ONLY = {t: d for t, d in WATCHLIST.items() if (d.get("shares") or 0) == 0}


def fmt(ticker: str) -> str:
    t = ticker.upper()
    name = WATCHLIST.get(t, {}).get("name", "")
    return f"{t} ({name})" if name else t


def build_keyboard(chat_id: str = None) -> dict:
    """Build inline keyboard — Deep Dive button shows last ticker if known."""
    last = _last_ticker.get(chat_id) if chat_id else None
    deep_dive_text = f"🔍 {last}" if last else "🔍 Deep Dive"
    deep_dive_data = f"deepdive:{last}" if last else "deepdive"
    return {
        "inline_keyboard": [
            [
                {"text": "💼 Portfolio",    "callback_data": "portfolio"},
                {"text": "📋 Watchlist",    "callback_data": "watchlist"},
            ],
            [
                {"text": "🌅 Briefing",     "callback_data": "briefing"},
                {"text": "📅 Earnings",     "callback_data": "earnings"},
            ],
            [
                {"text": deep_dive_text,    "callback_data": deep_dive_data},
                {"text": "📐 Quant Screen", "callback_data": "quant_screen"},
            ],
            [
                {"text": "🤖 AI Picks",     "callback_data": "ai_picks"},
                {"text": "🎓 Explain",      "callback_data": "explain"},
            ],
        ]
    }


def extract_ticker(text: str, chat_id: str = None) -> str | None:
    bold_matches = re.findall(r'<b>([A-Z]{1,6})(?:\s|\(|<)', text)
    for m in bold_matches:
        if m in WATCHLIST_TICKERS_SET:
            if chat_id:
                _last_ticker[chat_id] = m
            return m
    words = re.findall(r'\b([A-Z]{2,6})\b', text)
    for w in words:
        if w in WATCHLIST_TICKERS_SET:
            if chat_id:
                _last_ticker[chat_id] = w
            return w
    return None


# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are an AI investment research assistant and multi-asset portfolio manager.

This portfolio runs MULTIPLE independent theses — not just AI:
• <b>AI Infrastructure</b> — NVDA, AMD, ALAB, CRDO, TSM, ASML, ARM, AVGO
• <b>Memory Cycle</b> — MU, WDC, SNDK (DRAM/NAND pricing recovery)
• <b>Energy & Power</b> — GEV, BE, CEG, VST, TLN (grid capex, nuclear)
• <b>Banks & Rates</b> — JPM, GS, MS (rate normalisation, M&A)
• <b>Space</b> — RKLB, ASTS (direct-to-cell, launch deflation)
• <b>Networking & Optical</b> — GLW, LITE, CSCO (800G optical cycle)
• <b>Software & Data</b> — PLTR, APP, MSFT, META, GOOGL

CRITICAL: Frame every position within its PRIMARY thesis. MU moves on DRAM pricing, not NVDA. GEV moves on grid capex. GS moves on M&A and yield curve. Treat each thesis independently.

Always use tools for live data — never fabricate prices or news.

COMPANY ANALYSIS: Always cover (1) peer group by business line — name the closest competitor for each revenue segment, and (2) where competition is intense vs where they have breathing room.

GUT CHECKS: When the user expresses an instinct or opinion, pressure-test it: what the data supports, what challenges it, and your direct verdict. Never hedge with "it depends."

VALUATION: Never show multiples in isolation. Always compare to 2-3 peers — forward P/E, EV/EBITDA, revenue growth — and give a verdict on whether the premium/discount is justified. Use get_valuation for peer data.

POST-EARNINGS: Always explain counter-intuitive moves (beat but down / miss but up). Cover actual vs expected, guidance vs consensus, valuation premium effect, and whether the move is an overreaction.

FORMATTING — no exceptions:
- No markdown tables, no ### headers, no --- dividers, no - bullets (use •)
- Bold: <b>text</b> · Italic: <i>text</i>
- Each price on its own line: 📈 <b>{fmt("NVDA")}</b>: $204.65 (+1.33%)
- Always show ticker with company name: {fmt("NVDA")} not just NVDA
- Respond in English unless user writes in Chinese"""

# ── Telegram Helpers ──────────────────────────────────────────────────────────

def clean_for_telegram(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'#{1,6}\s+', '', text)
    text = re.sub(r'\|[^\n]+\|', '', text)
    text = re.sub(r'-{3,}', '—', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def send_message(text: str, chat_id: str = None, show_buttons: bool = True):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    cleaned = clean_for_telegram(text)
    chunks = [cleaned[i:i+4000] for i in range(0, len(cleaned), 4000)]
    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": chat_id or TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
        }
        if show_buttons and i == len(chunks) - 1:
            payload["reply_markup"] = json.dumps(build_keyboard(chat_id or TELEGRAM_CHAT_ID))
        requests.post(url, json=payload)


def answer_callback(callback_query_id: str):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
        json={"callback_query_id": callback_query_id}
    )


def get_updates(offset: int = 0) -> list:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    r = requests.get(url, params={
        "offset": offset,
        "timeout": 30,
        "allowed_updates": ["message", "callback_query"]
    })
    return r.json().get("result", []) if r.status_code == 200 else []


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def deep_dive(ticker: str) -> str:
    """Full AI research report: bull/bear case, catalysts, valuation, verdict. Use for 'deep dive', 'analyse', 'research X'."""
    from src.tools.deep_dive import deep_dive as _deep_dive
    result = _deep_dive(ticker.upper())
    try:
        save_research(ticker.upper(), "deep_dive", result)
    except Exception as e:
        print(f"[telegram_bot:deep_dive] save_research error: {e}")
    return result


@tool
def get_price(ticker: str) -> str:
    """Live price, daily change, 52w high/low, P/E for a ticker."""
    from src.tools.prices import get_live_prices
    data = get_live_prices([ticker.upper()], detailed=True).get(ticker.upper(), {})
    if not data:
        return f"Could not fetch price for {fmt(ticker)}."
    direction = "📈" if (data.get("change_pct") or 0) > 0 else "📉"
    return (
        f"{direction} <b>{fmt(ticker)}</b>\n"
        f"Price: <b>${data.get('price')}</b>\n"
        f"Today: <b>{data.get('change_pct'):+.2f}%</b>\n"
        f"52w High: ${data.get('week52_high')}\n"
        f"52w Low: ${data.get('week52_low')}\n"
        f"P/E: {data.get('pe_ratio')}"
    )


@tool
def get_news(ticker: str = None) -> str:
    """Latest news for a ticker, or macro news if no ticker given."""
    from src.tools.news_fetcher import get_news_for_tickers, get_macro_news
    if ticker:
        t = ticker.upper()
        articles = get_news_for_tickers([t]).get(t, [])
        if articles:
            msg = f"🗞 <b>Latest news: {fmt(t)}</b>\n\n"
            for a in articles[:5]:
                msg += f"• <b>{a['title']}</b>\n"
                if a.get("content"):
                    msg += f"  <i>{a['content'][:150].strip()}...</i>\n\n"
            return msg
        else:
            return f"No recent search results for {fmt(t)}. Provide a brief summary from your training knowledge about recent {fmt(t)} developments instead."
    else:
        articles = get_macro_news()
        msg = "🌍 <b>Market & Macro News</b>\n\n"
        for a in articles[:5]:
            msg += f"• <b>{a['title']}</b>\n"
            if a.get("content"):
                msg += f"  <i>{a['content'][:150].strip()}...</i>\n\n"
        return msg


@tool
def get_earnings_calendar() -> str:
    """Upcoming earnings dates for all watchlist stocks within 60 days."""
    from src.tools.earnings_calendar import get_earnings_dates
    dates = get_earnings_dates(WATCHLIST_TICKERS)
    msg = "📅 <b>Earnings Calendar</b>\n\n"
    upcoming = [
        (t, d) for t, d in dates.items()
        if d.get("days_until") is not None and d.get("days_until") >= 0
    ]
    upcoming.sort(key=lambda x: x[1]["days_until"])
    if upcoming:
        for ticker, data in upcoming:
            alert = " ⚠️ SOON" if data["alert"] else ""
            msg += f"• <b>{fmt(ticker)}</b>: {data['date']} ({data['days_until']} days){alert}\n"
    else:
        msg += "No upcoming earnings found in next 60 days."
    return msg


@tool
def get_portfolio() -> str:
    """Held positions with live prices, dollar value, P&L vs avg cost. Use for 'portfolio', 'holdings', 'how am I doing'."""
    from src.tools.prices import get_live_prices
    prices = get_live_prices(list(PORTFOLIO.keys()))
    msg = f"💼 <b>Portfolio — {len(PORTFOLIO)} Held Positions</b>\n"
    msg += f"<i>{datetime.now().strftime('%d %b %Y, %H:%M')}</i>\n\n"

    rows = []
    total_value = 0.0
    total_cost = 0.0
    winners = losers = 0

    for t, d in prices.items():
        if not d:
            continue
        shares = PORTFOLIO.get(t, {}).get("shares", 0)
        avg_cost = PORTFOLIO.get(t, {}).get("avg_cost", 0)
        price = d.get("price") or 0
        value = shares * price
        cost_basis = shares * avg_cost
        dollar_pnl = value - cost_basis
        pnl_pct = ((price - avg_cost) / avg_cost * 100) if avg_cost else 0
        total_value += value
        total_cost += cost_basis
        if pnl_pct >= 0:
            winners += 1
        else:
            losers += 1
        rows.append((t, d, price, value, dollar_pnl, pnl_pct))

    # Sort by position value descending
    rows.sort(key=lambda x: -x[3])

    # Table header
    msg += "<code>"
    msg += f"{'':10}{'today':>7}  {'P&L':>7}\n"
    msg += f"{'-'*27}\n"

    for t, d, price, value, dollar_pnl, pnl_pct in rows:
        chg = d.get("change_pct") or 0
        weight = (value / total_value * 100) if total_value else 0
        price_str = f"${price/1000:.1f}k" if price >= 1000 else f"${price:.0f}"
        left = f"{t:<5}{weight:.1f}%"
        today_str = f"{chg:+.1f}%"
        pnl_str = f"{pnl_pct:+.1f}%"
        msg += f"{left:<10}{today_str:>7}  {pnl_str:>7}\n"

    msg += "</code>"

    if total_value > 0:
        total_pnl = total_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        msg += (
            f"\n<b>${total_value:,.0f} total</b>  "
            f"{pnl_emoji} <b>{total_pnl_pct:+.1f}% all-in</b>\n"
            f"<i>{winners} up · {losers} down</i>"
        )
    return msg


@tool
def get_watchlist() -> str:
    """Monitoring names not yet held — live prices and ratings."""
    from src.tools.prices import get_live_prices
    prices = get_live_prices(list(WATCHLIST_ONLY.keys()))
    msg = f"👁 <b>Watchlist — {len(WATCHLIST_ONLY)} Monitoring</b>\n"
    msg += f"<i>{datetime.now().strftime('%d %b %Y, %H:%M')}</i>\n\n"
    for t, d in prices.items():
        if not d:
            continue
        rating = WATCHLIST_ONLY.get(t, {}).get("rating", "")
        direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
        rating_tag = f" <i>[{rating}]</i>" if rating else ""
        msg += f"{direction} <b>{fmt(t)}</b>: ${d.get('price')} ({d.get('change_pct'):+.2f}%){rating_tag}\n"
    return msg


@tool
def get_market_briefing() -> str:
    """Top portfolio moves + macro news snapshot. Use for 'market update', 'what happened today'."""
    from src.tools.news_fetcher import get_macro_news
    from src.tools.prices import get_live_prices
    held_tickers = list(PORTFOLIO.keys())[:8]
    prices = get_live_prices(held_tickers)
    macro = get_macro_news()
    msg = f"🌅 <b>Market Briefing — {datetime.now().strftime('%d %B %Y')}</b>\n\n"
    msg += "<b>Top Portfolio Moves:</b>\n"
    for t, d in prices.items():
        if not d:
            continue
        direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
        msg += f"{direction} <b>{fmt(t)}</b>: ${d.get('price')} ({d.get('change_pct'):+.2f}%)\n"
    msg += "\n<b>Macro & Market News:</b>\n"
    for a in macro[:3]:
        msg += f"• <b>{a['title']}</b>\n"
        if a.get("content"):
            msg += f"  <i>{a['content'][:150].strip()}...</i>\n\n"
    return msg


@tool
def get_sec_filings(ticker: str) -> str:
    """Recent SEC filings: 10-K, 10-Q, 8-K dates for a company."""
    from src.tools.sec_filings import get_filing_summary
    summary = get_filing_summary(ticker.upper())
    msg = f"📄 <b>SEC Filings: {fmt(ticker)}</b>\n\n"
    msg += f"• Latest 10-K: {summary['10-K'][0]['date'] if summary['10-K'] else 'N/A'}\n"
    msg += f"• Recent 10-Qs: {', '.join([f['date'] for f in summary['10-Q']]) or 'N/A'}\n"
    msg += f"• Recent 8-Ks: {', '.join([f['date'] for f in summary['8-K']]) or 'N/A'}\n"
    return msg


# ── Agent Setup ───────────────────────────────────────────────────────────────

llm = ChatDeepSeek(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    temperature=0.3,
)

@tool
def get_valuation(ticker: str) -> str:
    """P/E, fwd P/E, PEG, EV/EBITDA, P/B, margins, ROE vs peers. Bank-aware (P/TBV + ROE). Use for 'is X cheap/expensive'."""
    from src.tools.valuation import get_valuation_message
    return get_valuation_message(ticker.upper())


@tool
def check_risk() -> str:
    """Concentration by theme, correlated pairs (>70%), single-stock flags. Use for 'check my risk', 'am I diversified'."""
    from src.tools.risk import get_risk_report
    from src.tools.prices import get_live_prices
    held_tickers = list(PORTFOLIO.keys())
    prices = get_live_prices(held_tickers)
    return get_risk_report(WATCHLIST, prices)


@tool
def get_catalyst_calendar(days_ahead: int = 60) -> str:
    """Forward events: FOMC, GTC/Computex/Hot Chips, export control dates, earnings. Use for 'what's coming up', 'any catalysts'."""
    from src.tools.catalyst_calendar import get_catalyst_calendar as _gc
    return _gc(list(PORTFOLIO.keys()), days_ahead)


@tool
def earnings_reaction(ticker: str) -> str:
    """Post-earnings move analysis: actual vs expected, guidance vs consensus, whether the move is justified. Use for 'why did X drop/rally after earnings'."""
    from src.tools.prices import get_live_prices
    from src.tools.news_fetcher import get_news_for_tickers
    from concurrent.futures import ThreadPoolExecutor

    ticker = ticker.upper()

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_price = ex.submit(get_live_prices, [ticker], True)
        f_news  = ex.submit(get_news_for_tickers, [ticker])

    try:
        price_data  = f_price.result(timeout=20).get(ticker, {})
    except Exception as e:
        print(f"[telegram_bot:earnings_reaction] price fetch error: {e}")
        price_data = {}
    try:
        news_items  = f_news.result(timeout=20).get(ticker, [])
    except Exception as e:
        print(f"[telegram_bot:earnings_reaction] news fetch error: {e}")
        news_items = []

    price_context = (
        f"Current price: ${price_data.get('price', 'N/A')}\n"
        f"Today's move: {price_data.get('change_pct', 'N/A')}%\n"
        f"52w High: ${price_data.get('week52_high', 'N/A')} | 52w Low: ${price_data.get('week52_low', 'N/A')}\n"
        f"P/E: {price_data.get('pe_ratio', 'N/A')} | Market cap: ${(price_data.get('market_cap') or 0):,.0f}"
    )

    news_context = ""
    for a in news_items[:6]:
        news_context += f"• {a['title']}\n"
        if a.get('content'):
            news_context += f"  {a['content'][:250]}\n"

    prompt = (
        f"You are a senior equity analyst explaining {ticker}'s post-earnings move to a portfolio manager.\n\n"
        f"MARKET DATA:\n{price_context}\n\n"
        f"RECENT NEWS & EARNINGS COVERAGE:\n{news_context or 'No news found — use training knowledge.'}\n\n"
        f"Give a structured earnings reaction analysis:\n\n"
        f"<b>1. WHAT HAPPENED</b>\n"
        f"Actual results vs expectations — revenue beat/miss, earnings beat/miss, by how much. "
        f"What did guidance say vs what the market was pricing in?\n\n"
        f"<b>2. WHY THE STOCK MOVED THIS WAY</b>\n"
        f"Explain the logic, especially if counter-intuitive (beat but down / miss but up). "
        f"Cover: guidance disappointment, valuation premium effect (expensive stocks need blowouts), "
        f"sell-the-news dynamics, thin pre-market volume if relevant.\n\n"
        f"<b>3. IS THE MOVE JUSTIFIED?</b>\n"
        f"Is this a rational re-rating or an overreaction? Be direct and opinionated.\n\n"
        f"<b>4. THE SETUP FROM HERE</b>\n"
        f"What should an investor watch at the open / over the next session? "
        f"Is this a buy-the-dip setup or does the fundamental case look impaired?\n\n"
        f"Max 300 words. Be direct. Use <b>bold</b> for key numbers and verdicts."
    )

    try:
        analysis = call_deepseek(prompt, max_tokens=500, temperature=0.3, timeout=45)
        if analysis.startswith("❌"):
            return analysis
        return f"📊 <b>Earnings Reaction: {ticker}</b>\n\n{analysis}"
    except Exception as e:
        return f"❌ Error: {str(e)[:150]}"


@tool
def get_portfolio_advice(ticker: str) -> str:
    """Buy/pass verdict, position sizing, 腾空间 (what to trim to fund it). Use for 'should I buy X', 'thinking of adding X'."""
    from src.tools.prices import get_live_prices
    from src.tools.notion_holdings import get_holdings_cached
    from src.tools.scheduler import PORTFOLIO_CATEGORIES

    ticker = ticker.upper()
    holdings = get_holdings_cached()
    held = {t: d for t, d in holdings.items() if (d.get("shares") or 0) > 0}
    all_tickers = list(held.keys()) + ([ticker] if ticker not in held else [])

    prices = get_live_prices(all_tickers)

    # Compute portfolio value and allocations
    total_value = 0.0
    positions = {}
    for t, d in held.items():
        p = prices.get(t, {}).get("price") or 0
        shares = d.get("shares") or 0
        avg = d.get("avg_cost") or 0
        val = p * shares
        total_value += val
        pnl = ((p - avg) / avg * 100) if avg else 0
        positions[t] = {
            "name": d.get("name", t),
            "sector": d.get("sector", ""),
            "value": val,
            "pnl": pnl,
            "shares": shares,
            "avg_cost": avg,
            "price": p,
            "rating": d.get("rating", ""),
        }

    # Category breakdown
    cat_map = {}
    for cat, members in PORTFOLIO_CATEGORIES.items():
        cat_val = sum(positions[t]["value"] for t in members if t in positions)
        if cat_val > 0:
            cat_map[cat] = cat_val

    cat_text = ""
    for cat, val in sorted(cat_map.items(), key=lambda x: -x[1]):
        pct = val / total_value * 100 if total_value else 0
        cat_text += f"  {cat}: {pct:.1f}% (${val:,.0f})\n"

    # Top 10 positions by size
    top10 = sorted(positions.items(), key=lambda x: -x[1]["value"])[:10]
    top10_text = ""
    for t, d in top10:
        pct = d["value"] / total_value * 100 if total_value else 0
        top10_text += f"  {t} ({d['name']}): {pct:.1f}% • P&L {d['pnl']:+.1f}% • {d['sector']}\n"

    # Candidates with big gains (trim candidates)
    gainers = sorted(positions.items(), key=lambda x: -x[1]["pnl"])
    trim_candidates = ""
    for t, d in gainers[:6]:
        pct = d["value"] / total_value * 100 if total_value else 0
        trim_candidates += f"  {t}: P&L {d['pnl']:+.1f}% ({pct:.1f}% of portfolio)\n"

    # Candidate ticker info
    cand = holdings.get(ticker, {})
    cand_price = prices.get(ticker, {})
    cand_text = (
        f"Ticker: {ticker}\n"
        f"Name: {cand.get('name', 'Unknown')}\n"
        f"Sector: {cand.get('sector', 'Unknown')}\n"
        f"Rating: {cand.get('rating', 'Not in watchlist')}\n"
        f"Current price: ${cand_price.get('price', 'N/A')}\n"
        f"Today: {cand_price.get('change_pct', 'N/A')}%\n"
        f"Already held: {'Yes — ' + str(cand.get('shares', 0)) + ' shares' if ticker in held else 'No'}\n"
        f"Thesis: {cand.get('thesis', 'None on file')[:200]}\n"
    )

    prompt = (
        f"You are a senior portfolio manager advising on whether to add {ticker} to the portfolio.\n\n"
        f"PORTFOLIO SUMMARY:\n"
        f"Total value: ${total_value:,.0f} across {len(held)} positions\n\n"
        f"CATEGORY ALLOCATION:\n{cat_text}\n"
        f"TOP 10 POSITIONS:\n{top10_text}\n"
        f"BIGGEST WINNERS (trim candidates for 腾空間):\n{trim_candidates}\n"
        f"CANDIDATE:\n{cand_text}\n"
        f"Answer these questions directly:\n"
        f"1. <b>BUY or PASS?</b> — Does {ticker} fit the portfolio? Any concentration risk?\n"
        f"2. <b>Position size</b> — If buying, how much? (% of portfolio, rough $ amount at ${total_value:,.0f} total)\n"
        f"3. <b>腾空間 — Make room?</b> — Should you sell something first to fund it? "
        f"If yes: which specific position to trim, how much, and why that one?\n"
        f"4. <b>Timing</b> — Buy now or wait for a better entry?\n\n"
        f"Max 250 words. Be specific and opinionated. Use <b>bold</b> for tickers and key verdicts. "
        f"No generic advice."
    )

    try:
        advice = call_deepseek(prompt, max_tokens=450, temperature=0.3, timeout=45)
        if advice.startswith("❌"):
            return advice
        return f"🧠 <b>Portfolio Advisor: {ticker}</b>\n\n{advice}"
    except Exception as e:
        return f"❌ Error: {str(e)[:150]}"


@tool
def get_ficc_data() -> str:
    """US yield curve, credit spreads, policy rates, key FX pairs. Use for 'rates', 'bonds', 'yield curve', 'dollar'."""
    from src.tools.ficc import get_ficc_message
    return get_ficc_message()


@tool
def get_earnings_transcript(ticker: str) -> str:
    """Earnings call summary: CEO tone, guidance vs expectations, capex language, key risk, best analyst Q&A. Use for 'what did management say', 'transcript', 'call highlights'."""
    ticker = ticker.upper()

    # Fetch transcript content via Tavily
    transcript_text = ""
    try:
        results = tavily_search(
            f"{ticker} earnings call transcript CEO guidance capex {datetime.now().year} Q1 Q2",
            max_results=5,
            search_depth="advanced",
            timeout=12,
        )
        for a in results[:4]:
            transcript_text += f"SOURCE: {a.get('title', '')}\n"
            if a.get("content"):
                transcript_text += a["content"][:600] + "\n\n"
    except Exception as e:
        print(f"[telegram_bot:get_earnings_transcript] Tavily fetch error: {e}")

    if not transcript_text:
        transcript_text = "No transcript found — summarise based on training knowledge of recent earnings."

    prompt = (
        f"You are a senior equity analyst summarising {ticker}'s most recent earnings call.\n\n"
        f"TRANSCRIPT EXCERPTS:\n{transcript_text}\n\n"
        f"Start with ONE headline sentence (no label, no bullet): what were the market expectations going in "
        f"(consensus EPS and revenue estimates), did {ticker} beat or miss, and what was the stock's immediate reaction. "
        f"This must be the very first line.\n\n"
        f"Then extract these 5 elements:\n\n"
        f"<b>1. CEO TONE</b> — Bullish / Neutral / Cautious? What was the overall message?\n\n"
        f"<b>2. GUIDANCE</b> — What did management say about next quarter / full year revenue and EPS? "
        f"Was it above, in-line, or below expectations? Quote specific numbers if available.\n\n"
        f"<b>3. CAPEX & INVESTMENT</b> — What are they spending on? Any change in investment plans? "
        f"Specific $ amounts if mentioned.\n\n"
        f"<b>4. KEY RISK FLAGGED</b> — What risk or uncertainty did management highlight most? "
        f"Exact language matters here.\n\n"
        f"<b>5. BEST ANALYST Q&A</b> — One exchange that revealed the most about the business. "
        f"Who asked, what they asked, what management said.\n\n"
        f"Max 300 words total. Be specific — use numbers and direct quotes where possible. "
        f"Use <b>bold</b> for key figures and verdicts."
    )

    try:
        analysis = call_deepseek(prompt, max_tokens=550, temperature=0.2, timeout=40)
        if analysis.startswith("❌"):
            return analysis
        result = f"📞 <b>Earnings Call: {fmt(ticker)}</b>\n\n{analysis}"
        try:
            save_research(ticker, "earnings", result)
        except Exception as e:
            print(f"[telegram_bot:get_earnings_transcript] save_research error: {e}")
        # Auto-extract and log beat/miss to earnings tracker
        try:
            _auto_log_earnings_surprise(ticker, transcript_text, analysis)
        except Exception as e:
            print(f"[telegram_bot:get_earnings_transcript] auto_log error: {e}")
        return result
    except Exception as e:
        return f"❌ Error: {str(e)[:150]}"


def _auto_log_earnings_surprise(ticker: str, transcript_text: str, analysis: str):
    """Extract beat/miss + surprise %s from transcript analysis and auto-log to earnings tracker."""
    import json as _json
    extract_prompt = (
        f"From this earnings call analysis for {ticker}, extract structured data.\n\n"
        f"ANALYSIS:\n{analysis[:1500]}\n\n"
        f"Return ONLY a JSON object with these exact keys (use null if not found):\n"
        f'{{"period": "Q1 2025", "beat_miss": "Beat", '
        f'"rev_surprise_pct": 3.2, "eps_surprise_pct": 5.1, "stock_reaction": -2.0}}\n\n'
        f"beat_miss must be exactly one of: Beat, Miss, In-line\n"
        f"period format: Q1 2025 / Q2 2025 / FY2025\n"
        f"surprise %s: positive = above consensus, negative = below\n"
        f"stock_reaction: next-day % move if mentioned, else null\n"
        f"Return ONLY the JSON, no explanation."
    )
    raw = call_deepseek(extract_prompt, max_tokens=100, temperature=0.0, timeout=15)
    if raw.startswith("❌"):
        return
    # Strip markdown code fences if present
    raw = raw.strip("`").replace("json\n", "").strip()
    data = _json.loads(raw)
    period   = data.get("period")
    beat_miss = data.get("beat_miss")
    if not period or not beat_miss:
        return
    from src.tools.research_library import log_earnings_surprise as _les
    _les(
        ticker=ticker,
        period=period,
        beat_miss=beat_miss,
        rev_surprise_pct=data.get("rev_surprise_pct"),
        eps_surprise_pct=data.get("eps_surprise_pct"),
        stock_reaction=data.get("stock_reaction"),
        notes="auto-logged from transcript",
    )


@tool
def update_rating(ticker: str, rating: str) -> str:
    """Update Notion rating for a ticker. Valid: Buy, Spec. Buy, Allocate, Hold, Watchlist, Researching, Sell."""
    from src.tools.notion_holdings import update_rating as _update_rating
    return _update_rating(ticker.upper(), rating)


@tool
def size_position(ticker: str, conviction: str = "medium") -> str:
    """
    Position sizing calculator: given a ticker and conviction level, returns recommended
    $ amount, share count, and % of portfolio using fixed-fractional sizing.
    conviction: 'high' (3-5%), 'medium' (1.5-3%), 'low' (0.5-1.5%).
    Use when user asks 'how much should I buy', 'how many shares of X', 'what size for X'.
    """
    from src.tools.prices import get_live_prices
    from src.tools.notion_holdings import get_holdings_cached

    ticker = ticker.upper()
    conv = conviction.lower().strip()

    holdings = get_holdings_cached()
    held = {t: d for t, d in holdings.items() if (d.get("shares") or 0) > 0}
    prices = get_live_prices(list(held.keys()) + ([ticker] if ticker not in held else []))

    # Portfolio value
    total_value = sum(
        (prices.get(t, {}).get("price") or 0) * (d.get("shares") or 0)
        for t, d in held.items()
    )
    if total_value == 0:
        return "❌ Could not calculate portfolio value — no price data."

    # Existing position size
    existing_shares = holdings.get(ticker, {}).get("shares") or 0
    cand_price = prices.get(ticker, {}).get("price") or 0
    existing_value = existing_shares * cand_price
    existing_pct = existing_value / total_value * 100 if total_value else 0

    # Fixed-fractional bands by conviction
    bands = {
        "high":   (0.03, 0.05),
        "medium": (0.015, 0.03),
        "low":    (0.005, 0.015),
    }
    low_pct, high_pct = bands.get(conv, bands["medium"])

    # Remaining room (headroom to max band)
    headroom_pct = max(0, high_pct - existing_pct / 100)
    low_add  = total_value * low_pct
    high_add = total_value * high_pct
    target_add = total_value * (low_pct + high_pct) / 2

    if cand_price <= 0:
        return f"❌ Could not fetch price for {ticker}."

    low_shares  = int(low_add / cand_price)
    high_shares = int(high_add / cand_price)
    mid_shares  = int(target_add / cand_price)

    # Rating and thesis from Notion
    info = holdings.get(ticker, {})
    rating = info.get("rating", "Not rated")
    thesis_text = info.get("thesis", "")

    conv_label = {"high": "High conviction (3–5%)", "medium": "Medium conviction (1.5–3%)", "low": "Low conviction (0.5–1.5%)"}.get(conv, conv)

    msg = f"📐 <b>Position Sizing: {fmt(ticker)}</b>\n"
    msg += f"<i>Portfolio: ${total_value:,.0f} · Price: ${cand_price} · Conviction: {conv_label}</i>\n\n"

    if existing_value > 0:
        msg += f"<b>Existing position:</b> {existing_shares:.0f} shares = ${existing_value:,.0f} ({existing_pct:.1f}% of portfolio)\n\n"

    msg += f"<b>Recommended add:</b>\n"
    msg += f"• Target: <b>{mid_shares} shares</b> ≈ <b>${target_add:,.0f}</b> ({(low_pct+high_pct)/2*100:.1f}% of portfolio)\n"
    msg += f"• Range: {low_shares}–{high_shares} shares (${low_add:,.0f}–${high_add:,.0f})\n\n"

    if existing_value > 0:
        new_total_pct = (existing_value + target_add) / total_value * 100
        msg += f"<b>After add:</b> {new_total_pct:.1f}% of portfolio in {ticker}\n"
        if new_total_pct > 10:
            msg += f"⚠️ Would exceed 10% single-name limit — consider splitting into 2 tranches\n"

    msg += f"\n<b>Rating:</b> {rating}"
    if thesis_text:
        msg += f"\n<b>Thesis:</b> <i>{thesis_text[:150]}{'…' if len(thesis_text) > 150 else ''}</i>"

    return msg


@tool
def set_thesis(ticker: str, thesis: str) -> str:
    """Update the Thesis (Durable) field for a ticker in Notion. Use when user says 'set thesis NVDA ...' or 'update thesis for MU ...'."""
    from src.tools.notion_holdings import update_thesis as _update_thesis
    return _update_thesis(ticker.upper(), thesis)


@tool
def search_research(ticker: str = "", query: str = "") -> str:
    """
    Search the research library for past deep dives, earnings notes, and saved research.
    Use ticker to find all research on a name, query for keyword search, or both.
    Use for 'what did I research on MU', 'show past deep dives', 'find notes on capex'.
    """
    from src.tools.research_library import search_research as _search, format_research_results, get_research_summary
    if not ticker and not query:
        summary = get_research_summary()
        if not summary:
            return "📚 <b>Research Library</b>\n\nNo saved research yet. Library auto-saves every deep dive and earnings call analysis."
        msg = "📚 <b>Research Library Index</b>\n\n"
        for row in summary[:20]:
            msg += f"• <b>{row['ticker']}</b> — {row['cnt']} entries · last {row['last']}\n"
        return msg
    rows = _search(query=query, ticker=ticker.upper() if ticker else "", limit=5)
    header = f"📚 <b>Research: {ticker.upper() if ticker else query}</b>\n\n"
    return header + format_research_results(rows)


@tool
def log_earnings_surprise(ticker: str, period: str, beat_miss: str,
                          rev_surprise_pct: float = None, eps_surprise_pct: float = None,
                          stock_reaction: float = None, notes: str = "") -> str:
    """Log an earnings beat/miss to the tracker. beat_miss: 'Beat'|'Miss'|'In-line'. Use when user says 'log earnings NVDA Q1 2026 beat rev+3% eps+5% stock-2%'."""
    from src.tools.research_library import log_earnings_surprise as _log
    return _log(ticker, period, beat_miss, rev_surprise_pct, eps_surprise_pct, stock_reaction, notes)


@tool
def get_earnings_history(ticker: str) -> str:
    """Show earnings beat/miss track record for a ticker. Use for 'earnings history NVDA', 'how many times has MU beaten'."""
    from src.tools.research_library import format_earnings_history
    return format_earnings_history(ticker)


@tool
def switch_account(account: str) -> str:
    """Switch active portfolio account filter. Use 'switch account IBKR', 'show IBKR portfolio', 'switch to Moomoo'. Pass 'all' to view all accounts."""
    from src.tools.notion_holdings import set_active_account, list_accounts, reload_holdings
    if account.lower() == "all":
        set_active_account("")
        return "✅ Now viewing <b>all accounts</b>."
    accounts = list_accounts()
    match = next((a for a in accounts if a.lower() == account.lower()), None)
    if not match and accounts:
        match = next((a for a in accounts if account.lower() in a.lower()), None)
    if match:
        set_active_account(match)
        return f"✅ Switched to account: <b>{match}</b>"
    accounts_str = ", ".join(accounts) if accounts else "none found (check Notion 'Account' field)"
    return f"❌ Account '{account}' not found. Available: {accounts_str}"


@tool
def list_portfolios() -> str:
    """List all portfolio accounts and position counts. Use for 'list accounts', 'show portfolios', 'which accounts do I have'."""
    from src.tools.notion_holdings import list_accounts, get_holdings_cached, get_active_account
    accounts = list_accounts()
    if not accounts:
        return "⚠️ No 'Account' field found in Notion Holdings. Add an 'Account' property (Select or Text) to each holding."
    active = get_active_account()
    all_holdings = get_holdings_cached(account_filter="")
    msg = f"🗂 <b>Portfolio Accounts</b>\n"
    msg += f"<i>Active filter: {active if active else 'All accounts'}</i>\n\n"
    for acc in accounts:
        items = {t: d for t, d in all_holdings.items() if d.get("account", "").lower() == acc.lower()}
        held = sum(1 for d in items.values() if d.get("shares", 0) > 0)
        watch = len(items) - held
        marker = " ◀ active" if acc.lower() == active.lower() else ""
        msg += f"• <b>{acc}</b> — {held} held, {watch} watchlist{marker}\n"
    msg += f"\n• <b>All</b> — {sum(1 for d in all_holdings.values() if d.get('shares',0)>0)} held, {sum(1 for d in all_holdings.values() if not d.get('shares',0))} watchlist"
    msg += "\n\n<i>Switch with: <code>switch account ACCOUNT_NAME</code></i>"
    return msg


@tool
def get_theme_health() -> str:
    """Weekly theme health scores 0–10 for each theme in your portfolio. Score = weekly price momentum + breadth (% of names positive). Use for 'theme health', 'which theme is strongest', 'theme scores'."""
    from src.tools.prices import get_live_prices
    from src.tools.themes import THESIS_MAP
    from src.tools.notion_holdings import get_holdings_cached
    holdings = get_holdings_cached()
    theme_tickers: dict[str, list] = {}
    for t, d in holdings.items():
        if (d.get("shares") or 0) <= 0:
            continue
        theme = THESIS_MAP.get(t, "Other")
        theme_tickers.setdefault(theme, []).append(t)
    if not theme_tickers:
        return "No held positions found."
    all_held = [t for tlist in theme_tickers.values() for t in tlist]
    prices_all = get_live_prices(all_held)
    scores = {}
    for theme, tlist in theme_tickers.items():
        if len(tlist) < 2:
            continue
        moves = [prices_all.get(t, {}).get("change_pct") or 0 for t in tlist]
        avg_move = sum(moves) / len(moves)
        breadth  = sum(1 for m in moves if m > 0) / len(moves)
        score = round(min(10, max(0, 5 + avg_move * 0.6)) * 0.6 + breadth * 10 * 0.4, 1)
        scores[theme] = {"score": score, "avg_move": avg_move, "breadth": breadth, "n": len(tlist)}
    if not scores:
        return "Not enough positions per theme to score (need ≥2 per theme)."
    msg = f"🧭 <b>Theme Health Scores</b>\n<i>{datetime.now().strftime('%d %b %Y')}</i>\n\n"
    for theme, s in sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True):
        bar   = "█" * int(s["score"] / 2) + "░" * (5 - int(s["score"] / 2))
        emoji = "🟢" if s["score"] >= 7 else ("🟡" if s["score"] >= 4 else "🔴")
        msg  += f"{emoji} <b>{theme}</b> {bar} {s['score']}/10\n"
        msg  += f"   {s['avg_move']:+.1f}% avg · {int(s['breadth']*100)}% names positive · {s['n']} held\n"
    return msg.strip()


@tool
def manage_watchlist_target(action: str, ticker: str, target_price: float = None,
                             direction: str = "below", note: str = "") -> str:
    """Set/remove price targets for watchlist names. action='set'|'remove'|'list'. direction='below' (buy dip) or 'above' (breakout). Use for 'alert me when MRVL hits 60', 'target MRVL below 60', 'remove target MRVL'."""
    from src.tools.alert_config import set_watchlist_target, remove_watchlist_target, format_watchlist_targets
    if action == "list":
        return format_watchlist_targets()
    if action == "remove":
        return remove_watchlist_target(ticker)
    if action == "set" and target_price:
        return set_watchlist_target(ticker, target_price, direction, note)
    return "❌ Usage: action='set'|'remove'|'list', ticker, target_price, direction='below'|'above'"


@tool
def get_market_open_brief(market: str = "US") -> str:
    """On-demand market open brief: pre-market movers, today's earnings, economic calendar. market='US' or 'HK'. Use for 'what's happening before US open', 'HK open brief', 'pre-market movers'."""
    from src.tools.scheduler import send_market_open_alert
    send_market_open_alert(market.upper())
    return f"✅ {market.upper()} market open brief sent to Telegram."


@tool
def get_macro_regime() -> str:
    """Macro regime detector: yield curve + credit spreads + Fed Funds → RISK-ON/RISK-OFF/EASING/STAGFLATION/LATE CYCLE label. Use for 'macro regime', 'risk-on or off', 'what is the macro environment'."""
    from src.tools.ficc import get_macro_regime as _gmr
    return _gmr()


@tool
def get_sector_rotation() -> str:
    """
    Sector rotation monitor: 5-day ETF performance across all major sectors, ranked best to worst.
    Flags if AI/tech is lagging while defensives or cyclicals lead — signals rotation out of theme.
    Use for 'sector rotation', 'where is money flowing', 'is tech losing momentum', 'macro rotation'.
    """
    import yfinance as yf
    from src.tools.scheduler import SECTOR_ETFS

    SECTOR_ETF_MAP = {**SECTOR_ETFS, **{
        "XLK": "Tech", "XLF": "Financials", "XLE": "Energy",
        "XLV": "Healthcare", "XLI": "Industrials", "XLU": "Utilities",
        "XLP": "Staples", "XLB": "Materials", "XLRE": "Real Estate",
        "XLC": "Comms", "XLY": "Discretionary",
    }}

    try:
        tickers = list(SECTOR_ETF_MAP.keys())
        data = yf.download(tickers, period="5d", progress=False, auto_adjust=True)["Close"]
        moves = []
        for t in tickers:
            if t not in data.columns:
                continue
            col = data[t].dropna()
            if len(col) < 2:
                continue
            chg = (col.iloc[-1] - col.iloc[0]) / col.iloc[0] * 100
            moves.append((SECTOR_ETF_MAP.get(t, t), chg, t))

        moves.sort(key=lambda x: -x[1])

        msg = f"🔄 <b>Sector Rotation — 5-Day Performance</b>\n"
        msg += f"<i>{datetime.now().strftime('%d %b %Y')}</i>\n\n"

        for label, chg, etf in moves:
            bar = "█" * min(int(abs(chg) * 2), 10)
            direction = "▲" if chg >= 0 else "▼"
            msg += f"{direction} <b>{label}</b>: {chg:+.2f}% {bar}\n"

        # Rotation signal
        tech_chg = next((c for l, c, _ in moves if "Tech" in l or "AI" in l), None)
        defensive = [(l, c) for l, c, _ in moves if l in ("Utilities", "Staples", "Healthcare")]
        def_avg = sum(c for _, c in defensive) / len(defensive) if defensive else 0

        msg += "\n"
        if tech_chg is not None and def_avg > tech_chg + 3:
            msg += "⚠️ <b>Rotation signal:</b> Defensives outperforming tech by {:.1f}pp — risk-off, watch AI positions closely.".format(def_avg - tech_chg)
        elif tech_chg is not None and tech_chg > def_avg + 3:
            msg += "✅ <b>Risk-on:</b> Tech leading defensives by {:.1f}pp — momentum favours AI theme.".format(tech_chg - def_avg)
        else:
            msg += "<i>No strong rotation signal — mixed market.</i>"

        return msg

    except Exception as e:
        return f"❌ Sector rotation error: {str(e)[:150]}"


@tool
def get_pnl_summary() -> str:
    """Full P&L snapshot: unrealised (all positions vs cost), top winners/losers, by sector, realised trades this week. Use for 'P&L', 'how am I doing overall', 'weekly P&L', 'realised vs unrealised'."""
    from src.tools.scheduler import _compute_portfolio_pnl
    return _compute_portfolio_pnl()


@tool
def manage_alerts(action: str, ticker: str = "", threshold: float = 0, direction: str = "both") -> str:
    """
    Manage custom price alerts. action: 'set', 'remove', 'list'.
    direction: 'up', 'down', or 'both'. threshold in percent (e.g. 5 = 5%).
    Use when user says 'alert me when NVDA drops 5%', 'set alert for MU up 8%', 'remove alert NVDA', 'show my alerts'.
    """
    from src.tools.alert_config import set_alert, remove_alert, format_alerts_list
    if action == "set":
        if not ticker or threshold <= 0:
            return "❌ Provide ticker and threshold. Example: set, NVDA, 5.0, down"
        return set_alert(ticker.upper(), threshold, direction)
    elif action == "remove":
        return remove_alert(ticker.upper())
    else:
        return format_alerts_list()


@tool
def save_note(ticker: str, note: str) -> str:
    """
    Save a manual research note or observation to the library for a ticker.
    Use when user says 'save a note on NVDA', 'remember this about MU', 'log this observation'.
    """
    save_research(ticker.upper(), "note", note)
    return f"📝 Note saved for <b>{ticker.upper()}</b>."


@tool
def get_theme_momentum(theme: str = "all") -> str:
    """GitHub commit velocity + arXiv paper volume per theme. Themes: AI Infrastructure, Memory Cycle, Networking & Optical, Software & Data, Quantum, Space, Energy & Power. Pass 'all' for full sweep."""
    from src.tools.momentum import get_theme_momentum as _gtm
    t = None if theme.lower() in ("all", "everything", "") else theme
    return _gtm(t)


@tool
def get_geopolitical_pulse() -> str:
    """Live geo snapshot: US Policy, China/Taiwan, Europe, Middle East — 1 market-impact sentence each."""
    from src.tools.scheduler import fetch_geopolitical_pulse
    pulse = fetch_geopolitical_pulse()
    if not pulse:
        return "🌍 No significant geopolitical developments found right now."
    return f"🌍 <b>Geopolitical Pulse</b>\n<i>{datetime.now().strftime('%d %b %Y, %H:%M')}</i>\n\n{pulse}"


@tool
def get_read_through(ticker: str) -> str:
    """Industry chain-reaction: when a trigger ticker moves, identify affected portfolio positions. Triggers: NVDA, AMD, TSM, ASML, MU, WDC, GEV, CEG, PLTR, ASTS, GLW, JPM, MSFT, META, GOOGL."""
    from src.tools.read_through import get_read_through_analysis
    t = re.sub(r'\s+(earnings|results|report|news|beat|miss|guidance).*$', '', ticker.strip(), flags=re.IGNORECASE).upper()
    held = list(PORTFOLIO.keys())
    return get_read_through_analysis(t, held)


@tool
def get_decision_journal(filter: str = "all") -> str:
    """Trade log with rationale and realised P&L. filter: 'open', 'closed', or 'all'."""
    from src.tools.notion_holdings import get_journal_entries

    status = None
    if "open" in filter.lower():
        status = "Open"
    elif "closed" in filter.lower() or "complet" in filter.lower():
        status = "Closed"

    entries = get_journal_entries(status=status, limit=15)
    if not entries:
        return (
            "📓 <b>Decision Journal</b>\n\nNo entries yet.\n\n"
            "Log trades with:\n"
            "<code>bought 100 MU at 82 — DRAM floor, buying the dip</code>\n"
            "<code>sold MU at 95 — thesis played out</code>"
        )

    label = {"Open": "Open trades", "Closed": "Closed trades"}.get(status, "Recent trades")
    msg = f"📓 <b>Decision Journal</b> — <i>{label}</i>\n\n"

    pnl_list = []
    open_count = closed_count = 0

    for page in entries:
        props = page.get("properties", {})

        ticker_rt = props.get("Ticker", {}).get("rich_text", [])
        ticker = ticker_rt[0]["plain_text"] if ticker_rt else "?"

        action = props.get("Action", {}).get("select", {}).get("name", "?")
        shares = props.get("Shares", {}).get("number") or 0
        entry_price = props.get("Entry Price", {}).get("number") or 0
        exit_price = props.get("Exit Price", {}).get("number")
        pnl = props.get("Realized PnL Pct", {}).get("number")
        trade_status = props.get("Status", {}).get("select", {}).get("name", "?")
        theme = props.get("Theme", {}).get("select", {}).get("name", "")
        rationale_rt = props.get("Rationale", {}).get("rich_text", [])
        rationale = rationale_rt[0]["plain_text"] if rationale_rt else ""

        # Header line
        msg += f"<b>{ticker}</b> {action} · {shares:.0f} shares @ ${entry_price:.2f}"
        if exit_price:
            msg += f" → ${exit_price:.2f}"
        msg += "\n"

        # Status / P&L line
        if trade_status == "Open":
            open_count += 1
            msg += f"<i>🟢 Open"
        else:
            closed_count += 1
            if pnl is not None:
                pnl_list.append(pnl)
                emoji = "🟢" if pnl >= 0 else "🔴"
                msg += f"<i>Closed {emoji} {pnl:+.1f}%"
            else:
                msg += "<i>Closed"
        if theme:
            msg += f" · {theme}"
        msg += "</i>\n"

        # Rationale (first 100 chars)
        if rationale:
            clean = rationale.split("\n\nEXIT:")[0].strip()
            msg += f"<i>{clean[:100]}{'…' if len(clean) > 100 else ''}</i>\n"
        msg += "\n"

    # Summary footer
    if pnl_list:
        avg = sum(pnl_list) / len(pnl_list)
        wins = sum(1 for p in pnl_list if p > 0)
        msg += f"<b>Win rate:</b> {wins}/{len(pnl_list)} · <b>Avg P&L:</b> {avg:+.1f}%\n"
    msg += f"<i>Open: {open_count} · Closed: {closed_count}</i>"
    return msg


@tool
def get_theme_analysis(theme: str) -> str:
    """Thesis health check for a theme: on track/watch/concern, latest signals, one thing to watch. Themes: AI Infrastructure, Memory Cycle, Energy & Power, Banks & Rates, Space, Networking & Optical, Software & Data, Quantum, Defence, Crypto."""
    from src.tools.themes import get_theme_analysis as _gta, get_tickers_by_theme
    from src.tools.prices import get_live_prices

    theme = theme.strip().title()
    # Fuzzy match common shorthand
    _aliases = {
        "Memory": "Memory Cycle", "Mem": "Memory Cycle", "Dram": "Memory Cycle",
        "Energy": "Energy & Power", "Power": "Energy & Power",
        "Banks": "Banks & Rates", "Bank": "Banks & Rates", "Rates": "Banks & Rates",
        "Ai": "AI Infrastructure", "Ai Infrastructure": "AI Infrastructure",
        "Networking": "Networking & Optical", "Optical": "Networking & Optical",
        "Software": "Software & Data", "Data": "Software & Data",
        "Space": "Space", "Satellite": "Space",
        "Crypto": "Crypto", "Bitcoin": "Crypto",
        "Defence": "Defence", "Defense": "Defence",
        "Quantum": "Quantum",
    }
    theme = _aliases.get(theme, theme)

    by_theme = get_tickers_by_theme(WATCHLIST)
    held_in_theme = by_theme.get(theme, [])
    if not held_in_theme:
        # Show available themes
        available = ", ".join(sorted(by_theme.keys()))
        return f"No held positions found for theme '{theme}'.\nActive themes in your book: {available}"

    prices = get_live_prices(held_in_theme)
    return _gta(theme, held_in_theme, prices)


@tool
def get_proactive_dive(ticker: str) -> str:
    """
    Run a quick 4-section analyst note on any company name spotted in news that isn't already in the portfolio or watchlist.
    Use when user asks 'tell me about [ticker]', 'quick look at [ticker]', or 'what is [ticker]' for an unfamiliar name.
    Also used automatically each morning for new names found in overnight news.
    """
    from src.tools.proactive_analyst import run_mini_dive
    t = ticker.strip().upper()
    result = run_mini_dive(t)
    return result or f"❌ Could not generate analyst note for {t}."


@tool
def get_theme_radar() -> str:
    """
    Scan ~55 sector + thematic ETFs for emerging themes moving outside the current portfolio.
    Uses Z-score momentum vs 52-week history + portfolio correlation filter.
    Works for ALL sectors: biotech, consumer, energy, EM, industrials — not just tech.
    Use when user says 'any new themes', 'what sectors are moving', 'theme radar', 'what am I missing'.
    """
    from src.tools.theme_radar import run_theme_radar
    held = [t for t, d in PORTFOLIO.items() if (d.get("shares") or 0) > 0]
    result = run_theme_radar(held)
    if not result:
        return "🔭 <b>Theme Radar</b>\n\nNo sectors firing above threshold this week. Everything moving is already in your portfolio or in normal range."
    return result


@tool
def get_monthly_review() -> str:
    """
    Monthly 复盘 — look-back on closed trades, best/worst decisions, and 3 lessons.
    Use when user says '复盘', 'monthly review', 'how did we do this month', 'what did we get wrong', 'look back'.
    """
    from src.tools.notion_holdings import get_journal_entries
    from src.tools.llm import call_deepseek

    entries = get_journal_entries()
    if not entries:
        return "📒 No journal entries found."

    closed = [e for e in entries if e.get("status", "").lower() == "closed" and e.get("realised_pnl") is not None]
    open_  = [e for e in entries if e.get("status", "").lower() == "open"]

    if not closed and not open_:
        return "📒 No trades in the journal yet."

    # Build context for DeepSeek
    closed_lines = []
    for e in sorted(closed, key=lambda x: x.get("opened", ""), reverse=True)[:20]:
        t = e.get("ticker", "?")
        pnl = e.get("realised_pnl", 0)
        pnl_pct = e.get("realised_pnl_pct", 0)
        rationale = e.get("rationale", "")[:120]
        opened = e.get("opened", "")
        closed_date = e.get("closed", "")
        icon = "🟢" if pnl > 0 else "🔴"
        closed_lines.append(f"{icon} {t}: {pnl_pct:+.1f}% | opened {opened} closed {closed_date} | {rationale}")

    open_lines = []
    for e in open_[:10]:
        t = e.get("ticker", "?")
        rationale = e.get("rationale", "")[:80]
        open_lines.append(f"• {t}: {rationale}")

    context = ""
    if closed_lines:
        context += "CLOSED TRADES:\n" + "\n".join(closed_lines) + "\n\n"
    if open_lines:
        context += "OPEN POSITIONS (still holding):\n" + "\n".join(open_lines) + "\n\n"

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
        return "❌ Could not generate review."

    header = f"📅 <b>Monthly 复盘</b>\n<i>{datetime.now().strftime('%B %Y')}</i>\n"
    stats = f"<i>{len(closed)} closed trades · {len(open_)} open positions</i>\n\n"

    if closed:
        wins = sum(1 for e in closed if (e.get("realised_pnl") or 0) > 0)
        avg_pnl = sum(e.get("realised_pnl_pct") or 0 for e in closed) / len(closed)
        stats = f"<i>{len(closed)} closed · {wins} wins · avg {avg_pnl:+.1f}% · {len(open_)} still open</i>\n\n"

    return header + stats + result


@tool
def get_quant_screen(universe: str = "notion") -> str:
    """
    Quant factor screen — ranks names by composite score (momentum 40%, quality 30%, value 30%).
    universe: 'notion' (default, 98 Notion names) or 'full' (S&P 500 + Notion, ~500 names).
    Use when user says 'quant screen', 'factor screen', 'quant rank', 'top quant picks',
    'quant scores', 'full universe screen', or asks for a quantitative view of the portfolio.
    """
    from src.tools.notion_holdings import get_all_holdings
    from src.tools.quant.signals import run_quant_screen
    from src.tools.quant.universe import get_universe
    holdings        = get_all_holdings()
    notion_tickers  = [h["ticker"] for h in holdings if h.get("ticker")]
    tickers         = get_universe(notion_tickers, mode=universe)
    if not tickers:
        return "❌ No tickers found."
    top_n = 15 if universe == "full" else 10
    return run_quant_screen(tickers, top_n=top_n)


@tool
def get_quant_signal(ticker: str) -> str:
    """
    Quant factor breakdown for a single ticker — momentum, value, quality z-scores,
    composite score, and rank within the universe.
    Use when user says 'quant signal TICKER', 'quant score TICKER', 'factor breakdown TICKER'.
    """
    from src.tools.notion_holdings import get_all_holdings
    from src.tools.quant.signals import run_single_signal
    holdings = get_all_holdings()
    tickers  = [h["ticker"] for h in holdings if h.get("ticker")]
    return run_single_signal(ticker.upper(), tickers)


@tool
def get_quant_optimize(total_value: float = 100000) -> str:
    """
    Portfolio optimizer — suggests max-Sharpe weights and exact share counts
    across buy-rated names in the Notion watchlist.
    Use when user says 'quant optimize', 'optimize portfolio', 'optimal weights',
    or 'how should I allocate across my watchlist'.
    Optional: pass total_value in USD (default 100000).
    """
    from src.tools.notion_holdings import get_all_holdings
    from src.tools.quant.optimizer import run_optimizer
    holdings = get_all_holdings()
    # Optimize across BUY-rated watchlist names + held positions
    tickers  = [
        h["ticker"] for h in holdings
        if h.get("ticker") and (h.get("rating", "").upper() == "BUY" or (h.get("shares") or 0) > 0)
    ]
    if len(tickers) < 3:
        return "❌ Need at least 3 BUY-rated or held names to optimize."
    return run_optimizer(tickers, total_value=float(total_value))


@tool
def get_quant_paper() -> str:
    """
    Quant paper portfolio — shows open simulated positions and recent closed trades with P&L.
    Use when user says 'paper portfolio', 'quant paper', 'paper trades', 'simulated portfolio'.
    To open: 'quant open TICKER'. To close: 'quant close TICKER'.
    """
    from src.tools.quant.paper_trade import get_paper_portfolio
    return get_paper_portfolio()


@tool
def get_quant_backtest(years: int = 2, universe: str = "notion") -> str:
    """
    Backtests the 12-1 momentum factor on the chosen universe using walk-forward monthly simulation.
    years: lookback period in years (default 2, max 5)
    universe: 'notion' (98 names) or 'full' (~500 names, takes longer)
    Use when user says 'backtest', 'quant backtest', 'test the strategy', 'how does momentum perform',
    'quant performance', 'validate the signal'.
    """
    from src.tools.notion_holdings import get_all_holdings
    from src.tools.quant.backtest import run_backtest
    from src.tools.quant.universe import get_universe
    holdings        = get_all_holdings()
    notion_tickers  = [h["ticker"] for h in holdings if h.get("ticker")]
    tickers         = get_universe(notion_tickers, mode=universe)
    y               = max(1, min(int(years), 5))
    return run_backtest(tickers, years=y)


@tool
def manage_quant_paper(action: str, ticker: str, shares: float = 100) -> str:
    """
    Open or close a quant paper trade.
    action: 'open' or 'close'
    ticker: stock ticker symbol
    shares: number of shares (default 100, only used when opening)
    Use when user says 'quant open TICKER', 'quant close TICKER',
    'paper buy TICKER', 'paper sell TICKER'.
    """
    from src.tools.quant.paper_trade import open_position, close_position
    a = action.strip().lower()
    t = ticker.upper().strip()
    if a == "open":
        return open_position(t, shares=shares)
    elif a == "close":
        return close_position(t)
    else:
        return f"❌ Unknown action '{action}'. Use 'open' or 'close'."


tools = [
    deep_dive,
    get_price,
    get_news,
    get_earnings_calendar,
    get_portfolio,
    get_watchlist,
    get_market_briefing,
    get_sec_filings,
    get_ficc_data,
    get_portfolio_advice,
    earnings_reaction,
    get_valuation,
    check_risk,
    get_catalyst_calendar,
    get_theme_analysis,
    get_theme_momentum,
    get_geopolitical_pulse,
    get_read_through,
    get_decision_journal,
    get_earnings_transcript,
    update_rating,
    set_thesis,
    size_position,
    search_research,
    save_note,
    manage_alerts,
    get_pnl_summary,
    get_sector_rotation,
    log_earnings_surprise,
    get_earnings_history,
    get_macro_regime,
    switch_account,
    list_portfolios,
    get_market_open_brief,
    manage_watchlist_target,
    get_theme_health,
    get_monthly_review,
    get_theme_radar,
    get_proactive_dive,
    get_quant_screen,
    get_quant_signal,
    get_quant_optimize,
    get_quant_backtest,
    get_quant_paper,
    manage_quant_paper,
]

if _MEMORY_BACKEND == "sqlite":
    import os as _os2
    _db_path = _os2.path.join(_DB_DIR, "agent_memory.db")
    _volume_mounted = _os2.path.exists("/app/data")
    memory = _CheckpointSaver.from_conn_string(_db_path)
    _persistence = "✅ PERSISTENT (Railway Volume)" if _volume_mounted else "⚠️ EPHEMERAL (mount /app/data volume in Railway to persist)"
    print(f"💾 Memory: SQLite ({_db_path}) — {_persistence}")
else:
    memory = _CheckpointSaver()
    print("💾 Memory: in-process (install langgraph-checkpoint-sqlite to upgrade)")
agent = create_react_agent(llm, tools, checkpointer=memory)


# ── Explain Helper ────────────────────────────────────────────────────────────

def _call_explain(last_response: str) -> str:
    """Call DeepSeek with junior investor educational prompt."""
    system = (
        "You are a patient investment teacher explaining things to a junior investor who is still learning. "
        "Given the information the bot just showed, explain: "
        "(1) what this means in plain English, "
        "(2) why it matters for the portfolio, "
        "(3) how an experienced portfolio manager would think about and act on this. "
        "Be specific, practical, and educational. Use simple language. "
        "Format for Telegram using <b>bold</b> for key concepts. Max 250 words."
    )
    try:
        result = call_deepseek(
            "Please explain this for me:\n\n" + last_response,
            system=system,
            max_tokens=400,
            temperature=0.4,
            timeout=30,
        )
        if result.startswith("❌"):
            return "Could not generate explanation."
        return result
    except Exception as e:
        return f"Explanation error: {str(e)[:100]}"


# ── Button Callback Handler ───────────────────────────────────────────────────

def handle_callback(callback_data: str, chat_id: str, callback_query_id: str):
    """Handle a button tap."""
    answer_callback(callback_query_id)

    if callback_data == "portfolio":
        send_message("⏳ Loading portfolio...", chat_id, show_buttons=False)
        handle_message("show my portfolio", chat_id)

    elif callback_data == "watchlist":
        send_message("⏳ Loading watchlist...", chat_id, show_buttons=False)
        handle_message("show my watchlist", chat_id)

    elif callback_data == "briefing":
        send_message("⏳ Generating briefing...", chat_id, show_buttons=False)
        handle_message("morning briefing", chat_id)

    elif callback_data == "earnings":
        send_message("⏳ Loading earnings calendar...", chat_id, show_buttons=False)
        handle_message("any earnings coming up", chat_id)

    elif callback_data == "quant_screen":
        send_message("⏳ Running quant factor screen...", chat_id, show_buttons=False)
        handle_message("quant screen", chat_id)

    elif callback_data == "ai_picks":
        send_message(
            "⏳ Running AI stock picks — Cathie Wood, Druckenmiller, Damodaran debating...",
            chat_id, show_buttons=False
        )
        handle_message("picks", chat_id)

    elif callback_data.startswith("deepdive:"):
        ticker = callback_data.split(":", 1)[1]
        send_message(f"⏳ Running deep dive on {ticker}...", chat_id, show_buttons=False)
        handle_message(f"deep dive {ticker}", chat_id)

    elif callback_data == "deepdive":
        send_message(
            "🔍 <b>Deep Dive</b>\n\nWhich ticker would you like to research?\n\n"
            "<i>Just type the ticker symbol, e.g. NVDA or ASML</i>",
            chat_id,
            show_buttons=False
        )

    elif callback_data == "explain":
        last = _last_response.get(chat_id)
        if not last:
            send_message(
                "No recent response to explain — ask me something first!",
                chat_id, show_buttons=False
            )
            return
        send_message("🎓 Explaining...", chat_id, show_buttons=False)
        explanation = _call_explain(last)
        send_message(
            "🎓 <b>Junior Investor Guide</b>\n\n" + explanation,
            chat_id, show_buttons=False
        )


# ── Message Handler ───────────────────────────────────────────────────────────

def handle_message(text: str, chat_id: str):
    try:
        lowered = text.strip().lower()

        if lowered == "/start":
            send_message(
                "🤖 <b>AI Investor — Welcome</b>\n\n"
                "Your personal AI research analyst. Ask me anything about your portfolio "
                "or tap a button below to get started.",
                chat_id
            )
            return

        if lowered in ("send briefing", "test briefing"):
            from src.tools.scheduler import send_morning_briefing
            send_message("⏳ Generating briefing now...", chat_id, show_buttons=False)
            send_morning_briefing()
            return

        if lowered in ("send alert", "test alert", "check alerts"):
            from src.tools.scheduler import check_alerts_report
            send_message("⏳ Checking price alerts...", chat_id, show_buttons=False)
            result = check_alerts_report()
            send_message(result, chat_id)
            return

        if lowered in ("market close", "us close", "hk close", "eu close", "close summary"):
            from src.tools.scheduler import send_market_close_alert
            market = "HK" if "hk" in lowered else "EU" if "eu" in lowered else "US"
            send_message(f"⏳ Building {market} close summary...", chat_id, show_buttons=False)
            send_market_close_alert(market)
            return

        if lowered in ("check news", "breaking news", "any news"):
            from src.tools.scheduler import check_breaking_news
            send_message("⏳ Scanning for breaking news...", chat_id, show_buttons=False)
            check_breaking_news()
            send_message("✅ News scan complete — anything market-moving was pushed above.", chat_id)
            return

        if lowered in ("geo pulse", "geopolitical", "geo risk", "geo update"):
            from src.tools.scheduler import fetch_geopolitical_pulse
            send_message("⏳ Fetching geopolitical pulse...", chat_id, show_buttons=False)
            pulse = fetch_geopolitical_pulse()
            msg = (f"🌍 <b>Geopolitical Pulse</b>\n<i>{datetime.now().strftime('%d %b %Y, %H:%M')}</i>\n\n{pulse}"
                   if pulse else "🌍 No significant geopolitical developments found right now.")
            send_message(msg, chat_id)
            return

        if lowered in ("weekly digest", "send digest", "weekly report"):
            from src.tools.scheduler import send_weekly_digest
            send_message("⏳ Generating weekly digest...", chat_id, show_buttons=False)
            send_weekly_digest()
            return

        # ── Notion write-back commands ─────────────────────────────────────────
        # Strip polite filler before matching
        _cleaned = lowered.strip()
        for _filler in (" please", " thanks", " thank you", " cheers"):
            if _cleaned.endswith(_filler):
                _cleaned = _cleaned[:-len(_filler)].rstrip()
        # Skip common filler words between "add" and the ticker
        _add_match    = re.match(r'^add\s+(?:(?:stock|ticker|equity|the|me|a)\s+)?([A-Za-z0-9.\-]+)(?:\s+to\s+(?:my\s+)?watchlist)?(?:\s+(.+))?$', _cleaned)
        _buy_match    = re.match(r'^(?:bought|buy|purchase[sd]?)\s+(\d+(?:\.\d+)?)\s+([A-Za-z0-9.\-]+)\s+(?:at|@)\s+\$?(\d+(?:\.\d+)?)(?:\s*[—\-]{1,2}\s*(.+))?$', _cleaned)
        _sell_match   = re.match(r'^(?:sold|sell|close[sd]?)\s+(?:all\s+)?(?:\d+\s+)?([A-Za-z0-9.\-]+)(?:\s+(?:at|@)\s+\$?(\d+(?:\.\d+)?))?(?:\s*[—\-]{1,2}\s*(.+))?$', _cleaned)
        _rate_match        = re.match(r'^rate\s+([A-Za-z0-9.\-]+)\s+(.+)$', _cleaned)
        _thesis_match      = re.match(r'^(?:set\s+)?thesis\s+([A-Za-z0-9.\-]+)\s+(.+)$', _cleaned)
        # log earnings NVDA Q1 2026 beat rev+3.2% eps+5% stock-2.1%
        _earn_log_match    = re.match(r'^log\s+earnings\s+([A-Za-z0-9.\-]+)\s+(Q[1-4]\s+\d{4}|\d{4}\s+Q[1-4]|FY\d{4})\s+(beat|miss|in-?line)(.*)?$', _cleaned, re.IGNORECASE)
        _earn_hist_match   = re.match(r'^(?:earnings\s+history|show\s+earnings)\s+([A-Za-z0-9.\-]+)$', _cleaned)
        _alert_set_match   = re.match(r'^alert\s+([A-Za-z0-9.\-]+)\s+(?:(up|down)\s+)?(\d+(?:\.\d+)?)%?$', _cleaned)
        _alert_rm_match    = re.match(r'^(?:remove|delete|cancel)\s+alert\s+([A-Za-z0-9.\-]+)$', _cleaned)
        _alert_list_match  = _cleaned in ("show alerts", "my alerts", "list alerts", "alerts")
        _reload_match      = _cleaned in ("reload holdings", "refresh holdings", "reload", "refresh watchlist")
        _switch_acct_match = re.match(r'^(?:switch\s+(?:account|portfolio|to)\s+|show\s+portfolio\s+)(.+)$', _cleaned, re.IGNORECASE)
        _list_acct_match   = _cleaned in ("list accounts", "list portfolios", "show accounts", "my accounts", "portfolios")
        _target_set_match  = re.match(r'^(?:target|watch\s+price|entry\s+target)\s+([A-Za-z0-9.\-]+)\s+(below|above|at|under|over)?\s*\$?(\d+(?:\.\d+)?)(.*)?$', _cleaned, re.IGNORECASE)
        _target_rm_match   = re.match(r'^(?:remove|delete|cancel)\s+target\s+([A-Za-z0-9.\-]+)$', _cleaned, re.IGNORECASE)
        _target_list_match = _cleaned in ("show targets", "my targets", "list targets", "watchlist targets", "targets")

        if _add_match:
            ticker = _add_match.group(1).upper()
            name = _add_match.group(2) or ""
            from src.tools.notion_holdings import add_to_watchlist
            result = add_to_watchlist(ticker, name.strip().title() if name else "")
            send_message(result, chat_id)
            return

        if _buy_match:
            shares = float(_buy_match.group(1))
            ticker = _buy_match.group(2).upper()
            avg_cost = float(_buy_match.group(3))
            rationale = (_buy_match.group(4) or "").strip()
            from src.tools.notion_holdings import update_position, log_trade_entry
            result = update_position(ticker, shares, avg_cost)
            journal_result = log_trade_entry(ticker, "Buy", shares, avg_cost, rationale)
            send_message(result + "\n" + journal_result, chat_id)
            return

        if _sell_match:
            ticker = _sell_match.group(1).upper()
            explicit_exit = _sell_match.group(2)
            exit_note = (_sell_match.group(3) or "").strip()
            from src.tools.notion_holdings import sell_position, close_trade_entry
            from src.tools.prices import get_live_prices
            result = sell_position(ticker)
            # Determine exit price: explicit or live
            if explicit_exit:
                exit_price = float(explicit_exit)
            else:
                price_data = get_live_prices([ticker], detailed=False).get(ticker, {})
                exit_price = price_data.get("price") or 0
            journal_result = close_trade_entry(ticker, exit_price, exit_note) if exit_price else "⚠️ Could not fetch exit price for journal."
            send_message(result + "\n" + journal_result, chat_id)
            return

        if _rate_match:
            ticker = _rate_match.group(1).upper()
            rating = _rate_match.group(2).strip()
            from src.tools.notion_holdings import update_rating as _update_rating
            result = _update_rating(ticker, rating)
            send_message(result, chat_id)
            return

        if _thesis_match:
            ticker = _thesis_match.group(1).upper()
            thesis = _thesis_match.group(2).strip()
            from src.tools.notion_holdings import update_thesis as _update_thesis
            result = _update_thesis(ticker, thesis)
            send_message(result, chat_id)
            return

        if _earn_log_match:
            import re as _re2
            ticker  = _earn_log_match.group(1).upper()
            period  = _earn_log_match.group(2).upper().replace("  ", " ")
            bm_raw  = _earn_log_match.group(3).lower()
            beat_miss = "Beat" if bm_raw == "beat" else ("Miss" if bm_raw == "miss" else "In-line")
            rest    = (_earn_log_match.group(4) or "").strip()
            rev  = float(m.group(1)) if (m := _re2.search(r'rev([+-]?\d+(?:\.\d+)?)%?', rest, re.IGNORECASE)) else None
            eps  = float(m.group(1)) if (m := _re2.search(r'eps([+-]?\d+(?:\.\d+)?)%?', rest, re.IGNORECASE)) else None
            stk  = float(m.group(1)) if (m := _re2.search(r'stock([+-]?\d+(?:\.\d+)?)%?', rest, re.IGNORECASE)) else None
            from src.tools.research_library import log_earnings_surprise as _les
            send_message(_les(ticker, period, beat_miss, rev, eps, stk, rest[:200]), chat_id)
            return

        if _earn_hist_match:
            ticker = _earn_hist_match.group(1).upper()
            from src.tools.research_library import format_earnings_history
            send_message(format_earnings_history(ticker), chat_id)
            return

        if _alert_set_match:
            ticker    = _alert_set_match.group(1).upper()
            direction = (_alert_set_match.group(2) or "both").lower()
            threshold = float(_alert_set_match.group(3))
            from src.tools.alert_config import set_alert as _set_alert
            send_message(_set_alert(ticker, threshold, direction), chat_id)
            return

        if _alert_rm_match:
            ticker = _alert_rm_match.group(1).upper()
            from src.tools.alert_config import remove_alert as _remove_alert
            send_message(_remove_alert(ticker), chat_id)
            return

        if _alert_list_match:
            from src.tools.alert_config import format_alerts_list
            send_message(format_alerts_list(), chat_id)
            return

        if _reload_match:
            from src.tools.notion_holdings import reload_holdings
            new_data = reload_holdings()
            # Update all module-level dicts in-place so agent sees fresh data immediately
            WATCHLIST.clear(); WATCHLIST.update(new_data)
            WATCHLIST_TICKERS[:] = list(new_data.keys())
            WATCHLIST_TICKERS_SET.clear(); WATCHLIST_TICKERS_SET.update(WATCHLIST_TICKERS)
            PORTFOLIO.clear(); PORTFOLIO.update({t: d for t, d in new_data.items() if (d.get("shares") or 0) > 0})
            WATCHLIST_ONLY.clear(); WATCHLIST_ONLY.update({t: d for t, d in new_data.items() if (d.get("shares") or 0) == 0})
            send_message(
                f"✅ Holdings reloaded from Notion.\n"
                f"<b>{len(PORTFOLIO)}</b> held positions · <b>{len(WATCHLIST_ONLY)}</b> watchlist",
                chat_id
            )
            return

        if _target_set_match:
            from src.tools.alert_config import set_watchlist_target
            ticker    = _target_set_match.group(1).upper()
            direction_raw = (_target_set_match.group(2) or "below").lower()
            direction = "above" if direction_raw in ("above", "over", "at") else "below"
            target    = float(_target_set_match.group(3))
            note      = (_target_set_match.group(4) or "").strip().lstrip("—- ")
            send_message(set_watchlist_target(ticker, target, direction, note), chat_id)
            return

        if _target_rm_match:
            from src.tools.alert_config import remove_watchlist_target
            send_message(remove_watchlist_target(_target_rm_match.group(1).upper()), chat_id)
            return

        if _target_list_match:
            from src.tools.alert_config import format_watchlist_targets
            send_message(format_watchlist_targets(), chat_id)
            return

        if _switch_acct_match:
            from src.tools.notion_holdings import set_active_account, list_accounts, get_holdings_cached
            acct = _switch_acct_match.group(1).strip()
            if acct.lower() == "all":
                set_active_account("")
                reply = "✅ Now viewing <b>all accounts</b>."
            else:
                accounts = list_accounts()
                match_a = next((a for a in accounts if a.lower() == acct.lower()), None)
                if not match_a:
                    match_a = next((a for a in accounts if acct.lower() in a.lower()), None)
                if match_a:
                    set_active_account(match_a)
                    filtered = get_holdings_cached()
                    held = sum(1 for d in filtered.values() if d.get("shares", 0) > 0)
                    reply = f"✅ Switched to <b>{match_a}</b> — {held} held positions."
                else:
                    avail = ", ".join(accounts) if accounts else "none (add 'Account' field in Notion)"
                    reply = f"❌ Account '{acct}' not found.\nAvailable: {avail}"
            send_message(reply, chat_id)
            return

        if _list_acct_match:
            from src.tools.notion_holdings import list_accounts, get_holdings_cached, get_active_account
            accounts = list_accounts()
            if not accounts:
                send_message("⚠️ No 'Account' field in Notion Holdings. Add a 'Account' Select property to use multi-portfolio.", chat_id)
                return
            active = get_active_account()
            all_h = get_holdings_cached(account_filter="")
            msg = "🗂 <b>Portfolio Accounts</b>\n"
            msg += f"<i>Active: {active if active else 'All accounts'}</i>\n\n"
            for acc in accounts:
                items = {t: d for t, d in all_h.items() if d.get("account", "").lower() == acc.lower()}
                held = sum(1 for d in items.values() if d.get("shares", 0) > 0)
                marker = " ◀" if acc.lower() == active.lower() else ""
                msg += f"• <b>{acc}</b> — {held} held, {len(items)-held} watchlist{marker}\n"
            msg += "\n<i>Switch: <code>switch account NAME</code> · Reset: <code>switch account all</code></i>"
            send_message(msg, chat_id)
            return

        # ── End write-back commands ────────────────────────────────────────────

        # Quant shortcuts
        _quant_screen_match = re.match(r'^quant\s+screen(?:\s+(full|notion))?$', _cleaned)
        _quant_signal_match = re.match(r'^quant\s+signal\s+([A-Za-z]{1,6})$', _cleaned)
        _quant_bt_match     = re.match(r'^quant\s+backtest(?:\s+(full|notion))?(?:\s+(\d))?$', _cleaned)
        _quant_paper_match  = _cleaned in ("paper portfolio", "quant paper", "paper trades")
        _quant_open_match   = re.match(r'^quant\s+open\s+([A-Za-z]{1,6})(?:\s+(\d+))?$', _cleaned)
        _quant_close_match  = re.match(r'^quant\s+close\s+([A-Za-z]{1,6})$', _cleaned)

        if _quant_screen_match:
            universe = _quant_screen_match.group(1) or "notion"
            send_message("⏳ Running quant factor screen...", chat_id, show_buttons=False)
            from src.tools.quant.signals import run_quant_screen
            from src.tools.quant.universe import get_universe
            notion_tickers = list(WATCHLIST_TICKERS_SET)
            tickers = get_universe(notion_tickers, mode=universe)
            send_message(run_quant_screen(tickers, top_n=15 if universe == "full" else 10), chat_id)
            return

        if _quant_signal_match:
            ticker = _quant_signal_match.group(1).upper()
            send_message(f"⏳ Running quant signal for {ticker}...", chat_id, show_buttons=False)
            from src.tools.quant.signals import run_single_signal
            send_message(run_single_signal(ticker, list(WATCHLIST_TICKERS_SET)), chat_id)
            return

        if _quant_bt_match:
            universe = _quant_bt_match.group(1) or "notion"
            years    = int(_quant_bt_match.group(2) or 2)
            send_message(f"⏳ Running quant backtest ({universe}, {years}y)...", chat_id, show_buttons=False)
            from src.tools.quant.backtest import run_backtest
            from src.tools.quant.universe import get_universe
            tickers = get_universe(list(WATCHLIST_TICKERS_SET), mode=universe)
            send_message(run_backtest(tickers, years=years), chat_id)
            return

        if _quant_paper_match:
            from src.tools.quant.paper_trade import get_paper_portfolio
            send_message(get_paper_portfolio(), chat_id)
            return

        if _quant_open_match:
            ticker = _quant_open_match.group(1).upper()
            shares = float(_quant_open_match.group(2) or 100)
            from src.tools.quant.paper_trade import open_position
            send_message(open_position(ticker, shares=shares), chat_id)
            return

        if _quant_close_match:
            ticker = _quant_close_match.group(1).upper()
            from src.tools.quant.paper_trade import close_position
            send_message(close_position(ticker), chat_id)
            return

        if lowered in ("picks", "recommendations", "what should i buy", "stock picks", "ai picks"):
            from src.tools.recommendations import get_recommendations
            send_message(
                "⏳ Running AI stock picks — Cathie Wood, Druckenmiller, Damodaran debating...",
                chat_id, show_buttons=False
            )
            result = get_recommendations()
            send_message(result, chat_id)
            return

        send_message("⏳ Working on it...", chat_id, show_buttons=False)
        result = agent.invoke(
            {
                "messages": [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=text),
                ]
            },
            config={"configurable": {"thread_id": chat_id}}
        )
        response = result["messages"][-1].content

        # Track ticker and store response for explain button
        extract_ticker(response, chat_id)
        _last_response[chat_id] = response

        send_message(response, chat_id)

    except Exception as e:
        err = str(e)
        # Corrupted checkpointer state — tool_call with no ToolMessage response.
        # Reset this thread's memory and retry once with a clean slate.
        if "ToolMessage" in err or "tool_calls" in err:
            try:
                memory.put(
                    {"configurable": {"thread_id": chat_id}},
                    checkpoint={"v": 1, "ts": "", "id": "", "channel_values": {}, "channel_versions": {}, "versions_seen": {}, "pending_sends": []},
                    metadata={},
                    new_versions={},
                )
            except Exception:
                pass
            try:
                result = agent.invoke(
                    {"messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=text)]},
                    config={"configurable": {"thread_id": chat_id}}
                )
                response = result["messages"][-1].content
                extract_ticker(response, chat_id)
                _last_response[chat_id] = response
                send_message(response, chat_id)
            except Exception as e2:
                send_message(f"❌ Something went wrong: {str(e2)[:200]}", chat_id)
        else:
            send_message(f"❌ Something went wrong: {err[:200]}", chat_id)


# ── Bot Loop ──────────────────────────────────────────────────────────────────

def run_bot():
    print("🤖 AI Investor Bot (LangGraph) is running...")
    send_message(
        "🤖 <b>AI Investor is online</b>\n\n"
        "Your personal research analyst is ready. "
        "Ask me anything or tap a button below.",
        show_buttons=True
    )
    offset = 0
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1

                if "callback_query" in update:
                    cq = update["callback_query"]
                    chat_id = str(cq["message"]["chat"]["id"])
                    callback_data = cq.get("data", "")
                    callback_query_id = cq["id"]
                    print(f"[{datetime.now().strftime('%H:%M')}] Button: {callback_data}")
                    threading.Thread(
                        target=handle_callback,
                        args=(callback_data, chat_id, callback_query_id)
                    ).start()
                    continue

                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id", ""))
                text = message.get("text", "")
                if text and chat_id:
                    print(f"[{datetime.now().strftime('%H:%M')}] {text}")
                    threading.Thread(
                        target=handle_message,
                        args=(text, chat_id)
                    ).start()

        except KeyboardInterrupt:
            print("\nBot stopped.")
            break
        except Exception as e:
            print(f"Loop error: {e}")


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        from src.tools.scheduler import run_scheduler
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        print("📅 Scheduler thread started.")
    except Exception as e:
        print(f"Could not start scheduler thread: {e}")

    run_bot()
