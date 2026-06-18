import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from src.tools.prices import get_live_prices
from src.tools.news_fetcher import get_news_for_tickers
from src.tools.sec_filings import get_filing_summary

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

def call_deepseek(prompt: str, system: str = "") -> str:
    """Call DeepSeek API directly."""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "max_tokens": 2000,
        "temperature": 0.3,
    }

    response = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers=headers,
        json=payload,
    )

    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        return f"API Error: {response.status_code} - {response.text}"


def deep_dive(ticker: str) -> str:
    """
    Full deep dive chain:
    Step 1 - Live prices
    Step 2 - SEC filings
    Step 3 - News aggregation
    Step 4 - AI synthesis
    """
    print(f"\n🔬 Starting deep dive on {ticker}...")
    print("=" * 50)

    # Step 1 — Live prices
    print("📊 Step 1/4 — Fetching live prices...")
    prices = get_live_prices([ticker])
    price_data = prices.get(ticker, {})

    # Step 2 — SEC filings
    print("📄 Step 2/4 — Fetching SEC filings...")
    filings = get_filing_summary(ticker)

    # Step 3 — News
    print("🗞️  Step 3/4 — Fetching latest news...")
    news = get_news_for_tickers([ticker])
    ticker_news = news.get(ticker, [])

    # Step 4 — AI synthesis
    print("🤖 Step 4/4 — AI synthesis (this takes ~30 seconds)...")

    # Build context for DeepSeek
    price_context = f"""
LIVE MARKET DATA for {ticker}:
- Current Price: ${price_data.get('price')}
- Daily Change: {price_data.get('change_pct')}%
- 52-Week High: ${price_data.get('week52_high')}
- 52-Week Low: ${price_data.get('week52_low')}
- Market Cap: ${price_data.get('market_cap', 0):,.0f}
- P/E Ratio: {price_data.get('pe_ratio')}
"""

    filings_context = f"""
RECENT SEC FILINGS:
- Latest 10-K: {filings['10-K'][0]['date'] if filings['10-K'] else 'Not available'}
- Recent 10-Qs: {[f['date'] for f in filings['10-Q']]}
- Recent 8-Ks: {[f['date'] for f in filings['8-K']]}
"""

    news_context = "RECENT NEWS:\n"
    if ticker_news:
        for article in ticker_news[:5]:
            news_context += f"- {article['title']}\n"
            if article.get('content'):
                news_context += f"  {article['content'][:200]}\n"
    else:
        news_context += "No recent news found.\n"

    system_prompt = """You are a senior equity research analyst specialising in AI infrastructure and technology stocks.
Your analysis is used by a sophisticated investor with a 1-12 month catalyst-driven investment horizon.
You focus on: competitive moat, revenue growth trajectory, upcoming catalysts, and risk/reward.
Be direct, specific, and actionable. Avoid generic statements."""

    user_prompt = f"""Generate a comprehensive deep dive research report for {ticker}.

{price_context}
{filings_context}
{news_context}

Produce a structured report with these exact sections:

1. BUSINESS OVERVIEW
What does this company do and how does it make money? What is its role in the AI infrastructure stack?

2. CURRENT SITUATION
What is happening with this company right now based on the latest news and filings?

3. BULL CASE (6-12 months)
The strongest argument for owning this stock. Be specific about catalysts and price drivers.

4. BEAR CASE
The strongest argument against. What could go wrong?

5. KEY CATALYSTS
List the 3-5 most important upcoming events that could move the stock.

6. VALUATION ASSESSMENT
Is the stock cheap, fair, or expensive relative to its growth? Use the market data provided.

7. THESIS INVALIDATION TRIGGERS
What specific events would make this thesis wrong? Be concrete.

8. VERDICT
One of: STRONG BUY / BUY / WATCH / AVOID
With a one paragraph rationale.

Keep the full report under 800 words. Be direct and opinionated."""

    report = call_deepseek(user_prompt, system_prompt)

    # Format final output
    output = f"""
{'='*60}
DEEP DIVE REPORT: {ticker}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
{'='*60}

{report}

{'='*60}
DATA SOURCES:
- Price: ${price_data.get('price')} (live)
- SEC Filings: {len(filings['10-K'])} 10-K, {len(filings['10-Q'])} 10-Q, {len(filings['8-K'])} 8-K
- News articles: {len(ticker_news)} found
{'='*60}
"""
    return output


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    report = deep_dive(ticker)
    print(report)
    