"""
AI Stock Recommendation Engine
Three lenses: Screener + Gap Analysis + Catalyst Picks
Four personas: Cathie Wood, Druckenmiller, Damodaran + Li Wei (HK/China)
Based on the original virattt/ai-hedge-fund investor persona architecture.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from src.tools.llm import call_deepseek

CATHIE_WOOD = (
    "You are Cathie Wood, CEO of ARK Invest. Your philosophy: disruptive tech, "
    "massive TAM, AI/robotics/fintech, long-term exponential growth over short-term profit. "
    "You believe the biggest risk is NOT owning disruptive innovation. "
    "Given the watchlist data below, identify 2-3 names you would buy or add to right now "
    "and explain why in your own voice. Be specific."
)

DRUCKENMILLER = (
    "You are Stanley Druckenmiller, legendary macro investor. Your philosophy: seek asymmetric "
    "risk-reward, big upside limited downside. Follow momentum. Be aggressive when conditions "
    "favour it. Concentrate in your best ideas. "
    "Given the watchlist data below, identify 2-3 names with the most asymmetric setup right now "
    "and explain the risk-reward in your own voice."
)

DAMODARAN = (
    "You are Aswath Damodaran, Professor of Finance at NYU Stern. Your philosophy: every asset "
    "has intrinsic value from cash flows, growth, and risk. Price and value differ. Do not "
    "overpay even for a great business. Biggest mistakes come from confusing narrative with numbers. "
    "Given the watchlist data below, identify 2-3 names offering best value vs growth potential "
    "and explain your valuation logic."
)

LI_WEI = (
    "You are Li Wei, Senior Asia Equity Strategist with 20 years covering Greater China and "
    "ASEAN equities. Former Goldman Sachs Hong Kong desk. You understand HKEX-specific dynamics "
    "that US-focused analysts miss:\n"
    "• H-share discounts to ADR equivalents — structural discount that can compress as Southbound "
    "Connect inflows accelerate\n"
    "• PBOC policy cycle — rate cuts, RRR reductions, and liquidity injections move HK/China "
    "equities faster than US Fed moves\n"
    "• China regulatory environment — platform economy crackdown (2020-22) is largely behind us, "
    "Beijing now needs big tech to drive growth and employment\n"
    "• Southbound Stock Connect flows — mainland money chasing HK-listed names with HK dollar "
    "exposure is a technical tailwind\n"
    "• Geopolitical risk — Taiwan flashpoints, US-China export controls, Hong Kong political "
    "stability — always price these in\n"
    "• Earnings calendar — Chinese companies report on a different schedule; results are "
    "in HKD/RMB and margins are structurally different from US peers\n"
    "• Policy signalling — Caixin PMI, State Council announcements, and CITIC/CICC reports "
    "move before Bloomberg consensus catches up\n"
    "Given the HK/China watchlist data below, identify 1-2 names with the best near-term "
    "setup and explain the thesis through your Asia lens. Be direct about the specific "
    "China/HK catalyst you are watching. Flag any geopolitical or regulatory risks."
)

EXCLUDE_SUFFIXES = (".HK", ".SS", ".SZ", ".TW", ".KS", ".T")
EXCLUDE_TICKERS = {"BTC", "ETH", "SOL", "MATIC", "POL", "BTC-USD", "^VIX", "^HSI"}
HK_CHINA_SUFFIXES = (".HK", ".SS", ".SZ")


def _call(system, user, tokens=400):
    return call_deepseek(user, system=system, max_tokens=tokens, temperature=0.4, timeout=45)


def _is_us(ticker):
    if ticker in EXCLUDE_TICKERS:
        return False
    for s in EXCLUDE_SUFFIXES:
        if ticker.endswith(s):
            return False
    return True


def _is_hk_china(ticker):
    return any(ticker.endswith(s) for s in HK_CHINA_SUFFIXES)


def _screener(holdings, prices):
    BUY = {"Buy", "Spec. Buy", "Allocate"}
    out = []
    for ticker, data in holdings.items():
        if data.get("rating", "") not in BUY:
            continue
        if not _is_us(ticker):
            continue
        p = prices.get(ticker, {})
        out.append({
            "ticker": ticker,
            "name": data.get("name", ticker),
            "sector": data.get("sector", ""),
            "rating": data.get("rating", ""),
            "change": p.get("change_pct") if p else None,
            "price": p.get("price") if p else None,
            "held": (data.get("shares") or 0) > 0,
            "thesis": data.get("thesis", ""),
        })
    out.sort(key=lambda x: (x["change"] is None, -(x["change"] or 0)))
    return out


def _gaps(holdings):
    sm = {}
    for ticker, data in holdings.items():
        sec = data.get("sector", "Unknown")
        if sec not in sm:
            sm[sec] = {"held": [], "buy_not_held": []}
        held = (data.get("shares") or 0) > 0
        rated_buy = data.get("rating", "") in {"Buy", "Spec. Buy", "Allocate"}
        if held:
            sm[sec]["held"].append(ticker)
        elif rated_buy and _is_us(ticker):
            sm[sec]["buy_not_held"].append(ticker)
    return {sec: d["buy_not_held"] for sec, d in sm.items() if d["buy_not_held"]}


def _catalysts(holdings, earnings):
    BUY = {"Buy", "Spec. Buy", "Allocate"}
    out = []
    for ticker, earn in earnings.items():
        days = earn.get("days_until")
        if days is None or days < 0 or days > 14:
            continue
        h = holdings.get(ticker, {})
        if h.get("rating", "") not in BUY:
            continue
        out.append({"ticker": ticker, "name": h.get("name", ticker), "days": days, "date": earn.get("date", ""), "rating": h.get("rating", "")})
    out.sort(key=lambda x: x["days"])
    return out


def _hk_screener(holdings, prices):
    """Screener for HK/China-listed names only."""
    out = []
    for ticker, data in holdings.items():
        if not _is_hk_china(ticker):
            continue
        p = prices.get(ticker, {})
        out.append({
            "ticker": ticker,
            "name": data.get("name", ticker),
            "sector": data.get("sector", ""),
            "rating": data.get("rating", ""),
            "change": p.get("change_pct") if p else None,
            "price": p.get("price") if p else None,
            "held": (data.get("shares") or 0) > 0,
            "thesis": data.get("thesis", ""),
        })
    out.sort(key=lambda x: (x["change"] is None, -(x["change"] or 0)))
    return out


def _build_hk_data_text(hk_screener):
    """Format HK/China watchlist data for the Li Wei persona."""
    if not hk_screener:
        return "No HK/China names in watchlist."
    s = "HK/CHINA WATCHLIST (HKEX, Shanghai, Shenzhen listed):\n"
    for c in hk_screener:
        chg = (str(round(c["change"], 1)) + "% today") if c["change"] is not None else "price unavailable"
        held = "HELD" if c["held"] else "WATCHING"
        rating = c["rating"] or "No rating"
        s += f"- {c['ticker']} ({c['name']}) | {rating} | {chg} | {c['sector']} | {held}\n"
        if c["thesis"]:
            s += f"  Thesis: {c['thesis'][:150]}\n"
    return s


def _build_data_text(screener, gaps, catalyst_list):
    s = "TOP RATED NAMES (US-listed, sorted by momentum):\n"
    for c in screener[:20]:
        chg = (str(round(c["change"], 1)) + "% today") if c["change"] is not None else "price data unavailable"
        held = "HELD" if c["held"] else "NOT HELD"
        s += "- " + c["ticker"] + " (" + c["name"] + ") | " + c["rating"] + " | " + chg + " | " + c["sector"] + " | " + held + "\n"
        if c["thesis"]:
            s += "  Thesis: " + c["thesis"][:120] + "\n"
    g = "\nSECTOR GAPS (buy-rated but not yet in portfolio):\n"
    for sec, names in gaps.items():
        g += "- " + sec + ": " + ", ".join(names) + "\n"
    cat = "\nEARNINGS CATALYSTS (buy-rated, next 14 days):\n"
    if catalyst_list:
        for c in catalyst_list:
            cat += "- " + c["ticker"] + " (" + c["name"] + ") reports in " + str(c["days"]) + " days | " + c["rating"] + "\n"
    else:
        cat += "None.\n"
    return s + g + cat


def get_recommendations():
    from src.tools.notion_holdings import get_holdings_cached
    from src.tools.prices import get_live_prices
    from src.tools.earnings_calendar import get_earnings_dates
    from dotenv import load_dotenv
    load_dotenv()

    print("[" + datetime.now().strftime("%H:%M") + "] Running recommendation engine...")
    holdings = get_holdings_cached()
    tickers = list(holdings.keys())
    BUY = {"Buy", "Spec. Buy", "Allocate"}
    buy_tickers = [t for t, d in holdings.items() if d.get("rating", "") in BUY]

    executor = ThreadPoolExecutor(max_workers=7)

    # T=0: prices + earnings both start simultaneously
    fp = executor.submit(get_live_prices, tickers)
    fe = executor.submit(get_earnings_dates, buy_tickers)

    # Block on prices only — earnings keeps running in background
    prices = fp.result()
    print("[" + datetime.now().strftime("%H:%M") + "] Prices done. Starting persona debates...")

    # Compute screeners + gaps (instant) then kick off all personas immediately
    screener = _screener(holdings, prices)
    hk_screener = _hk_screener(holdings, prices)
    gaps = _gaps(holdings)
    data_text = _build_data_text(screener, gaps, [])
    hk_data_text = _build_hk_data_text(hk_screener)

    # All 4 personas run in parallel while earnings still fetching in background
    fc = executor.submit(_call, CATHIE_WOOD, data_text, 350)
    fd = executor.submit(_call, DRUCKENMILLER, data_text, 350)
    fv = executor.submit(_call, DAMODARAN, data_text, 350)
    fhk = executor.submit(_call, LI_WEI, hk_data_text, 350)

    # Collect all results
    cathie_view = fc.result()
    druck_view = fd.result()
    damodaran_view = fv.result()
    li_wei_view = fhk.result()
    try:
        earnings_data = fe.result(timeout=25)
    except Exception:
        earnings_data = {}
    executor.shutdown(wait=False)

    catalyst_list = _catalysts(holdings, earnings_data)

    # ── US picks synthesis ────────────────────────────────────────────────────
    synthesis_prompt = (
        "You are a senior portfolio manager synthesising views from three legendary investors.\n\n"
        "CATHIE WOOD (ARK Invest - disruptive innovation):\n" + cathie_view + "\n\n"
        "STANLEY DRUCKENMILLER (macro, asymmetric risk-reward):\n" + druck_view + "\n\n"
        "ASWATH DAMODARAN (NYU - valuation discipline):\n" + damodaran_view + "\n\n"
    )
    if catalyst_list:
        synthesis_prompt += "EARNINGS CATALYSTS THIS FORTNIGHT:\n"
        for c in catalyst_list:
            synthesis_prompt += "- " + c["ticker"] + " reports in " + str(c["days"]) + " days\n"
        synthesis_prompt += "\n"
    synthesis_prompt += (
        "Produce a ranked shortlist of 3-5 US stocks to act on NOW.\n"
        "For each pick:\n"
        "- Ticker + name\n"
        "- Verdict: Buy / Add to existing / Watch for entry\n"
        "- Which investors agree (Cathie / Druck / Damodaran)\n"
        "- Why now: 1-2 specific sentences\n"
        "- Portfolio gap it fills if any\n\n"
        "Rules: max 400 words, no tables, no headers, number picks 1. 2. 3., "
        "direct and opinionated, use <b>bold</b> for tickers and verdicts."
    )

    print("[" + datetime.now().strftime("%H:%M") + "] Synthesising US picks...")
    us_final = _call(
        "You are a decisive senior portfolio manager. Make clear, specific, actionable recommendations.",
        synthesis_prompt, 600
    )

    # ── HK/China synthesis ────────────────────────────────────────────────────
    hk_synthesis_prompt = (
        "You are a senior portfolio manager synthesising Li Wei's Asia equity view.\n\n"
        "LI WEI (Asia Equity Strategist — Greater China):\n" + li_wei_view + "\n\n"
        "Summarise into 1-2 actionable HK/China picks. For each:\n"
        "- Ticker + name\n"
        "- Verdict: Buy / Add / Watch\n"
        "- The specific HK/China catalyst Li Wei is watching\n"
        "- Key risk to flag\n\n"
        "Rules: max 200 words, no tables, number picks 1. 2., "
        "use <b>bold</b> for tickers. If Li Wei is not bullish on any name, say so explicitly."
    )

    print("[" + datetime.now().strftime("%H:%M") + "] Synthesising HK/China picks...")
    hk_final = _call(
        "You are a decisive senior portfolio manager covering Greater China equities.",
        hk_synthesis_prompt, 350
    )

    date_str = datetime.now().strftime("%d %B %Y")
    out = (
        "🎯 <b>AI Stock Picks — " + date_str + "</b>\n\n"
        + us_final
        + "\n\n<i>Cathie Wood (innovation) · Druckenmiller (macro) · Damodaran (valuation)</i>"
    )
    if hk_screener:
        out += (
            "\n\n🇭🇰 <b>HK/China Picks — Li Wei</b>\n\n"
            + hk_final
            + "\n\n<i>Li Wei (Asia Equity Strategist · Greater China)</i>"
        )
    return out


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    print(get_recommendations())
