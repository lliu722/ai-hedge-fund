"""
Ticker universe management.

Two modes:
  - Notion-only (98 names): default for factor screen
  - Full (~500 names): S&P 500 pulled from Wikipedia + Notion 98 merged

The S&P 500 list is fetched once per session and cached in memory.
Falls back to a hardcoded ~200-name cross-sector list if Wikipedia is unreachable.
"""
from __future__ import annotations
import pandas as pd

_sp500_cache: list[str] | None = None


# Fallback list — large-cap cross-sector names if Wikipedia fetch fails
_FALLBACK_UNIVERSE = [
    # Tech & AI
    "AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","AMD","AVGO","QCOM",
    "INTC","MU","AMAT","LRCX","KLAC","TXN","ADI","MRVL","SMCI","ARM",
    "CRM","NOW","SNOW","PLTR","DDOG","MDB","NET","ZS","PANW","CRWD",
    "ORCL","IBM","HPQ","DELL","WDC","STX","ANET","CDNS","SNPS","ANSS",
    # Semiconductors
    "ASML","TSM","NXPI","ON","MCHP","SWKS","QRVO","MPWR","WOLF","ACLS",
    # AI/Cloud infrastructure
    "GTLB","CFLT","HCP","AISP","SOUN","BBAI","AI",
    # Financials
    "JPM","BAC","GS","MS","WFC","C","BLK","AXP","COF","USB",
    "V","MA","PYPL","SQ","FIS","FISV","GPN","WEX",
    # Healthcare
    "LLY","JNJ","UNH","ABBV","MRK","PFE","TMO","DHR","ABT","BMY",
    "AMGN","GILD","BIIB","VRTX","REGN","MRNA","ISRG","SYK","MDT","BSX",
    # Biotech
    "ASTS","RXRX","EDIT","NTLA","BEAM","CRSP","PACB","ILMN",
    # Energy
    "XOM","CVX","COP","SLB","OXY","PSX","VLO","MPC","HES","DVN",
    "NEE","AEP","SO","DUK","PCG","EXC","ETR","CEG","VST",
    # Industrials
    "RTX","GE","HON","BA","LMT","NOC","GD","TDG","HII","L3H",
    "CAT","DE","EMR","ETN","ITW","PH","ROK","DOV","XYL","GNRC",
    # Consumer
    "WMT","HD","COST","TGT","LOW","MCD","SBUX","NKE","LULU","TPR",
    "AMZN","BKNG","ABNB","UBER","LYFT","DPZ","YUM","CMG","MKC",
    # Real Estate & Infrastructure
    "AMT","PLD","EQIX","CCI","DLR","SBAC","IRM","O","WPC",
    # Materials & Commodities
    "NEM","FCX","SCCO","AA","NUE","CLF","MP","LTHM","ALB","SQM",
    # Comms & Media
    "NFLX","DIS","CMCSA","T","VZ","TMUS","WBD","PARA","FOX","NYT",
    # Space, Defence, New Energy
    "RKLB","ASTS","LUNR","MNTS","RDW",
    "ENPH","FSLR","RUN","ARRY","NOVA","BE","PLUG","BLOOM",
    "OKLO","SMR","NNE","BWX","UUUU",
    # International / EM proxies (US-listed)
    "BABA","JD","PDD","BIDU","SE","GRAB","NU","MELI",
    # ETFs excluded — pure equities only
]


def get_sp500_tickers() -> list[str]:
    """Fetch S&P 500 tickers from Wikipedia. Cached per session."""
    global _sp500_cache
    if _sp500_cache is not None:
        return _sp500_cache
    try:
        table = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            attrs={"id": "constituents"},
        )[0]
        tickers = table["Symbol"].str.replace(".", "-", regex=False).tolist()
        _sp500_cache = [t for t in tickers if isinstance(t, str) and t.isalpha() or "-" in t]
        print(f"[universe] S&P 500 fetched: {len(_sp500_cache)} tickers")
        return _sp500_cache
    except Exception as e:
        print(f"[universe] Wikipedia fetch failed ({e}), using fallback list")
        _sp500_cache = _FALLBACK_UNIVERSE
        return _sp500_cache


def get_universe(notion_tickers: list[str], mode: str = "notion") -> list[str]:
    """
    mode='notion'  — 98 Notion names only
    mode='full'    — S&P 500 + Notion names merged, deduped
    """
    if mode == "notion":
        return list(dict.fromkeys(notion_tickers))   # deduped, order preserved

    sp500 = get_sp500_tickers()
    merged = list(dict.fromkeys(notion_tickers + sp500))
    print(f"[universe] Full universe: {len(merged)} tickers (Notion {len(notion_tickers)} + S&P 500 {len(sp500)})")
    return merged
