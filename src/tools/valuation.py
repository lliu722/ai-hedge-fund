"""
Valuation Monitor — fetch and format key valuation metrics per ticker.
Asset-class aware: growth multiples for tech, P/TBV + ROE for banks,
EV/EBITDA for mature industrials.
"""
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor


BANK_TICKERS = {"JPM", "MS", "GS", "BAC", "C", "WFC", "DB", "HSBC", "BCS"}
COMMODITY_TICKERS = {"GC=F", "CL=F", "BZ=F", "HG=F", "NG=F", "SI=F", "USO", "GLD"}


def _fetch_valuation(ticker: str) -> dict:
    try:
        info = yf.Ticker(ticker).info
        return {
            "ticker": ticker,
            "name": info.get("shortName", ticker),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "market_cap": info.get("marketCap"),
            "pe_trailing": info.get("trailingPE"),
            "pe_forward": info.get("forwardPE"),
            "peg": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "ev_revenue": info.get("enterpriseToRevenue"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "roe": info.get("returnOnEquity"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "fcf": info.get("freeCashflow"),
            "gross_margins": info.get("grossMargins"),
            "operating_margins": info.get("operatingMargins"),
            "debt_to_equity": info.get("debtToEquity"),
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)[:100]}


def _fmt_val(v, pct=False, x=False, mult=1):
    if v is None:
        return "N/A"
    v = v * mult
    if pct:
        return f"{v*100:.1f}%"
    if x:
        return f"{v:.1f}x"
    return f"{v:.2f}"


def get_valuation_message(ticker: str) -> str:
    ticker = ticker.upper()
    d = _fetch_valuation(ticker)

    if "error" in d:
        return f"❌ Could not fetch valuation data for {ticker}: {d['error']}"

    mc = d.get("market_cap") or 0
    mc_str = f"${mc/1e9:.1f}B" if mc >= 1e9 else f"${mc/1e6:.0f}M" if mc else "N/A"

    is_bank = ticker in BANK_TICKERS
    is_commodity = ticker in COMMODITY_TICKERS

    msg = f"📐 <b>Valuation: {ticker}</b>"
    if d.get("name") and d["name"] != ticker:
        msg += f" <i>({d['name']})</i>"
    msg += f"\n<i>{d.get('sector', '')} · {d.get('industry', '')}</i>\n"
    msg += f"Market cap: <b>{mc_str}</b>\n\n"

    if is_commodity:
        msg += "<i>Commodities: valuation via supply/demand fundamentals, not multiples.</i>"
        return msg

    if is_bank:
        msg += "<b>Bank Metrics:</b>\n"
        msg += f"• P/Book: <b>{_fmt_val(d.get('price_to_book'), x=True)}</b>\n"
        msg += f"• ROE: <b>{_fmt_val(d.get('roe'), pct=True)}</b>\n"
        msg += f"• Forward P/E: <b>{_fmt_val(d.get('pe_forward'), x=True)}</b>\n"
        msg += f"• Trailing P/E: <b>{_fmt_val(d.get('pe_trailing'), x=True)}</b>\n"
    else:
        msg += "<b>Earnings & Growth:</b>\n"
        msg += f"• Trailing P/E: <b>{_fmt_val(d.get('pe_trailing'), x=True)}</b>\n"
        msg += f"• Forward P/E: <b>{_fmt_val(d.get('pe_forward'), x=True)}</b>\n"
        msg += f"• PEG Ratio: <b>{_fmt_val(d.get('peg'), x=True)}</b>\n"
        msg += f"• Revenue Growth (YoY): <b>{_fmt_val(d.get('revenue_growth'), pct=True)}</b>\n"
        msg += f"• Earnings Growth (YoY): <b>{_fmt_val(d.get('earnings_growth'), pct=True)}</b>\n\n"

        msg += "<b>Enterprise Value:</b>\n"
        msg += f"• EV/Revenue: <b>{_fmt_val(d.get('ev_revenue'), x=True)}</b>\n"
        msg += f"• EV/EBITDA: <b>{_fmt_val(d.get('ev_ebitda'), x=True)}</b>\n"
        msg += f"• Price/Book: <b>{_fmt_val(d.get('price_to_book'), x=True)}</b>\n\n"

        msg += "<b>Profitability:</b>\n"
        msg += f"• Gross Margin: <b>{_fmt_val(d.get('gross_margins'), pct=True)}</b>\n"
        msg += f"• Operating Margin: <b>{_fmt_val(d.get('operating_margins'), pct=True)}</b>\n"
        msg += f"• ROE: <b>{_fmt_val(d.get('roe'), pct=True)}</b>\n"

        fcf = d.get("fcf")
        if fcf:
            fcf_str = f"${fcf/1e9:.1f}B" if abs(fcf) >= 1e9 else f"${fcf/1e6:.0f}M"
            msg += f"• Free Cash Flow: <b>{fcf_str}</b>\n"

    return msg


def get_valuation_data(ticker: str) -> dict:
    return _fetch_valuation(ticker.upper())
