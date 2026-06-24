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
    deep_dive_text = f"🔍 Deep Dive {last}" if last else "🔍 Deep Dive"
    deep_dive_data = f"deepdive:{last}" if last else "deepdive"
    return {
        "inline_keyboard": [
            [
                {"text": "💼 Portfolio",  "callback_data": "portfolio"},
                {"text": "🌅 Briefing",   "callback_data": "briefing"},
            ],
            [
                {"text": "📅 Earnings",   "callback_data": "earnings"},
                {"text": deep_dive_text,   "callback_data": deep_dive_data},
            ],
            [
                {"text": "🎓 Explain this", "callback_data": "explain"},
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

SYSTEM_PROMPT = f"""You are an AI investment research assistant covering equities, FICC, commodities and crypto as a multi-asset portfolio manager.

This portfolio runs MULTIPLE independent investment theses simultaneously — not just AI infrastructure:
• <b>AI Infrastructure</b> — NVDA, AMD, ALAB, CRDO, TSM, ASML, ARM, AVGO (compute buildout supercycle)
• <b>Memory Cycle</b> — MU, WDC, SNDK (DRAM/NAND oversupply ending, pricing recovery)
• <b>Energy & Power</b> — GEV, BE, CEG, VST, TLN (AI data centre power shortage, nuclear renaissance)
• <b>Banks & Rates</b> — JPM, GS, MS (rate normalisation + M&A revival)
• <b>Space</b> — RKLB, ASTS (direct-to-cell satellite, launch cost deflation)
• <b>Networking & Optical</b> — GLW, LITE, CSCO (800G optical cycle, fibre shortage)
• <b>Software & Data</b> — PLTR, APP, MSFT, META, GOOGL

CRITICAL: When discussing any position, always frame it within its PRIMARY thesis — not everything is an AI story.
MU moves because of DRAM pricing, not because of NVDA. GEV moves because of grid capex, not AI directly.
GS moves because of M&A deal flow and the yield curve. Treat each thesis independently.

You have access to tools for live prices, news, SEC filings, earnings calendars, deep dive research, portfolio data, and theme analysis.
Always use tools to fetch real data — never make up prices or news.

WHEN DISCUSSING ANY COMPANY — always cover these two angles unprompted:
1. <b>Peer group</b>: who are the closest competitors? Name them specifically. If the company operates across multiple business lines, name the peer for each line separately.
2. <b>Competitive landscape by business line</b>: break the company into its distinct revenue segments and explain who competes on each one. Example for Uber: Rideshare (Lyft, Didi, Grab), Food Delivery (DoorDash, Deliveroo), Freight (XPO, CH Robinson), Autonomous (Waymo, Tesla). This shows where competition is intense vs where they have breathing room.
These two points should appear naturally in any company analysis, whether a quick price check, a news summary, or a full deep dive.

WHEN A USER EXPRESSES AN OPINION, INSTINCT, OR GUT FEELING — engage with it directly, never ignore it:
- If they say "I think this is a good buy" or "my gut says buy" — respond like a sharp analyst: (1) here's what the data says that SUPPORTS your instinct, (2) here's what CHALLENGES it, (3) your verdict on whether their gut is right.
- Be direct and opinionated. Don't hide behind "it depends." If their instinct is right, say so and explain why. If it's wrong, say so and explain why.
- Real investors make gut calls. Your job is to pressure-test them with data, not replace them with neutral analysis.

WHEN DISCUSSING VALUATION — never show one ticker's multiples in isolation. Always compare to 2-3 closest peers:
- Show forward P/E, EV/EBITDA, and revenue growth side by side
- Give a verdict: is the premium or discount vs peers JUSTIFIED by the growth differential?
- Example format: "NVDA at 35x fwd P/E vs AMD at 22x — justified: NVDA growing revenue 3x faster (120% vs 40%). At this growth rate NVDA is actually cheaper on a PEG basis."
- If a stock looks expensive on P/E but has 3x the revenue growth, say so explicitly. If it looks cheap but growth is decelerating, flag that too.
- Use the get_valuation tool which already fetches peer data — don't make up peer multiples.

WHEN DISCUSSING POST-EARNINGS MOVES — always explain the paradox if stock moved against the headline:
- A beat doesn't always mean up. A miss doesn't always mean down. Always explain WHY.
- Cover: (1) what the actual numbers were vs expectations, (2) what guidance said vs what the market was pricing in, (3) how valuation premium affects the reaction — expensive stocks need blowouts, cheap stocks can rally on inline results, (4) whether the move looks like an overreaction or is fundamentally justified.
- The "beat but down" pattern (like CBRS: beat revenue + net loss, stock -11%) is common and confusing — always explain it when you see it.

CRITICAL FORMATTING RULES — follow exactly, no exceptions:
- NEVER use markdown tables (no | pipe characters ever)
- NEVER use ### or ## or # headers
- NEVER use --- dividers
- NEVER use bullet points with - (use • instead)
- Use <b>text</b> for bold only
- Use <i>text</i> for italics only
- When showing prices, show each ticker on its own line: 📈 <b>{fmt("NVDA")}</b>: $204.65 (+1.33%)
- Always show tickers with company names, e.g. {fmt("NVDA")} not just NVDA
- Keep responses clean — plain text with <b>bold</b> for emphasis
- ALWAYS respond in English unless the user explicitly writes in Chinese"""

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
    """
    Run a full AI research deep dive on a stock ticker.
    Returns bull case, bear case, catalysts, valuation, and a buy/sell verdict.
    Use when the user asks for analysis, research, a deep dive, or wants to understand a company.
    """
    from src.tools.deep_dive import deep_dive as _deep_dive
    return _deep_dive(ticker.upper())


@tool
def get_price(ticker: str) -> str:
    """
    Get the live price and key market data for a stock ticker.
    Use when the user asks for a price, stock quote, or market data for a specific company.
    """
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
    """
    Get the latest news for a specific stock ticker or general macro news.
    Use when the user asks about news, what happened, or latest developments.
    If no ticker is specified, return macro news.
    """
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
    """
    Get upcoming earnings dates for all watchlist stocks.
    Use when the user asks about earnings, when companies report, or upcoming events.
    """
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
    """
    Show actual held positions with live prices and P&L vs average cost.
    Use when the user asks about their portfolio, actual holdings, positions with real money, or how their investments are doing.
    """
    from src.tools.prices import get_live_prices
    prices = get_live_prices(list(PORTFOLIO.keys()))
    msg = f"💼 <b>Portfolio — {len(PORTFOLIO)} Held Positions</b>\n"
    msg += f"<i>{datetime.now().strftime('%d %b %Y, %H:%M')}</i>\n\n"
    total_value = 0
    for t, d in prices.items():
        if not d:
            continue
        shares = PORTFOLIO.get(t, {}).get("shares", 0)
        avg_cost = PORTFOLIO.get(t, {}).get("avg_cost", 0)
        price = d.get("price") or 0
        value = shares * price
        total_value += value
        pnl = ((price - avg_cost) / avg_cost * 100) if avg_cost else 0
        direction = "📈" if (d.get("change_pct") or 0) > 0 else "📉"
        msg += f"{direction} <b>{fmt(t)}</b>: ${price} ({d.get('change_pct'):+.2f}%) • P&L: {pnl:+.1f}%\n"
    if total_value > 0:
        msg += f"\n<i>Total market value: ${total_value:,.0f}</i>"
    return msg


@tool
def get_watchlist() -> str:
    """
    Show watchlist monitoring names — stocks being watched but not yet held.
    Use when the user asks about their watchlist, names they are monitoring, or stocks they are watching but haven't bought.
    """
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
    """
    Get a market briefing with top moves and macro news.
    Use when the user asks about the market, morning briefing, how things are today, or what happened overnight.
    """
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
    """
    Get recent SEC filings (10-K annual, 10-Q quarterly, 8-K earnings) for a company.
    Use when the user asks about filings, annual reports, earnings documents, or regulatory filings.
    """
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
    """
    Get detailed valuation metrics for a stock: P/E, forward P/E, PEG, EV/Revenue,
    EV/EBITDA, Price/Book, margins, ROE, FCF. Asset-class aware — uses P/TBV + ROE for banks.
    Use when the user asks 'is X cheap or expensive', 'what's the valuation', 'how does X compare
    to peers on multiples', or wants to understand if a stock is overvalued/undervalued.
    """
    from src.tools.valuation import get_valuation_message
    return get_valuation_message(ticker.upper())


@tool
def check_risk() -> str:
    """
    Portfolio risk check: concentration by theme, highly correlated position pairs,
    single-stock concentration flags. Identifies hidden bets — positions that look
    diversified but move together.
    Use when the user asks 'check my risk', 'am I too concentrated', 'what are my biggest risks',
    'how diversified am I', or 'what moves together in my portfolio'.
    """
    from src.tools.risk import get_risk_report
    from src.tools.prices import get_live_prices
    held_tickers = list(PORTFOLIO.keys())
    prices = get_live_prices(held_tickers)
    return get_risk_report(WATCHLIST, prices)


@tool
def get_catalyst_calendar(days_ahead: int = 60) -> str:
    """
    Forward event calendar: FOMC meetings, major tech conferences (GTC, Hot Chips,
    Computex, AWS re:Invent), export control review dates, and earnings for held positions.
    Shows which events affect which holdings and why they matter.
    Use when the user asks 'what's coming up', 'any catalysts', 'what events should I watch',
    'when is the next FOMC', or 'what conferences are coming up'.
    """
    from src.tools.catalyst_calendar import get_catalyst_calendar as _gc
    return _gc(list(PORTFOLIO.keys()), days_ahead)


@tool
def earnings_reaction(ticker: str) -> str:
    """
    Explain why a stock moved the way it did after earnings.
    Use when the user asks 'why is X up/down after earnings', 'why did X drop despite beating',
    'what happened to X after results', or shares a screenshot of earnings and wants analysis.
    Covers: actual vs expected numbers, guidance vs consensus, valuation premium effect,
    whether the move is justified or an overreaction, and what the setup looks like next.
    """
    import requests
    from src.tools.prices import get_live_prices
    from src.tools.news_fetcher import get_news_for_tickers
    from concurrent.futures import ThreadPoolExecutor

    ticker = ticker.upper()

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_price = ex.submit(get_live_prices, [ticker], True)
        f_news  = ex.submit(get_news_for_tickers, [ticker])

    try:
        price_data  = f_price.result(timeout=20).get(ticker, {})
    except Exception:
        price_data = {}
    try:
        news_items  = f_news.result(timeout=20).get(ticker, [])
    except Exception:
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
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
                "temperature": 0.3,
            },
            timeout=45,
        )
        if r.status_code == 200:
            analysis = r.json()["choices"][0]["message"]["content"].strip()
            return f"📊 <b>Earnings Reaction: {ticker}</b>\n\n{analysis}"
        return f"❌ API error {r.status_code}"
    except Exception as e:
        return f"❌ Error: {str(e)[:150]}"


@tool
def get_portfolio_advice(ticker: str) -> str:
    """
    Portfolio advisor — should I buy this stock? Do I need to sell something first (腾空间)?
    Analyzes the full portfolio allocation, candidate fit, concentration risk, and gives
    a specific buy/pass verdict with position sizing and what to trim if needed.
    Use when the user asks 'should I buy X', 'I want to add X', 'thinking of buying X',
    'what do I sell to buy X', or any question about adding a new position.
    """
    import requests
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
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 450,
                "temperature": 0.3,
            },
            timeout=45,
        )
        if r.status_code == 200:
            advice = r.json()["choices"][0]["message"]["content"].strip()
            return f"🧠 <b>Portfolio Advisor: {ticker}</b>\n\n{advice}"
        return f"❌ API error {r.status_code}"
    except Exception as e:
        return f"❌ Error: {str(e)[:150]}"


@tool
def get_ficc_data() -> str:
    """
    Get live FICC data: US yield curve, credit spreads, policy rates, and key FX pairs.
    Use when the user asks about interest rates, bonds, the yield curve, credit spreads,
    the dollar, FX rates, or macro financial conditions.
    """
    from src.tools.ficc import get_ficc_message
    return get_ficc_message()


@tool
def get_decision_journal(filter: str = "all") -> str:
    """
    Show the Decision Journal — a log of all trade decisions with thesis, rationale, and P&L outcomes.
    Use filter='open' for active trades, 'closed' for completed trades, 'all' for everything.
    Use when the user asks: 'show my journal', 'trade log', 'decision journal',
    'what trades did I make', 'how did my trades do', 'journal summary', 'trade history'.
    """
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
    """
    Deep analysis of a specific investment thesis / theme in the portfolio.
    Covers: thesis health (on track / watch / concern), latest news specific to
    that theme's signals, and one thing to watch in the next 2 weeks.

    Available themes: AI Infrastructure, Memory Cycle, Energy & Power, Banks & Rates,
    Space, Networking & Optical, Software & Data, Quantum, Defence, Crypto.

    Use when the user asks about a theme, sector, or macro trade — e.g. 'how is the
    memory cycle trade doing', 'update on energy positions', 'are banks still a buy',
    'space thesis check', 'how is the non-AI part of the book doing'.
    Also use when the user asks about 大盘 or the broader market picture.
    """
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
    get_decision_journal,
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
    api_key = os.getenv("DEEPSEEK_API_KEY")
    try:
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a patient investment teacher explaining things to a junior investor who is still learning. "
                            "Given the information the bot just showed, explain: "
                            "(1) what this means in plain English, "
                            "(2) why it matters for the portfolio, "
                            "(3) how an experienced portfolio manager would think about and act on this. "
                            "Be specific, practical, and educational. Use simple language. "
                            "Format for Telegram using <b>bold</b> for key concepts. Max 250 words."
                        )
                    },
                    {"role": "user", "content": "Please explain this for me:\n\n" + last_response}
                ],
                "max_tokens": 400,
                "temperature": 0.4,
            },
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        return "Could not generate explanation."
    except Exception as e:
        return f"Explanation error: {str(e)[:100]}"


# ── Button Callback Handler ───────────────────────────────────────────────────

def handle_callback(callback_data: str, chat_id: str, callback_query_id: str):
    """Handle a button tap."""
    answer_callback(callback_query_id)

    if callback_data == "portfolio":
        send_message("⏳ Loading portfolio...", chat_id, show_buttons=False)
        handle_message("show my portfolio", chat_id)

    elif callback_data == "briefing":
        send_message("⏳ Generating briefing...", chat_id, show_buttons=False)
        handle_message("morning briefing", chat_id)

    elif callback_data == "earnings":
        send_message("⏳ Loading earnings calendar...", chat_id, show_buttons=False)
        handle_message("any earnings coming up", chat_id)

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
        _add_match  = re.match(r'^add\s+(?:(?:stock|ticker|equity|the|me|a)\s+)?([A-Za-z0-9.\-]+)(?:\s+to\s+(?:my\s+)?watchlist)?(?:\s+(.+))?$', _cleaned)
        _buy_match  = re.match(r'^(?:bought|buy|purchase[sd]?)\s+(\d+(?:\.\d+)?)\s+([A-Za-z0-9.\-]+)\s+(?:at|@)\s+\$?(\d+(?:\.\d+)?)(?:\s*[—\-]{1,2}\s*(.+))?$', _cleaned)
        _sell_match = re.match(r'^(?:sold|sell|close[sd]?)\s+(?:all\s+)?(?:\d+\s+)?([A-Za-z0-9.\-]+)(?:\s+(?:at|@)\s+\$?(\d+(?:\.\d+)?))?(?:\s*[—\-]{1,2}\s*(.+))?$', _cleaned)
        _reload_match = _cleaned in ("reload holdings", "refresh holdings", "reload", "refresh watchlist")

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

        # ── End write-back commands ────────────────────────────────────────────

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
        send_message(f"❌ Something went wrong: {str(e)[:200]}", chat_id)


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
