"""
Theme Analysis Layer — covers ALL portfolio themes, not just AI infrastructure.
Each position maps to a primary investment thesis. Each thesis has its own
signals, search queries, and what to watch for.
"""
import os
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime


# ── Ticker → Thesis mapping ───────────────────────────────────────────────────

THESIS_MAP = {
    # AI Infrastructure
    "NVDA": "AI Infrastructure", "AMD": "AI Infrastructure", "ALAB": "AI Infrastructure",
    "CRDO": "AI Infrastructure", "TSM": "AI Infrastructure", "ASML": "AI Infrastructure",
    "ARM":  "AI Infrastructure", "AVGO": "AI Infrastructure", "INTC": "AI Infrastructure",
    "SMCI": "AI Infrastructure",

    # Memory Cycle Recovery
    "MU": "Memory Cycle", "WDC": "Memory Cycle", "SNDK": "Memory Cycle", "DRAM": "Memory Cycle",

    # Energy & Power Grid
    "GEV": "Energy & Power", "BE": "Energy & Power", "CEG": "Energy & Power",
    "VST": "Energy & Power", "TLN": "Energy & Power", "SEI": "Energy & Power",
    "OKLO": "Energy & Power",

    # Banks & Rate Cycle
    "JPM": "Banks & Rates", "GS": "Banks & Rates", "MS": "Banks & Rates", "GE": "Banks & Rates",

    # Space & Satellite
    "RKLB": "Space", "ASTS": "Space", "SPCX": "Space",

    # Networking & Optical
    "GLW": "Networking & Optical", "LITE": "Networking & Optical",
    "CSCO": "Networking & Optical", "NOK": "Networking & Optical",

    # Software & Data
    "PLTR": "Software & Data", "APP": "Software & Data", "GOOGL": "Software & Data",
    "MSFT": "Software & Data", "META": "Software & Data", "MSTR": "Software & Data",

    # Defence
    "LMT": "Defence",

    # Quantum
    "IONQ": "Quantum",

    # Crypto
    "BTC": "Crypto", "ETH": "Crypto", "SOL": "Crypto",

    # Commodities (for reference)
    "MP": "Rare Earth / Materials",
}


# ── Per-theme thesis, signals, and search context ─────────────────────────────

THEME_THESIS = {
    "Memory Cycle": {
        "one_liner": "DRAM/NAND oversupply cycle ending — pricing recovery + AI demand absorption.",
        "thesis": (
            "Memory producers (MU, WDC, SNDK) are inflecting from the deepest margin trough "
            "in a decade. DRAM spot prices are recovering as AI server demand absorbs capacity "
            "and PC/mobile restocking begins. The thesis: pricing power returns faster than "
            "consensus expects because AI training runs consume 8-10x the DRAM of traditional workloads."
        ),
        "signals": [
            "DRAM spot price (DDR5 and HBM)",
            "NAND contract pricing",
            "MU/WDC inventory days on hand",
            "PC and smartphone shipment data",
            "Hyperscaler memory spend in earnings calls",
        ],
        "search_query": "DRAM spot price memory cycle inventory recovery pricing HBM 2026",
        "watch_for": "Price floor confirmation, inventory normalisation, first positive guidance revision from MU",
        "bear_flag": "Renewed oversupply, DRAM price reversal, hyperscaler capex cut",
    },

    "Energy & Power": {
        "one_liner": "AI data centre power shortage — nuclear + gas peakers + grid infrastructure cycle.",
        "thesis": (
            "AI data centres are consuming power faster than the grid can supply it. This creates "
            "a multi-year structural electricity shortage benefiting power generators (CEG, VST, TLN), "
            "grid equipment makers (GEV), and clean power developers (BE, OKLO). "
            "Nuclear is the only always-on carbon-free source at scale — policy tailwind accelerating."
        ),
        "signals": [
            "PJM capacity auction clearing prices",
            "New data centre power contracts and announced MW",
            "Nuclear permitting and SMR policy developments",
            "GEV and Siemens Energy order backlog",
            "Grid interconnection queue length (DOE data)",
            "Natural gas storage and prices",
        ],
        "search_query": "data center power demand electricity grid nuclear SMR energy 2026",
        "watch_for": "New hyperscaler power deals, nuclear permitting progress, GEV order book updates",
        "bear_flag": "Grid build-out faster than expected, AI capex slowdown reducing power demand",
    },

    "Banks & Rates": {
        "one_liner": "Rate normalisation + M&A revival — NIM expansion and deal flow reopening.",
        "thesis": (
            "US money centre banks (JPM, GS, MS) benefit from: (1) rate cuts normalising the "
            "yield curve and expanding net interest margins, (2) M&A and IPO pipeline that froze "
            "in 2022-23 now thawing as rates fall, (3) elevated trading revenue from volatility. "
            "GS and MS are disproportionately exposed to capital markets revival."
        ),
        "signals": [
            "Fed Funds futures (rate cut probability)",
            "10Y-2Y yield curve spread",
            "Investment banking fee revenue",
            "M&A announced deal volume",
            "IPO pipeline and calendar",
            "Loan growth and credit quality",
        ],
        "search_query": "bank M&A IPO deal flow Fed rate cut investment banking 2026",
        "watch_for": "Fed cut confirmation, large M&A deals announced, IB fee guidance upgrades",
        "bear_flag": "Credit cycle turning, loan losses rising, rate cuts delayed, deal activity stalling",
    },

    "Space": {
        "one_liner": "Direct-to-cell satellite + launch cost deflation — new connectivity markets opening.",
        "thesis": (
            "ASTS (AST SpaceMobile) is building the first space-based direct-to-cell network — "
            "connects any smartphone without hardware changes. RKLB (Rocket Lab) is the only "
            "independent small-launch provider at scale. The thesis: launch cost deflation from "
            "SpaceX is paradoxically bullish for the ecosystem by making constellation deployment viable."
        ),
        "signals": [
            "ASTS satellite deployment progress and coverage milestones",
            "Carrier partnership announcements (AT&T, Verizon, Vodafone)",
            "FCC spectrum licensing",
            "RKLB launch manifest and backlog",
            "SpaceX competitive moves",
        ],
        "search_query": "ASTS AST SpaceMobile satellite direct cell RKLB Rocket Lab launch 2026",
        "watch_for": "ASTS commercial service launch, new carrier deals, RKLB neutron rocket progress",
        "bear_flag": "Spectrum challenges, satellite deployment delays, SpaceX entering direct competition",
    },

    "Networking & Optical": {
        "one_liner": "AI cluster interconnect driving 800G optical cycle — fibre and transceiver shortage.",
        "thesis": (
            "AI training clusters require massive internal bandwidth — 800G and eventually 1.6T "
            "optical transceivers connecting thousands of GPUs. GLW (Corning) supplies the fibre "
            "and is seeing genuine shortage pricing. LITE (Coherent) and CRDO (Credo) ride the "
            "same wave. This is a picks-and-shovels play on AI infrastructure build-out."
        ),
        "signals": [
            "800G optical transceiver shipments and pricing",
            "GLW optical fibre order backlog",
            "Hyperscaler networking capex disclosures",
            "LITE/Coherent revenue guidance",
            "400G→800G upgrade cycle progress",
        ],
        "search_query": "optical networking 800G fibre hyperscaler AI interconnect GLW Corning LITE 2026",
        "watch_for": "Fibre pricing inflection, 800G ramp confirmation, hyperscaler networking capex beats",
        "bear_flag": "Overcapacity in transceivers, hyperscaler networking spend cut",
    },

    "AI Infrastructure": {
        "one_liner": "Multi-year AI compute buildout — picks-and-shovels outperform applications near term.",
        "thesis": (
            "The AI infrastructure build-out is a multi-year capex cycle. Semiconductors (NVDA, AMD), "
            "foundry (TSM), lithography (ASML), and chip IP (ARM) are the core. NVDA dominant "
            "but diversification to ALAB/CRDO accelerating as hyperscalers build custom silicon. "
            "The risk: overbuild if AI monetisation disappoints."
        ),
        "signals": [
            "Hyperscaler capex guidance (Microsoft, Google, Meta, Amazon)",
            "NVDA GPU allocation and lead times",
            "CoWoS and HBM packaging capacity",
            "AI model training run size and cost",
            "Inference demand and monetisation metrics",
        ],
        "search_query": "AI infrastructure capex NVDA hyperscaler data center GPU demand 2026",
        "watch_for": "Hyperscaler capex beats, NVDA Blackwell Ultra availability, custom silicon acceleration",
        "bear_flag": "Hyperscaler capex cut, AI revenue disappointment, GPU inventory build",
    },

    "Software & Data": {
        "one_liner": "AI monetisation at the application layer — PLTR, APP, MSFT, META.",
        "thesis": (
            "PLTR: only enterprise AI platform with proven government and commercial deployments. "
            "APP (AppLovin): AI-driven ad targeting moat, dominant in mobile gaming. "
            "MSFT/GOOGL/META: scale players monetising AI through cloud, search, and advertising. "
            "The thesis: AI productivity premium will be captured first by platforms with captive distribution."
        ),
        "signals": [
            "PLTR commercial revenue growth and AIP adoption",
            "APP e-commerce revenue expansion",
            "MSFT Azure AI revenue attach rate",
            "Meta AI advertising ROI metrics",
        ],
        "search_query": "Palantir PLTR enterprise AI AIP AppLovin APP AI advertising revenue 2026",
        "watch_for": "PLTR US commercial acceleration, APP TAM expansion, MSFT AI revenue disclosure",
        "bear_flag": "Enterprise AI budget fatigue, ad market slowdown, regulatory action",
    },

    "Quantum": {
        "one_liner": "IONQ — early stage, binary outcome, long-duration option on quantum computing.",
        "thesis": "Pre-revenue bet on quantum error correction progress. Small position sizing appropriate. Thesis invalidation: 5-year timeline to fault-tolerant quantum extends to 10+.",
        "signals": ["IONQ algorithmic qubit milestones", "IBM quantum roadmap", "Government quantum funding"],
        "search_query": "quantum computing IONQ error correction milestone 2026",
        "watch_for": "Error correction breakthroughs, enterprise customer announcements",
        "bear_flag": "Timeline extension to fault-tolerant quantum, funding cut",
    },

    "Defence": {
        "one_liner": "LMT — geopolitical tailwind driving defence budget expansion.",
        "thesis": "NATO spending commitments post-Ukraine driving multi-year order books. F-35 backlog and hypersonics pipeline. Steady compounder with political support.",
        "signals": ["NATO defence budgets", "F-35 orders", "US defence budget", "Geopolitical flashpoints"],
        "search_query": "Lockheed Martin LMT defence budget F-35 orders 2026",
        "watch_for": "New F-35 orders, hypersonics contract wins, NATO spending increases",
        "bear_flag": "US defence budget cuts, F-35 programme cancellation",
    },

    "Crypto": {
        "one_liner": "BTC/ETH/SOL — macro liquidity and regulatory clarity driving adoption cycle.",
        "thesis": "Bitcoin as digital gold / macro hedge. ETH as programmable money infrastructure. SOL as high-throughput L1 for consumer crypto apps. MSTR: leveraged BTC proxy.",
        "signals": ["BTC ETF flows", "Fed liquidity conditions", "Crypto regulatory developments", "On-chain activity"],
        "search_query": "Bitcoin ETF crypto regulation adoption BTC price 2026",
        "watch_for": "ETF inflow acceleration, regulatory clarity, institutional adoption",
        "bear_flag": "Regulatory crackdown, macro risk-off, BTC dominance collapse",
    },
}


def get_theme_for_ticker(ticker: str) -> str:
    return THESIS_MAP.get(ticker.upper(), "Other")


def get_tickers_by_theme(holdings: dict) -> dict:
    """Group held tickers by their investment thesis."""
    result = {}
    for t, d in holdings.items():
        if (d.get("shares") or 0) <= 0:
            continue
        theme = THESIS_MAP.get(t, "Other")
        result.setdefault(theme, []).append(t)
    return result


def get_theme_analysis(theme: str, held_tickers: list, prices: dict) -> str:
    """
    Full theme health check: price summary + Tavily news + DeepSeek verdict.
    Returns a formatted Telegram message.
    """
    meta = THEME_THESIS.get(theme)
    if not meta:
        return f"No thesis data for theme: {theme}"

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

    # Fetch Tavily news for this theme
    news_text = ""
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {TAVILY_API_KEY}", "Content-Type": "application/json"},
            json={"query": meta["search_query"], "max_results": 6, "search_depth": "basic"},
            timeout=10,
        )
        if r.status_code == 200:
            for a in r.json().get("results", [])[:5]:
                news_text += f"- {a.get('title', '')}\n"
                if a.get("content"):
                    news_text += f"  {a['content'][:200]}\n"
    except Exception:
        pass

    # Build price summary
    price_lines = []
    for t in held_tickers:
        d = prices.get(t, {})
        if not d or d.get("price") is None:
            continue
        chg = d.get("change_pct") or 0
        icon = "▲" if chg > 0 else "▼"
        price_lines.append(f"{icon} {t}: ${d['price']} ({chg:+.2f}%)")

    prices_text = "\n".join(price_lines) if price_lines else "No price data."

    # DeepSeek synthesis
    prompt = (
        f"You are a portfolio manager reviewing the '{theme}' theme in your book.\n\n"
        f"THESIS: {meta['thesis']}\n\n"
        f"KEY SIGNALS TO WATCH: {', '.join(meta['signals'][:4])}\n\n"
        f"TODAY'S POSITIONS:\n{prices_text}\n\n"
        f"RECENT NEWS:\n{news_text if news_text else 'No news found.'}\n\n"
        f"Give a thesis health check in 3 parts:\n"
        f"1. <b>Thesis status</b> — 🟢 On track / 🟡 Watch / 🔴 Concern + one sentence why\n"
        f"2. <b>What the news means</b> — how does today's news affect this thesis specifically?\n"
        f"3. <b>What to watch</b> — one specific thing in the next 2 weeks that will confirm or challenge the thesis\n\n"
        f"Max 150 words. Be direct. Use <b>bold</b> for tickers and key verdicts."
    )

    analysis = ""
    try:
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 300, "temperature": 0.3},
            timeout=30,
        )
        if r.status_code == 200:
            analysis = r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        analysis = "Analysis unavailable."

    msg = (
        f"📌 <b>{theme}</b>\n"
        f"<i>{meta['one_liner']}</i>\n\n"
        f"<b>Positions today:</b>\n{prices_text}\n\n"
        f"{analysis}"
    )
    return msg
