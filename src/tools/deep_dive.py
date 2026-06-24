import os
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

from src.tools.prices import get_live_prices
from src.tools.news_fetcher import get_news_for_tickers
from src.tools.sec_filings import get_filing_summary

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")


def call_deepseek(prompt: str, system: str = "") -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": messages, "max_tokens": 2000, "temperature": 0.3},
            timeout=90,
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        return f"API Error {response.status_code}: {response.text[:200]}"
    except requests.exceptions.Timeout:
        return "DeepSeek API timed out after 90s. Please try again."
    except Exception as e:
        return f"API call failed: {str(e)[:200]}"


def deep_dive(ticker: str) -> str:
    print(f"\n🔬 Deep dive: {ticker}")

    # Steps 1-3 in parallel
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_price   = ex.submit(get_live_prices, [ticker])
        f_filings = ex.submit(get_filing_summary, ticker)
        f_news    = ex.submit(get_news_for_tickers, [ticker])

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

    print(f"✅ Data fetched — price: {bool(price_data)}, news: {len(ticker_news)}, filings: {sum(len(v) for v in filings.values())}")

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
            if a.get('content'):
                news_context += f"  {a['content'][:200]}\n"
    else:
        news_context += "No recent news found — use training knowledge.\n"

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
    