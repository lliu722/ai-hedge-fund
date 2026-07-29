from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from src.tools.llm import tavily_search, clean_news, filter_relevant


def get_news_for_tickers(tickers: list, days_back: int = 2, names: dict | None = None) -> dict:
    """
    Fetch recent news per ticker, one real search per ticker (parallelized),
    not limited to any fixed subset — works for any ticker passed in.

    Previously this searched only 3 hardcoded theme clusters covering 8
    tickers total (NVDA/ALAB/AMD/TSM/ASML/ARM/AVGO/PLTR/APP/CEG); any other
    ticker silently got back an empty list regardless of what news actually
    existed for it, starving news context for the vast majority of a
    100+-name portfolio across deep_dive(), get_news(), and earnings_reaction.
    days_back was also accepted but never actually passed to the search —
    dead parameter, no real recency filtering. Both fixed.

    names: optional {ticker: company_name} map. When given, the company
    name is folded into the search query (sharpens ambiguous short tickers
    like "BE" or "ON") and used alongside the ticker for the relevance
    check below — search hits are filtered, not trusted wholesale.
    """
    names = names or {}

    def _fetch_one(ticker: str) -> tuple[str, list]:
        company = names.get(ticker, "")
        query = f"{ticker} {company} stock news".strip() if company else f"{ticker} stock news"
        try:
            results = tavily_search(
                query, max_results=8, search_depth="basic",
                topic="news", days=days_back,
            )
            articles = clean_news(results)
            relevant = filter_relevant(articles, ticker, company)
            return ticker, [
                {
                    "title": a.get("title"),
                    "url": a.get("url"),
                    "content": (a.get("content", "") or "")[:500],
                    "published_date": a.get("published_date"),
                }
                for a in relevant
            ]
        except Exception as e:
            print(f"Error fetching news for {ticker}: {e}")
            return ticker, []

    if not tickers:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(tickers))) as ex:
        return dict(ex.map(_fetch_one, tickers))


def get_macro_news():
    query = "AI chip semiconductor export control Fed rates tech earnings"
    try:
        results = tavily_search(query, max_results=8, search_depth="basic", topic="news", days=2)
        return clean_news(results)
    except Exception as e:
        print(f"Error fetching macro news: {e}")
        return []


if __name__ == "__main__":
    print("Testing news fetcher...")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    tickers = ["NVDA", "TSM", "AVGO", "BE", "GEV"]
    news = get_news_for_tickers(tickers)
    for ticker, articles in news.items():
        print(f"\n{ticker}: {len(articles)} articles found")
        for a in articles[:2]:
            print(f"  - {a['title']}")
    print("\nMacro news:")
    macro = get_macro_news()
    for a in macro[:3]:
        print(f"  - {a['title']}")
