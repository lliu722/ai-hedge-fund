from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from src.tools.prices import get_live_prices
from src.tools.news_fetcher import get_news_for_tickers
from src.tools.sec_filings import get_filing_summary
from src.tools.llm import call_deepseek, fmt_snippet


def deep_dive(ticker: str) -> str:
    print(f"\n🔬 Deep dive: {ticker}")

    # Pull saved notes + earnings history from research library
    def fetch_notes():
        try:
            from src.tools.research_library import search_research
            return search_research(ticker=ticker, limit=5)
        except Exception:
            return []

    def fetch_earnings_history():
        try:
            from src.tools.research_library import get_earnings_history
            return get_earnings_history(ticker)
        except Exception:
            return []

    # Steps 1-5 in parallel
    with ThreadPoolExecutor(max_workers=5) as ex:
        f_price    = ex.submit(get_live_prices, [ticker])
        f_filings  = ex.submit(get_filing_summary, ticker)
        f_news     = ex.submit(get_news_for_tickers, [ticker])
        f_notes    = ex.submit(fetch_notes)
        f_earnings = ex.submit(fetch_earnings_history)

        try:
            price_data  = f_price.result(timeout=20).get(ticker, {})
        except Exception:
            price_data = {}
        try:
            filings = f_filings.result(timeout=20)
        except Exception:
            filings = {"10-K": [], "10-Q": [], "8-K": []}
        try:
            ticker_news = f_news.result(timeout=20).get(ticker, [])
        except Exception:
            ticker_news = []
        try:
            saved_notes = f_notes.result(timeout=10)
        except Exception:
            saved_notes = []
        try:
            earn_history = f_earnings.result(timeout=10)
        except Exception:
            earn_history = []

    print(f"✅ Data fetched — price: {bool(price_data)}, news: {len(ticker_news)}, filings: {sum(len(v) for v in filings.values())}, notes: {len(saved_notes)}, earnings: {len(earn_history)}")

    price_context = f"""LIVE MARKET DATA for {ticker}:
• Price: ${price_data.get('price', 'N/A')}
• Daily Change: {price_data.get('change_pct', 'N/A')}%
• 52-Week High: ${price_data.get('week52_high', 'N/A')}
• 52-Week Low: ${price_data.get('week52_low', 'N/A')}
• Market Cap: ${(price_data.get('market_cap') or 0):,.0f}
• P/E Ratio: {price_data.get('pe_ratio', 'N/A')}"""

    filings_context = f"""RECENT SEC FILINGS:
• Latest 10-K: {filings['10-K'][0]['date'] if filings['10-K'] else 'Not available'}
• Recent 10-Qs: {[f['date'] for f in filings['10-Q']]}
• Recent 8-Ks: {[f['date'] for f in filings['8-K']]}"""

    news_context = "RECENT NEWS:\n"
    if ticker_news:
        for a in ticker_news[:5]:
            news_context += f"• {a['title']}\n"
            snip = fmt_snippet(a.get("content", ""), 200)
            if snip:
                news_context += f"  {snip}\n"
    else:
        news_context += "No recent news found — use training knowledge.\n"

    notes_context = ""
    if saved_notes:
        notes_context = "YOUR SAVED NOTES & PRIOR RESEARCH:\n"
        for n in saved_notes[:5]:
            notes_context += f"[{n['type']} · {n['created']}]\n{n['content'][:400]}\n\n"

    earnings_context = ""
    if earn_history:
        beats = sum(1 for r in earn_history if r["beat_miss"] == "Beat")
        earnings_context = f"EARNINGS SURPRISE HISTORY ({beats}/{len(earn_history)} beats):\n"
        for r in earn_history[:4]:
            emoji = "🟢" if r["beat_miss"] == "Beat" else ("🔴" if r["beat_miss"] == "Miss" else "🟡")
            parts = []
            if r.get("rev_surprise_pct") is not None: parts.append(f"Rev {r['rev_surprise_pct']:+.1f}%")
            if r.get("eps_surprise_pct") is not None: parts.append(f"EPS {r['eps_surprise_pct']:+.1f}%")
            if r.get("stock_reaction") is not None: parts.append(f"Stock {r['stock_reaction']:+.1f}%")
            earnings_context += f"{emoji} {r['period']}: {r['beat_miss']} · {' · '.join(parts)}\n"

    system_prompt = (
        "You are a senior equity research analyst covering multi-asset portfolios with a focus on AI infrastructure. "
        "Your reader is a sophisticated investor with a 1-12 month catalyst-driven horizon. "
        "Be direct, specific, and opinionated. No generic statements. "
        "Format for Telegram: use <b>bold</b> for section headers and key terms. "
        "Use • for bullets. No markdown tables, no --- dividers, no # headers."
    )

    user_prompt = f"""Deep dive research report for <b>{ticker}</b>.

{price_context}

{filings_context}

{news_context}
{earnings_context}
{notes_context}

Write a structured report with these 9 sections. Use <b>1. BUSINESS OVERVIEW</b> style headers:

1. BUSINESS OVERVIEW — what it does, how it makes money. Break into distinct business lines with rough revenue split if known.
2. COMPETITIVE LANDSCAPE — peer group by business line. For each major segment: who are the direct competitors, what is the company's market position, where is competition most intense vs where do they have breathing room? Name specific tickers/companies.
3. CURRENT SITUATION — what is happening right now based on news and filings
4. BULL CASE (6-12 months) — strongest argument for owning, specific catalysts
5. BEAR CASE — strongest argument against, what could go wrong
6. KEY CATALYSTS — 3-5 upcoming events that could move the stock
7. VALUATION — cheap / fair / expensive vs growth, reference the P/E and market cap. Compare to closest peer multiple if known.
8. THESIS INVALIDATION — specific events that would make the thesis wrong
9. VERDICT — STRONG BUY / BUY / WATCH / AVOID with one paragraph rationale

Under 900 words total. Be direct and opinionated."""

    print("🤖 Calling DeepSeek for synthesis...")
    report = call_deepseek(user_prompt, system_prompt)

    output = (
        f"🔬 <b>Deep Dive: {ticker}</b>\n"
        f"<i>{datetime.now().strftime('%d %b %Y, %H:%M')}</i>\n\n"
        f"{report}\n\n"
        f"<i>Sources: live price • {len(filings['10-K'])} 10-K • {len(filings['10-Q'])} 10-Q • {len(ticker_news)} news articles</i>"
    )
    return output


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    report = deep_dive(ticker)
    print(report)
    