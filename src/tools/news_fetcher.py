import os
from tavily import TavilyClient
from datetime import datetime

client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

THEME_CLUSTERS = {
    "AI_compute": ["NVDA", "ALAB", "AMD"],
    "semiconductors": ["TSM", "ASML", "ARM", "AVGO"],
    "AI_software_energy": ["PLTR", "APP", "CEG"],
}

def get_news_for_tickers(tickers, days_back=2):
    results = {ticker: [] for ticker in tickers}
    for cluster_name, ctickers in THEME_CLUSTERS.items():
        relevant = [t for t in ctickers if t in tickers]
        if not relevant:
            continue
        query = " ".join(relevant) + " stock news earnings AI"
        try:
            response = client.search(query=query, max_results=10, search_depth="basic", include_answer=False)
            articles = response.get("results", [])
            for article in articles:
                title = article.get("title", "").upper()
                content = article.get("content", "").upper()
                for ticker in relevant:
                    if ticker in title or ticker in content:
                        results[ticker].append({
                            "title": article.get("title"),
                            "url": article.get("url"),
                            "content": article.get("content", "")[:500],
                            "published_date": article.get("published_date"),
                        })
        except Exception as e:
            print(f"Error fetching news for {cluster_name}: {e}")
    return results

def get_macro_news():
    query = "AI chip semiconductor export control Fed rates tech earnings"
    try:
        response = client.search(query=query, max_results=5, search_depth="basic", include_answer=False)
        return response.get("results", [])
    except Exception as e:
        print(f"Error fetching macro news: {e}")
        return []

if __name__ == "__main__":
    print("Testing news fetcher...")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    tickers = ["NVDA", "TSM", "AVGO"]
    news = get_news_for_tickers(tickers)
    for ticker, articles in news.items():
        print(f"\n{ticker}: {len(articles)} articles found")
        for a in articles[:2]:
            print(f"  - {a['title']}")
    print("\nMacro news:")
    macro = get_macro_news()
    for a in macro[:3]:
        print(f"  - {a['title']}")
