import json
from numbers import Number

from src.core.objects import DriverStatus, Name, Thesis
from src.adapters.llm import LLMAdapter
from src.features.coverage.types import Evidence, LensView


def lens_pillars(name: Name, thesis: Thesis, evidence: Evidence) -> LensView:
    per_driver = {driver.id: driver.status for driver in thesis.drivers}
    return LensView(
        source="pillars",
        per_driver=per_driver,
        summary="pillar status read from saved thesis",
        signal=None,
    )


# Lens A: fundamentals-analyst prompt pattern adapted from TradingAgents (Apache-2.0). See NOTICE.md.
def lens_fundamentals(name, thesis, evidence) -> LensView:
    drivers = "\n".join(f"{driver.id}: {driver.summary}" for driver in thesis.drivers)
    prompt = f"""Saved thesis drivers:
{drivers}

Latest fundamentals:
{evidence.fundamentals}

You are a fundamentals analyst. Given the saved thesis drivers and the latest fundamentals, classify EACH driver as one of: holding, strained, invalidated — based only on what the fundamentals support. Reply ONLY with a JSON object mapping each driver id to its status, plus a key "summary" with one sentence. Example: {{"d1": "holding", "summary": "margins stable"}}."""

    raw = LLMAdapter().fetch(prompt, system="You output only valid JSON.")
    if not raw:
        return LensView(
            source="fundamentals",
            per_driver={},
            summary="fundamentals lens unavailable (LLM error)",
            signal=None,
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return LensView(
            source="fundamentals",
            per_driver={},
            summary="fundamentals lens: unparseable response",
            signal=None,
        )

    per_driver = {}
    statuses = {
        "holding": DriverStatus.HOLDING,
        "strained": DriverStatus.STRAINED,
        "invalidated": DriverStatus.INVALIDATED,
    }
    for driver in thesis.drivers:
        status = data.get(driver.id)
        if status in statuses:
            per_driver[driver.id] = statuses[status]

    return LensView(
        source="fundamentals",
        per_driver=per_driver,
        summary=data.get("summary", ""),
        signal=None,
    )


def _pe_verdict(forward_pe) -> tuple[str, str]:
    if isinstance(forward_pe, Number):
        if forward_pe < 15:
            verdict = "cheap"
        elif forward_pe > 30:
            verdict = "expensive"
        else:
            verdict = "fair"
        return verdict, f"valuation: {verdict} (P/E fallback, forward P/E {forward_pe})"
    return "fair", "valuation: data partial — no DCF, no P/E"


# Lens B: adapted from src/agents/aswath_damodaran.py (ai-hedge-fund, MIT). See NOTICE.md.
def lens_valuation(name, thesis, evidence) -> LensView:
    fundamentals = evidence.fundamentals
    fcff = fundamentals.get("free_cash_flow")
    shares = fundamentals.get("shares_outstanding")
    market_cap = fundamentals.get("market_cap")
    beta = fundamentals.get("beta")
    growth = fundamentals.get("revenue_growth")
    forward_pe = fundamentals.get("forward_pe")

    if not fcff or not shares or not market_cap:
        verdict, summary = _pe_verdict(forward_pe)
        return LensView(
            source="valuation",
            per_driver={},
            summary=summary,
            signal=None,
        )

    cost_of_equity = 0.045 + (beta * 0.05) if isinstance(beta, Number) else 0.09
    base_growth = min(growth, 0.12) if isinstance(growth, Number) and growth > 0 else 0.04
    terminal_growth = 0.025
    years = 10
    g = base_growth
    g_step = (terminal_growth - base_growth) / (years - 1)

    pv_sum = 0.0
    for year in range(1, years + 1):
        fcff_t = fcff * (1 + g)
        pv = fcff_t / (1 + cost_of_equity) ** year
        pv_sum += pv
        g += g_step

    tv = (
        fcff
        * (1 + terminal_growth)
        / (cost_of_equity - terminal_growth)
        / (1 + cost_of_equity) ** years
    )
    equity_value = pv_sum + tv
    margin_of_safety = (equity_value - market_cap) / market_cap

    if margin_of_safety >= 0.25:
        verdict = "cheap"
    elif margin_of_safety <= -0.25:
        verdict = "expensive"
    else:
        verdict = "fair"

    return LensView(
        source="valuation",
        per_driver={},
        summary=f"valuation: {verdict} (margin of safety {round(margin_of_safety * 100)}%)",
        signal=None,
    )
