"""
Proactive Analyst — Layer 4 Mode 2.

System spots company names in morning briefing news that are NOT already in
the 98 holdings/watchlist names, then automatically runs a mini research note
on each. Fires after the morning briefing, unprompted.

Rules:
- Only fires for names NOT in current holdings + watchlist (the 98)
- 7-day cooldown per ticker (SQLite) to avoid repeating the same name
- Max 2 dives per morning to avoid flooding Telegram
- Mini-dive: 4 sections, ~20s, lighter than the full 9-section deep dive
"""
import os
import sqlite3
from datetime import datetime, timedelta

from src.tools.llm import call_deepseek, tavily_search, clean_news, fmt_snippet

_DB_PATH = "/app/data/research.db" if os.path.exists("/app/data") else "research.db"


# ── Persistence ───────────────────────────────────────────────────────────────

def _init_db():
    with sqlite3.connect(_DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS proactive_dives (
                ticker TEXT NOT NULL,
                date   TEXT NOT NULL,
                PRIMARY KEY (ticker, date)
            )
        """)


def _already_dived(ticker: str, days: int = 7) -> bool:
    try:
        _init_db()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with sqlite3.connect(_DB_PATH) as con:
            row = con.execute(
                "SELECT 1 FROM proactive_dives WHERE ticker=? AND date>=?",
                (ticker, cutoff)
            ).fetchone()
        return row is not None
    except Exception:
        return False


def _mark_dived(ticker: str):
    try:
        _init_db()
        today = datetime.now().strftime("%Y-%m-%d")
        with sqlite3.connect(_DB_PATH) as con:
            con.execute(
                "INSERT OR IGNORE INTO proactive_dives (ticker, date) VALUES (?, ?)",
                (ticker, today)
            )
    except Exception:
        pass


# ── Name extraction ───────────────────────────────────────────────────────────

def extract_new_names(news_articles: list, known_tickers: set) -> list:
    """
    Extract publicly traded company tickers from news articles.
    Returns list of tickers NOT in known_tickers, deduped, ordered by appearance.
    """
    if not news_articles:
        return []

    text = "\n".join(
        f"- {a.get('title', '')} {a.get('content', '')[:200]}"
        for a in news_articles[:15]
    )

    prompt = (
        "Extract all publicly traded US stock tickers mentioned in the news below.\n"
        "Return ONLY a comma-separated list of ticker symbols (e.g. NVDA, TSLA, AMZN).\n"
        "Do NOT include: ETFs, indices (SPY, QQQ, VIX), cryptocurrencies, or mutual funds.\n"
        "If none found, return exactly: NONE\n\n"
        f"NEWS:\n{text}"
    )

    result = call_deepseek(prompt, max_tokens=80, temperature=0.1, timeout=15)
    if not result or result.strip().upper() == "NONE" or result.startswith("❌"):
        return []

    seen = set()
    unique = []
    for raw in result.replace("\n", ",").split(","):
        t = raw.strip().upper().strip(".")
        if (
            t
            and 1 <= len(t) <= 5
            and t.isalpha()
            and t not in known_tickers
            and t not in seen
            and t not in {"THE", "AND", "FOR", "ETF", "USD", "GDP", "CPI", "FED"}
        ):
            seen.add(t)
            unique.append(t)

    return unique


# ── Mini-dive ─────────────────────────────────────────────────────────────────

def run_mini_dive(ticker: str) -> str:
    """
    4-section analyst note on a new name spotted in news. ~20s.
    Returns formatted Telegram string or "" on failure.
    """
    # Price data
    price_context = ""
    try:
        from src.tools.prices import get_live_prices
        d = get_live_prices([ticker]).get(ticker, {})
        if d.get("price"):
            mktcap = d.get("market_cap") or 0
            price_context = (
                f"Price: ${d['price']} ({d.get('change_pct', 0):+.1f}% today) | "
                f"Mkt cap: ${mktcap/1e9:.1f}B | "
                f"P/E: {d.get('pe_ratio', 'N/A')}"
            )
    except Exception:
        pass

    # Fresh news specifically about this company
    news = clean_news(tavily_search(
        f"{ticker} stock company earnings business model news 2026",
        max_results=5, search_depth="basic",
    ))
    news_text = ""
    for a in news[:3]:
        news_text += f"- {a.get('title', '')}\n"
        snip = fmt_snippet(a.get("content", ""), 140)
        if snip:
            news_text += f"  {snip}\n"

    prompt = (
        f"You are an equity analyst. A new company just appeared in the morning news: <b>{ticker}</b>.\n"
        + (f"{price_context}\n\n" if price_context else "\n")
        + f"NEWS MENTIONS:\n{news_text or 'No specific news found — use training knowledge.'}\n\n"
        "Write a quick analyst note with exactly 4 sections (use these exact headers):\n\n"
        "<b>What it does</b> — one sentence: business model, how it makes money\n"
        "<b>Why it's in the news</b> — what specifically caused it to appear today\n"
        "<b>Valuation snapshot</b> — cheap / fair / expensive vs peers, one sentence\n"
        "<b>Verdict</b> — WATCH or PASS, with one sentence why\n\n"
        "Max 130 words total. Direct. Use <b>bold</b> for the ticker."
    )

    result = call_deepseek(prompt, max_tokens=220, temperature=0.3, timeout=25)
    if not result or result.startswith("❌"):
        return ""

    return (
        f"🔍 <b>New Name: {ticker}</b>\n"
        f"<i>Spotted in morning news — proactive analyst note</i>\n\n"
        f"{result}"
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def run_proactive_analysis(news_articles: list, known_tickers: set, max_dives: int = 2) -> list:
    """
    Called from morning briefing after news is fetched.
    Returns list of formatted Telegram messages (one per new name).
    Empty list if nothing fires.
    """
    candidates = extract_new_names(news_articles, known_tickers)
    if not candidates:
        print("[proactive analyst] No new names found in news.")
        return []

    print(f"[proactive analyst] Candidates: {candidates}")

    results = []
    for ticker in candidates:
        if len(results) >= max_dives:
            break
        if _already_dived(ticker, days=7):
            print(f"[proactive analyst] {ticker} already dived within 7 days — skipping.")
            continue
        print(f"[proactive analyst] Mini-dive: {ticker}")
        msg = run_mini_dive(ticker)
        if msg:
            _mark_dived(ticker)
            results.append(msg)

    return results
