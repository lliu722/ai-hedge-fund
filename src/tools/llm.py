"""
Shared LLM helpers — single call site for DeepSeek and Tavily.
Import these everywhere instead of inlining requests.post calls.
"""
import os
import requests

_DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
_TAVILY_URL   = "https://api.tavily.com/search"


def call_deepseek(
    prompt: str,
    system: str = "",
    max_tokens: int = 500,
    temperature: float = 0.3,
    timeout: int = 60,
) -> str:
    """Call DeepSeek chat. Returns content string or raises on failure."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        r = requests.post(
            _DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": messages,
                  "max_tokens": max_tokens, "temperature": temperature},
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        return f"❌ DeepSeek error {r.status_code}: {r.text[:150]}"
    except requests.exceptions.Timeout:
        return f"❌ DeepSeek timed out after {timeout}s."
    except Exception as e:
        return f"❌ DeepSeek call failed: {str(e)[:150]}"


def tavily_search(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
    timeout: int = 10,
) -> list[dict]:
    """Run a Tavily search. Returns list of result dicts (empty on failure)."""
    api_key = os.getenv("TAVILY_API_KEY", "")
    try:
        r = requests.post(
            _TAVILY_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": query, "max_results": max_results, "search_depth": search_depth},
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json().get("results", [])
        print(f"[Tavily] HTTP {r.status_code} for query: {query[:60]}")
    except Exception as e:
        print(f"[Tavily] Error: {e} — query: {query[:60]}")
    return []


_JUNK_DOMAINS = (
    "investing.com", "tradingview.com", "barchart.com", "tradingeconomics.com",
    "marketbeat.com", "stockanalysis.com", "macrotrends.net", "wisesheets.io",
    "simplywall.st", "gurufocus.com",
)
_JUNK_TITLES = (
    "calendar", "schedule", "quote - chart", "stock market index",
    "latest news and updates", "stock screener", "historical data",
    "r/stocks", "r/investing",
)


def clean_news(results: list, min_content: int = 60) -> list:
    """
    Filter Tavily results — removes junk SEO pages, empty content, markdown noise.
    Use after every tavily_search() before displaying or passing to DeepSeek.
    """
    out = []
    for r in results:
        url   = r.get("url", "").lower()
        title = r.get("title", "").lower()
        content = r.get("content", "").strip()
        if any(d in url for d in _JUNK_DOMAINS):
            continue
        if any(k in title for k in _JUNK_TITLES):
            continue
        if len(content) < min_content:
            continue
        if content.startswith("[") or content.startswith("]("):
            continue
        out.append(r)
    return out


def fmt_snippet(content: str, max_len: int = 150) -> str:
    """Return a clean display snippet from Tavily content, or empty string if useless."""
    c = content.strip() if content else ""
    if not c or len(c) < 40 or c.startswith("[") or c.startswith("]("):
        return ""
    return c[:max_len]
