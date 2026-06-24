"""
Industry Read-Through Map — when a trigger ticker moves or reports earnings,
identify which portfolio positions are affected and why, then synthesize the
implications via DeepSeek.
"""
import os
import requests
from concurrent.futures import ThreadPoolExecutor


# ── Read-Through Map ──────────────────────────────────────────────────────────
# trigger_ticker → {tickers, relationships, context}
# relationship tuple: (type, one-line description of the link)

READ_THROUGH_MAP = {
    "NVDA": {
        "tickers": ["ALAB", "CRDO", "TSM", "ASML", "ARM", "AVGO", "MU", "MU"],
        "tickers": ["ALAB", "CRDO", "TSM", "ASML", "ARM", "AVGO", "MU"],
        "relationships": {
            "ALAB": ("customer",  "NVDA GPU racks use Astera Labs PCIe retimers for server interconnects — NVDA shipments = ALAB pull-through revenue"),
            "CRDO": ("customer",  "AI clusters require Credo's active electrical cables — NVDA rack deployments = CRDO AEC demand"),
            "TSM":  ("supplier",  "Blackwell GPUs fabbed exclusively at TSMC N4/N3 — NVDA demand beats = more TSM wafer revenue"),
            "ASML": ("indirect",  "TSMC CoWoS expansion to serve NVDA needs ASML EUV tools — NVDA upside flows to ASML 12-18 months later"),
            "ARM":  ("licensor",  "NVDA CPU cores (Grace) and networking ASICs use Arm IP — NVDA growth = ARM royalty upside"),
            "AVGO": ("partner",   "NVDA NVLink switches and Broadcom custom silicon co-exist in hyperscaler racks — AI capex lifts both"),
            "MU":   ("supplier",  "Every H200/B200 GPU ships with HBM3e — NVDA demand directly fills MU (and SK Hynix) HBM allocation"),
        },
        "context": "NVDA is the bellwether of the AI infrastructure supercycle. A beat on data centre revenue is a green light for the entire compute stack. A guidance miss is a risk-off signal for all AI semis.",
    },

    "AMD": {
        "tickers": ["ALAB", "CRDO", "TSM"],
        "relationships": {
            "ALAB": ("customer", "AMD MI300X/MI325X GPU clusters use the same PCIe retimers as NVDA racks — AMD AI revenue = ALAB demand"),
            "CRDO": ("customer", "AMD-based AI clusters need high-speed interconnects — same CRDO AEC pull-through as NVDA"),
            "TSM":  ("supplier", "AMD GPUs fabbed at TSMC N5 — AMD MI300X ramp = more TSMC CoWoS utilisation"),
        },
        "context": "AMD is the #2 GPU for AI training. Strong AMD AI revenue validates hyperscaler multi-vendor strategy and benefits the same AI infra stack as NVDA, just at lower volumes.",
    },

    "TSM": {
        "tickers": ["NVDA", "AMD", "ASML", "ALAB", "ARM"],
        "relationships": {
            "NVDA":  ("customer",  "TSMC is NVDA's sole foundry — TSM CoWoS capacity and yield commentary = NVDA supply visibility"),
            "AMD":   ("customer",  "AMD fabbed at TSMC — TSM guidance sets AMD production ceiling"),
            "ASML":  ("equipment", "TSM capex guidance directly translates to ASML EUV tool orders placed 12-18 months ahead"),
            "ALAB":  ("indirect",  "CoWoS packaging bottleneck is the key constraint for all AI chip companies — TSM CoWoS commentary affects ALAB's customer shipment timelines"),
            "ARM":   ("indirect",  "All major TSMC customers (Apple, NVDA, AMD, Qualcomm) use Arm IP — TSMC revenue breadth = ARM royalty breadth"),
        },
        "context": "TSMC quarterly calls are the single best read-through for the AI semiconductor supply chain. Their CoWoS packaging commentary and advanced node utilisation rate tells you what's happening inside NVDA's supply chain before NVDA reports.",
    },

    "ASML": {
        "tickers": ["TSM", "INTC"],
        "relationships": {
            "TSM":  ("customer", "TSMC is ASML's largest EUV customer — ASML order intake = TSM committed expansion capex"),
            "INTC": ("customer", "Intel is a major ASML customer for its IDM 2.0 programme — ASML order trends signal Intel fab confidence"),
        },
        "context": "ASML orders are the most leading indicator of semiconductor capex — 12-18 months ahead of production ramp. ASML guidance is the canary for the entire foundry capex cycle.",
    },

    "MU": {
        "tickers": ["WDC", "SNDK"],
        "relationships": {
            "WDC":  ("cycle-peer", "Same DRAM/NAND pricing cycle — MU pricing and inventory commentary is a near-perfect 1-quarter lead for WDC"),
            "SNDK": ("cycle-peer", "SNDK (SanDisk, WDC spin-off) operates in the same NAND pricing environment — MU NAND ASP trend = SNDK outlook"),
        },
        "context": "Memory is a commodity cycle. MU reports first and sets the tone for the quarter. Their HBM demand commentary is especially critical — it tells you whether AI-driven memory demand is absorbing the oversupply.",
    },

    "WDC": {
        "tickers": ["MU", "SNDK"],
        "relationships": {
            "MU":   ("cycle-peer", "DRAM/NAND pricing peer — WDC NAND ASP and inventory days confirm or deny MU's outlook"),
            "SNDK": ("direct",     "SNDK was WDC's NAND business before the spin-off — same factories, same customers, same cycle. WDC results ARE the SNDK read-through."),
        },
        "context": "WDC results are the most direct read-through for SNDK (same underlying NAND factories). WDC's HDD commentary also matters for data centre storage demand.",
    },

    "GEV": {
        "tickers": ["BE", "CEG", "VST", "TLN"],
        "relationships": {
            "BE":  ("theme-peer",   "Both serve the AI data centre power demand thesis — GEV order backlog validates the multi-year power infrastructure cycle that BE also rides"),
            "CEG": ("power-peer",   "Grid equipment (GEV) and nuclear generation (CEG) serve the same hyperscaler 24/7 power demand — GEV backlog = CEG PPA opportunity"),
            "VST": ("power-peer",   "GEV turbine orders signal sustained power demand growth that benefits VST gas generation assets"),
            "TLN": ("power-peer",   "Same PJM power market dynamic — GEV commentary on data centre power contracts reads through to TLN capacity pricing"),
        },
        "context": "GEV is the picks-and-shovels play on the AI power thesis. Their order backlog and margins are the best real-time indicator of how the grid infrastructure buildout is progressing.",
    },

    "CEG": {
        "tickers": ["VST", "TLN", "BE"],
        "relationships": {
            "VST": ("pricing-peer", "Same PJM capacity auction market — CEG capacity clearing prices directly set the pricing environment for VST"),
            "TLN": ("pricing-peer", "Same power market. CEG PPA pricing negotiations set the benchmark for TLN's own capacity deal discussions"),
            "BE":  ("theme",        "Nuclear (CEG) and fuel cells (BE) both compete for the '24/7 carbon-free' hyperscaler power contracts"),
        },
        "context": "CEG's power purchase agreement (PPA) pricing with hyperscalers is the key read-through. Each new nuclear deal sets the market rate for all power generators serving data centres.",
    },

    "PLTR": {
        "tickers": ["APP", "MSFT"],
        "relationships": {
            "APP":  ("theme-peer", "Both AI software monetisation plays — PLTR enterprise AI adoption rate signals enterprise willingness to pay for AI platforms, which benefits APP's AI-driven ad targeting narrative"),
            "MSFT": ("ecosystem",  "PLTR's AIP runs on Azure — strong PLTR commercial momentum = Azure AI workload growth"),
        },
        "context": "PLTR is the leading indicator for enterprise AI platform adoption. Their US commercial revenue growth rate is the cleanest signal of whether enterprises are deploying AI in production.",
    },

    "ASTS": {
        "tickers": ["RKLB"],
        "relationships": {
            "RKLB": ("customer", "ASTS uses Rocket Lab's Electron to launch BlueBird satellites — ASTS deployment milestones = RKLB launch manifest fills"),
        },
        "context": "The ASTS-RKLB relationship is direct: more ASTS satellite deployments = more RKLB launches booked. ASTS commercial service milestones are the key read-through.",
    },

    "GLW": {
        "tickers": ["LITE", "CRDO"],
        "relationships": {
            "LITE": ("theme-peer", "Same 800G optical cycle — GLW supplies the fibre, LITE supplies the transceivers at either end. GLW fibre pricing inflection = LITE transceiver demand follows"),
            "CRDO": ("indirect",   "AI cluster bandwidth demand drives fibre (GLW) and active electrical cable (CRDO) simultaneously — GLW backlog validates the AI networking capex theme"),
        },
        "context": "GLW fibre commentary is the most upstream indicator of the AI networking buildout. Shortage pricing at the fibre layer confirms hyperscaler bandwidth demand is real, not a planning number.",
    },

    "JPM": {
        "tickers": ["GS", "MS"],
        "relationships": {
            "GS": ("direct-peer", "Same IB/capital markets cycle. JPM M&A fee commentary = GS pipeline visibility. JPM trading revenue = GS trading environment."),
            "MS": ("direct-peer", "JPM and MS both leveraged to M&A revival and rate normalisation. JPM is the tone-setter for bank earnings season."),
        },
        "context": "JPM reports first every earnings season. Their M&A pipeline commentary, trading revenue trajectory, and NIM guidance sets the expectation for all money centre banks. GS and MS move on JPM day.",
    },

    # Hyperscalers — not held but trigger major read-through for held positions
    "MSFT": {
        "tickers": ["NVDA", "ALAB", "CRDO", "PLTR"],
        "relationships": {
            "NVDA": ("customer",  "Azure is one of NVDA's top 3 GPU customers — MSFT AI capex guidance is a direct NVDA demand signal"),
            "ALAB": ("indirect",  "Azure AI cluster build at scale requires PCIe retimer components — MSFT capex = ALAB design wins"),
            "CRDO": ("indirect",  "Microsoft AI cluster interconnect uses Credo AEC solutions — Azure AI expansion = CRDO revenue"),
            "PLTR": ("customer",  "PLTR AIP runs on Azure. Azure growth accelerates PLTR enterprise sales motion. MSFT endorsement = PLTR credibility."),
        },
        "context": "MSFT Azure AI capex guidance is one of the highest-impact data points for the AI infrastructure trade. They publish explicit GPU acquisition numbers — their commentary moves NVDA, ALAB, and the whole stack.",
    },

    "META": {
        "tickers": ["NVDA", "ALAB", "CRDO"],
        "relationships": {
            "NVDA": ("customer",  "Meta is one of NVDA's top 3 GPU buyers — META capex commentary is a direct NVDA demand signal. They buy in 100k+ GPU tranches."),
            "ALAB": ("indirect",  "Meta AI cluster build uses Astera Labs PCIe retimers across their GPU infrastructure"),
            "CRDO": ("indirect",  "Meta AI infra at their scale uses Credo AEC for high-density server rack interconnects"),
        },
        "context": "Meta publishes AI capex plans explicitly — their GPU acquisition numbers are more transparent than most hyperscalers. A META capex raise is immediately bullish for NVDA allocation.",
    },

    "GOOGL": {
        "tickers": ["NVDA", "TSM", "ALAB"],
        "relationships": {
            "NVDA": ("customer/competitor", "Google buys NVDA GPUs AND builds TPUs — either way, GOOGL AI capex = more TSMC CoWoS demand"),
            "TSM":  ("customer",            "Google TPU v5/v6 fabbed at TSMC N3/N2 — GOOGL custom silicon capex drives TSMC utilisation"),
            "ALAB": ("indirect",            "Google's AI cluster scale means Astera Labs components across their TPU and GPU server mix"),
        },
        "context": "Google is unique — both a buyer of NVDA GPUs and a builder of custom TPUs. Either path benefits TSMC. Their cloud AI revenue growth is the demand validation for the entire AI infrastructure trade.",
    },
}


def get_read_through_analysis(trigger_ticker: str, held_tickers: list,
                               news_context: str = "") -> str:
    """
    For a given trigger ticker (e.g. NVDA after earnings), identify which held
    portfolio positions are affected, fetch recent news about the trigger, and
    synthesize the read-through implications via DeepSeek.

    Args:
        trigger_ticker: The company that moved / reported (e.g. "NVDA")
        held_tickers: List of tickers currently held in portfolio
        news_context: Optional pre-fetched news summary string

    Returns:
        Formatted Telegram message with read-through analysis.
    """
    trigger = trigger_ticker.upper()
    mapping = READ_THROUGH_MAP.get(trigger)
    if not mapping:
        available = ", ".join(sorted(READ_THROUGH_MAP.keys()))
        return (
            f"No read-through map for <b>{trigger}</b>.\n"
            f"<i>Mapped triggers: {available}</i>"
        )

    held_set = set(t.upper() for t in held_tickers)
    affected = [t for t in mapping["tickers"] if t in held_set]

    if not affected:
        return (
            f"📡 <b>Read-Through: {trigger}</b>\n\n"
            f"No currently held positions with a read-through relationship to {trigger}.\n"
            f"<i>Related tickers in the map: {', '.join(mapping['tickers'])}</i>"
        )

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

    # Fetch latest news about the trigger if not provided
    if not news_context:
        try:
            r = requests.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {TAVILY_API_KEY}", "Content-Type": "application/json"},
                json={
                    "query": f"{trigger} earnings results guidance latest news today",
                    "max_results": 6,
                    "search_depth": "basic",
                },
                timeout=10,
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                news_context = ""
                for a in results[:5]:
                    news_context += f"- {a.get('title', '')}\n"
                    if a.get("content"):
                        news_context += f"  {a['content'][:200]}\n"
        except Exception:
            news_context = "No news available."

    # Build relationship context for DeepSeek
    rel_lines = []
    for ticker in affected:
        rel_type, rel_desc = mapping["relationships"].get(ticker, ("related", ""))
        rel_lines.append(f"• <b>{ticker}</b> [{rel_type}]: {rel_desc}")

    rel_text = "\n".join(rel_lines)

    prompt = (
        f"You are a portfolio manager assessing the read-through impact of {trigger} news on related holdings.\n\n"
        f"CONTEXT: {mapping['context']}\n\n"
        f"LATEST {trigger} NEWS:\n{news_context or 'No specific news — assess based on general relationship.'}\n\n"
        f"AFFECTED HOLDINGS AND THEIR RELATIONSHIP TO {trigger}:\n"
        + "\n".join(
            f"- {t} ({mapping['relationships'].get(t, ('related', ''))[0]}): {mapping['relationships'].get(t, ('', ''))[1]}"
            for t in affected
        )
        + f"\n\nFor each affected holding, give:\n"
        f"1. Impact direction: 🟢 Positive / 🔴 Negative / 🟡 Neutral/Mixed\n"
        f"2. ONE sentence explaining exactly why and how strong the read-through is\n"
        f"3. Whether this changes the investment thesis or is just a near-term move\n\n"
        f"Then give a 1-sentence overall portfolio read-through verdict.\n"
        f"Max 200 words. Use <b>bold</b> for tickers. Be direct and specific — no generic statements."
    )

    analysis = ""
    try:
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 400,
                "temperature": 0.3,
            },
            timeout=30,
        )
        if r.status_code == 200:
            analysis = r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        analysis = "Analysis unavailable — check DeepSeek API."

    msg = (
        f"📡 <b>Read-Through: {trigger}</b>\n"
        f"<i>{mapping['context'][:120]}…</i>\n\n"
        f"<b>Affected holdings:</b>\n{rel_text}\n\n"
        f"{analysis}"
    )
    return msg


def get_morning_read_through(held_prices: dict, held_tickers: list) -> str:
    """
    For the morning briefing: if any trigger ticker moved >5% overnight,
    return a compact read-through blurb for inclusion in the briefing prompt.
    Used by scheduler.py.
    """
    triggered = []
    for ticker, data in held_prices.items():
        if ticker in READ_THROUGH_MAP and data and abs(data.get("change_pct") or 0) >= 5.0:
            triggered.append((ticker, data["change_pct"]))

    if not triggered:
        return ""

    lines = []
    for ticker, chg in triggered:
        mapping = READ_THROUGH_MAP[ticker]
        held_set = set(t.upper() for t in held_tickers)
        affected = [t for t in mapping["tickers"] if t in held_set]
        if affected:
            direction = "up" if chg > 0 else "down"
            lines.append(
                f"• {ticker} is {direction} {abs(chg):.1f}% — read-through for {', '.join(affected)}: {mapping['context'][:120]}"
            )

    return "\n".join(lines)
