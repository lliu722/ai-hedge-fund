"""
B2 — Data & Info Sources for the Equity L/S desk.

Single file, one section per source. Each section is independent — a failure
in one source never blocks another. Every fetch returns a plain dict so callers
don't need to know which library produced it.

Sections:
  1. Market Data        — yfinance primary, OpenBB cross-check
  2. Portfolio / User   — live reads from B3 portfolio_db
  3. SEC Filings        — SEC EDGAR via requests (returns a flat list of filings)
  4. News / Event Feed  — Tavily (copied from src/tools/news_fetcher.py)
  5. Earnings Calendar  — yfinance .calendar
  6. Internal Calcs     — momentum, valuation, quality, liquidity, risk, composite
  7. Research Library   — live reads from B4 knowledge_base
  8. TradingAgents      — latest trader output from B4 (written by B5 runs)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

# ══════════════════════════════════════════════════════════════════════════════
# 1. MARKET DATA
# Primary: yfinance .info  |  Cross-check / extras: OpenBB equity
# ══════════════════════════════════════════════════════════════════════════════

def get_market_data(ticker: str) -> dict:
    """
    Full market data for one ticker.
    yfinance is the primary source. OpenBB fills gaps and cross-checks key fields.
    Returns a flat dict — keys described inline.
    """
    yf_data = _yf_fetch(ticker)
    obb_data = _obb_fetch(ticker)
    return _merge(yf_data, obb_data)


def _yf_fetch(ticker: str) -> dict:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        t = yf.Ticker(ticker)

        # Quarterly financials for margin/FCF trend
        try:
            quarterly_financials = t.quarterly_financials.to_dict() if t.quarterly_financials is not None else {}
        except Exception:
            quarterly_financials = {}

        try:
            quarterly_cashflow = t.quarterly_cashflow.to_dict() if t.quarterly_cashflow is not None else {}
        except Exception:
            quarterly_cashflow = {}

        return {
            # ── Price & Quote ──────────────────────────────────────────────
            "price":                info.get("currentPrice") or info.get("regularMarketPrice"),
            "prev_close":           info.get("previousClose"),
            "open":                 info.get("open"),
            "day_high":             info.get("dayHigh"),
            "day_low":              info.get("dayLow"),
            "change_pct":           info.get("regularMarketChangePercent"),
            # ── Range & Volume ─────────────────────────────────────────────
            "week52_high":          info.get("fiftyTwoWeekHigh"),
            "week52_low":           info.get("fiftyTwoWeekLow"),
            "volume":               info.get("regularMarketVolume"),
            "avg_volume_10d":       info.get("averageVolume10days"),
            # ── Market Cap & Liquidity ─────────────────────────────────────
            "market_cap":           info.get("marketCap"),
            "float_shares":         info.get("floatShares"),
            "shares_outstanding":   info.get("sharesOutstanding"),
            # ── Volatility / Risk ──────────────────────────────────────────
            "beta":                 info.get("beta"),
            # ── Valuation Multiples ────────────────────────────────────────
            "trailing_pe":          info.get("trailingPE"),
            "forward_pe":           info.get("forwardPE"),
            "price_to_book":        info.get("priceToBook"),
            "price_to_sales":       info.get("priceToSalesTrailingTwelveMonths"),
            "ev_to_ebitda":         info.get("enterpriseToEbitda"),
            "ev_to_revenue":        info.get("enterpriseToRevenue"),
            # ── Basic Fundamentals ─────────────────────────────────────────
            "revenue":              info.get("totalRevenue"),
            "revenue_growth":       info.get("revenueGrowth"),
            "gross_margins":        info.get("grossMargins"),
            "operating_margins":    info.get("operatingMargins"),
            "profit_margins":       info.get("profitMargins"),
            "ebitda":               info.get("ebitda"),
            "free_cash_flow":       info.get("freeCashflow"),
            "return_on_equity":     info.get("returnOnEquity"),
            "return_on_assets":     info.get("returnOnAssets"),
            # ── Earnings ──────────────────────────────────────────────────
            "eps_trailing":         info.get("trailingEps"),
            "eps_forward":          info.get("forwardEps"),
            "earnings_growth":      info.get("earningsGrowth"),
            # ── Analyst Estimates ──────────────────────────────────────────
            "target_mean_price":    info.get("targetMeanPrice"),
            "target_high_price":    info.get("targetHighPrice"),
            "target_low_price":     info.get("targetLowPrice"),
            "analyst_count":        info.get("numberOfAnalystOpinions"),
            "recommendation":       info.get("recommendationKey"),
            # ── Debt & Leverage ────────────────────────────────────────────
            "debt_to_equity":       info.get("debtToEquity"),
            "current_ratio":        info.get("currentRatio"),
            "quick_ratio":          info.get("quickRatio"),
            # ── Ownership & Short Interest ─────────────────────────────────
            "short_percent_float":  info.get("shortPercentOfFloat"),
            "institutions_pct":     info.get("institutionsPercentHeld"),
            "insiders_pct":         info.get("heldPercentInsiders"),
            # ── Dividend ──────────────────────────────────────────────────
            "dividend_yield":       info.get("dividendYield"),
            # ── Metadata ──────────────────────────────────────────────────
            "name":                 info.get("shortName") or info.get("longName"),
            "sector":               info.get("sector"),
            "industry":             info.get("industry"),
            "country":              info.get("country"),
            "exchange":             info.get("exchange"),
            "currency":             info.get("currency"),
            # ── Trend data (raw — callers derive trend) ────────────────────
            "_quarterly_financials": quarterly_financials,
            "_quarterly_cashflow":   quarterly_cashflow,
            "_source":               "yfinance",
        }
    except Exception as e:
        return {"_source": "yfinance", "_error": str(e)}


def _obb_fetch(ticker: str) -> dict:
    """
    OpenBB cross-check. Fetches fields yfinance may miss or report differently.
    Graceful — returns empty dict on any failure (OpenBB needs API keys for some providers).
    """
    try:
        from openbb import obb
        result = {}

        # Analyst price targets (consensus)
        try:
            pt = obb.equity.estimates.price_target(symbol=ticker, provider="yfinance")
            if pt and pt.results:
                r = pt.results[0]
                result["obb_target_price"] = getattr(r, "price_target", None)
                result["obb_analyst_firm"] = getattr(r, "analyst_firm", None)
        except Exception:
            pass

        # Earnings estimates
        try:
            est = obb.equity.estimates.consensus(symbol=ticker, provider="yfinance")
            if est and est.results:
                r = est.results[0]
                result["obb_eps_estimate"] = getattr(r, "eps_consensus", None)
        except Exception:
            pass

        result["_obb_source"] = "openbb/yfinance"
        return result
    except Exception:
        return {}


def _merge(yf: dict, obb: dict) -> dict:
    """Merge yfinance + OpenBB. yfinance wins on conflicts."""
    merged = {**obb, **yf}  # yf overwrites obb on key clash
    merged["_sources"] = ["yfinance", "openbb"] if obb.get("_obb_source") else ["yfinance"]
    return merged


# ══════════════════════════════════════════════════════════════════════════════
# 2. PORTFOLIO / USER DATA
# Live reads from B3 portfolio_db (standalone SQLite)
# ══════════════════════════════════════════════════════════════════════════════

def get_holdings(account: str | None = None) -> list[dict]:
    """Current holdings from the portfolio DB."""
    from src.desks.equity_ls.infrastructure.b3_portfolio import portfolio_db
    return portfolio_db.get_holdings(account)


def get_watchlist() -> list[dict]:
    """Watchlist from the portfolio DB."""
    from src.desks.equity_ls.infrastructure.b3_portfolio import portfolio_db
    return portfolio_db.get_watchlist()


def get_trade_journal(ticker: str | None = None) -> list[dict]:
    """Trade history from the portfolio DB."""
    from src.desks.equity_ls.infrastructure.b3_portfolio import portfolio_db
    return portfolio_db.get_trades(ticker)


# ══════════════════════════════════════════════════════════════════════════════
# 3. SEC FILINGS
# Copied from src/tools/sec_filings.py — adapted to return plain dicts
# ══════════════════════════════════════════════════════════════════════════════

def get_sec_filings(ticker: str, filing_types: list[str] | None = None) -> list[dict]:
    """
    Fetch recent SEC filings for a ticker.
    filing_types: e.g. ["10-K", "10-Q", "8-K"]. Defaults to all three.
    """
    if filing_types is None:
        filing_types = ["10-K", "10-Q", "8-K"]
    try:
        import requests
        # Get CIK from SEC EDGAR
        search = requests.get(
            f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom"
            f"&startdt={(datetime.now()-timedelta(days=365)).strftime('%Y-%m-%d')}"
            f"&enddt={datetime.now().strftime('%Y-%m-%d')}&forms={','.join(filing_types)}",
            headers={"User-Agent": "ai-hedge-fund research@example.com"},
            timeout=10,
        )
        hits = search.json().get("hits", {}).get("hits", [])
        results = []
        for h in hits[:5]:
            src = h["_source"]
            cik = (src.get("ciks") or [""])[0].lstrip("0")
            adsh = src.get("adsh", "")
            results.append({
                "ticker": ticker,
                "form": src.get("form"),
                "filed": src.get("file_date"),
                "period_ending": src.get("period_ending"),
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{adsh}-index.htm",
            })
        return results
    except Exception as e:
        return [{"ticker": ticker, "_error": str(e)}]


# ══════════════════════════════════════════════════════════════════════════════
# 4. NEWS / EVENT FEED
# Copied from src/tools/news_fetcher.py — Tavily
# ══════════════════════════════════════════════════════════════════════════════

def get_news(ticker: str, days_back: int = 3) -> list[dict]:
    """Fetch recent news for a ticker via Tavily."""
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY", ""))
        response = client.search(
            query=f"{ticker} stock news",
            topic="news",
            days=days_back,
            max_results=10,
        )
        return [
            {
                "title":   a.get("title"),
                "url":     a.get("url"),
                "source":  a.get("source"),
                "date":    a.get("published_date"),
                "snippet": a.get("content", "")[:300],
            }
            for a in response.get("results", [])
        ]
    except Exception as e:
        return [{"ticker": ticker, "_error": str(e)}]


# ══════════════════════════════════════════════════════════════════════════════
# 5. EARNINGS CALENDAR
# yfinance .calendar — next earnings date + estimates
# ══════════════════════════════════════════════════════════════════════════════

def get_earnings_dates(ticker: str) -> dict:
    """Next earnings date + consensus EPS/revenue estimates."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None:
            return {"ticker": ticker, "earnings_date": None}
        # cal is a dict in newer yfinance versions
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date", [])
            return {
                "ticker":           ticker,
                "earnings_date":    str(dates[0]) if dates else None,
                "eps_estimate":     cal.get("EPS Estimate"),
                "revenue_estimate": cal.get("Revenue Estimate"),
            }
        # legacy: DataFrame
        return {
            "ticker":        ticker,
            "earnings_date": str(cal.columns[0].date()) if not cal.empty else None,
        }
    except Exception as e:
        return {"ticker": ticker, "_error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# 6. INTERNAL CALCULATIONS
# Derived signals: momentum, valuation score, quality, liquidity, risk, composite
# Logic copied from src/tools/quant/factors.py — adapted for single ticker
# ══════════════════════════════════════════════════════════════════════════════

def get_internal_scores(ticker: str) -> dict:
    """
    Compute all internal scores for a single ticker.
    Returns: momentum, valuation_score, quality_score, liquidity_score,
             risk_score, composite_score, rsi, signal (BUY/WATCH/AVOID).
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info

        # Momentum: 12-1 month return
        hist = t.history(period="13mo", interval="1mo", auto_adjust=True)
        mom = None
        if len(hist) >= 13:
            ret_12 = (hist["Close"].iloc[-2] - hist["Close"].iloc[0]) / hist["Close"].iloc[0]
            ret_1  = (hist["Close"].iloc[-1] - hist["Close"].iloc[-2]) / hist["Close"].iloc[-2]
            mom = float(ret_12 - ret_1)

        # RSI (14-day)
        daily = t.history(period="3mo", interval="1d", auto_adjust=True)
        rsi = _compute_rsi(daily["Close"].dropna().tolist()) if len(daily) >= 15 else None

        # Valuation score: 1 / forward PE (higher = cheaper)
        fpe = info.get("forwardPE") or info.get("trailingPE")
        val_score = (1 / fpe) if fpe and fpe > 0 else None

        # Quality score: (ROE + gross margin) / 2
        roe = info.get("returnOnEquity")
        gm  = info.get("grossMargins")
        if roe is not None and gm is not None:
            quality = (roe + gm) / 2
        elif gm is not None:
            quality = gm
        else:
            quality = None

        # Liquidity score: avg daily volume proxy (normalised to 0-1, capped at 10M shares)
        vol = info.get("averageVolume") or 0
        liquidity = min(vol / 10_000_000, 1.0)

        # Risk score: beta proxy (lower beta = lower risk score)
        beta = info.get("beta")
        risk = abs(beta) if beta is not None else None

        # Composite: 40% momentum, 30% quality, 30% value (same weights as factors.py)
        scores = [s for s in [mom, quality, val_score] if s is not None]
        composite = (
            0.4 * (mom or 0) + 0.3 * (quality or 0) + 0.3 * (val_score or 0)
            if len(scores) >= 2 else None
        )

        # Signal
        if composite is not None:
            signal = "BUY" if composite > 0.15 else "AVOID" if composite < -0.05 else "WATCH"
        else:
            signal = "WATCH"

        return {
            "ticker":          ticker,
            "momentum":        round(mom, 4) if mom is not None else None,
            "rsi":             round(rsi, 1) if rsi is not None else None,
            "valuation_score": round(val_score, 4) if val_score is not None else None,
            "quality_score":   round(quality, 4) if quality is not None else None,
            "liquidity_score": round(liquidity, 4),
            "risk_score":      round(risk, 2) if risk is not None else None,
            "composite_score": round(composite, 4) if composite is not None else None,
            "signal":          signal,
        }
    except Exception as e:
        return {"ticker": ticker, "_error": str(e)}


def _compute_rsi(closes: list, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    if not gains:
        return 0.0
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


# ══════════════════════════════════════════════════════════════════════════════
# 7. RESEARCH REPORT LIBRARY  (B4 knowledge_base)
# ══════════════════════════════════════════════════════════════════════════════

def get_research_reports(ticker: str, report_type: str | None = None) -> list[dict]:
    """Saved research documents for a ticker from the B4 knowledge base."""
    from src.desks.equity_ls.infrastructure.b4_knowledge_base import knowledge_base
    return knowledge_base.get_reports(ticker, report_type)


def get_kb_summary(ticker: str) -> dict:
    """Quick KB summary: report count, current thesis, latest agent signal."""
    from src.desks.equity_ls.infrastructure.b4_knowledge_base import knowledge_base
    return knowledge_base.get_kb_summary(ticker)


# ══════════════════════════════════════════════════════════════════════════════
# 8. TRADINGAGENTS
# B5 pipeline runs save agent outputs to B4; this reads the latest trader view.
# ══════════════════════════════════════════════════════════════════════════════

def get_trading_agent_opinion(ticker: str) -> dict:
    """Latest TradingAgents trader output for a ticker (saved by B5 into B4).
    Empty dict if the name has never been run through the pipeline."""
    from src.desks.equity_ls.infrastructure.b4_knowledge_base import knowledge_base
    return knowledge_base.get_latest_agent_output(ticker, "trader") or {}
