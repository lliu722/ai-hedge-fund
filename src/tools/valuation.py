"""
Valuation Monitor — fetch and format key valuation metrics per ticker.
Asset-class aware: growth multiples for tech, P/TBV + ROE for banks,
EV/EBITDA for mature industrials.
"""
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor


BANK_TICKERS = {"JPM", "MS", "GS", "BAC", "C", "WFC", "DB", "HSBC", "BCS"}
COMMODITY_TICKERS = {"GC=F", "CL=F", "BZ=F", "HG=F", "NG=F", "SI=F", "USO", "GLD"}

# Closest peers by primary business — used for multiple comparison
PEER_GROUPS = {
    "NVDA":  ["AMD", "AVGO", "INTC"],
    "AMD":   ["NVDA", "INTC", "AVGO"],
    "AVGO":  ["NVDA", "MRVL", "QCOM"],
    "TSM":   ["INTC", "SMCI", "AMAT"],
    "ASML":  ["AMAT", "LRCX", "KLAC"],
    "ARM":   ["NVDA", "INTC", "QCOM"],
    "ALAB":  ["MRVL", "CRDO", "AVGO"],
    "CRDO":  ["ALAB", "MRVL", "LITE"],
    "MU":    ["WDC", "SNDK", "STX"],
    "WDC":   ["MU", "SNDK", "STX"],
    "SNDK":  ["WDC", "MU", "STX"],
    "PLTR":  ["SNOW", "MDB", "DDOG"],
    "APP":   ["TTD", "GOOGL", "META"],
    "MSFT":  ["GOOGL", "AMZN", "META"],
    "GOOGL": ["MSFT", "META", "AMZN"],
    "META":  ["GOOGL", "SNAP", "TTD"],
    "CEG":   ["VST", "TLN", "NRG"],
    "VST":   ["CEG", "TLN", "NRG"],
    "TLN":   ["CEG", "VST", "NRG"],
    "RKLB":  ["ASTS", "BA", "LMT"],
    "ASTS":  ["RKLB", "DISH", "VSAT"],
    "JPM":   ["GS", "MS", "BAC"],
    "GS":    ["MS", "JPM", "BAC"],
    "MS":    ["GS", "JPM", "BAC"],
    "MSTR":  ["COIN", "RIOT", "MARA"],
    "GLW":   ["LITE", "NOK", "CSCO"],
    "LITE":  ["GLW", "CRDO", "IIVI"],
}


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


def _peer_comparison(ticker: str, main: dict) -> str:
    """
    Fetch peer multiples in parallel and return a formatted comparison block
    with a DeepSeek verdict on whether the premium/discount is justified.
    """
    import os, requests
    peers = PEER_GROUPS.get(ticker, [])
    if not peers:
        return ""

    with ThreadPoolExecutor(max_workers=3) as ex:
        peer_data = dict(zip(peers, ex.map(_fetch_valuation, peers)))

    # Build compact comparison rows
    rows = []
    main_fpe = main.get("pe_forward")
    main_rev_growth = main.get("revenue_growth")

    for p, d in peer_data.items():
        if "error" in d:
            continue
        fpe = d.get("pe_forward")
        eveb = d.get("ev_ebitda")
        rg = d.get("revenue_growth")
        fpe_str = f"{fpe:.1f}x" if fpe else "N/A"
        eveb_str = f"{eveb:.1f}x" if eveb else "N/A"
        rg_str = f"{rg*100:.0f}%" if rg else "N/A"
        rows.append(f"• <b>{p}</b>: fwd P/E {fpe_str} · EV/EBITDA {eveb_str} · Rev growth {rg_str}")

    if not rows:
        return ""

    # Format main ticker row for context
    m_fpe = f"{main_fpe:.1f}x" if main_fpe else "N/A"
    m_eveb = f"{main.get('ev_ebitda'):.1f}x" if main.get("ev_ebitda") else "N/A"
    m_rg = f"{main_rev_growth*100:.0f}%" if main_rev_growth else "N/A"

    block = f"\n<b>vs Peers:</b>\n"
    block += f"• <b>{ticker}</b> (this): fwd P/E {m_fpe} · EV/EBITDA {m_eveb} · Rev growth {m_rg}\n"
    block += "\n".join(rows)

    # DeepSeek verdict — is the premium/discount justified?
    try:
        peer_summary = f"{ticker}: fwd P/E {m_fpe}, rev growth {m_rg}\n"
        for p, d in peer_data.items():
            if "error" not in d:
                fpe = f"{d['pe_forward']:.1f}x" if d.get("pe_forward") else "N/A"
                rg = f"{d['revenue_growth']*100:.0f}%" if d.get("revenue_growth") else "N/A"
                peer_summary += f"{p}: fwd P/E {fpe}, rev growth {rg}\n"

        prompt = (
            f"Valuation comparison:\n{peer_summary}\n"
            f"In ONE sentence: is {ticker}'s valuation premium or discount vs peers justified by its growth? "
            f"Be specific about the numbers. Start with 'Premium justified:' / 'Discount unwarranted:' / "
            f"'Trading in line:' / 'Expensive vs growth:' as appropriate."
        )
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 100, "temperature": 0.2},
            timeout=15,
        )
        if r.status_code == 200:
            verdict = r.json()["choices"][0]["message"]["content"].strip()
            block += f"\n\n<i>⚖️ {verdict}</i>"
    except Exception:
        pass

    return block


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

    # Peer comparison block (non-bank, non-commodity)
    if not is_bank and not is_commodity:
        peer_block = _peer_comparison(ticker, d)
        if peer_block:
            msg += peer_block

    return msg


def get_valuation_data(ticker: str) -> dict:
    return _fetch_valuation(ticker.upper())
