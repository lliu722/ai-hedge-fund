"""House View on-demand desk entry points.

degrade_to: if the LLM is unavailable, every persona returns hold/Low and debate
is balanced, so the desk still returns a low-conviction HOLD Recommendation
rather than failing.
"""
import json
from collections import Counter

from src.adapters.llm import LLMAdapter
from src.core.objects import Action, Name, Position, Recommendation, Signal, Thesis
from src.features.house_view.lenses import lens_debate, lens_personas, lens_trader
from src.features.house_view.synthesize import synthesize_view


def _modal_action(personas) -> str:
    if not personas:
        return "hold"
    counts = Counter(call.action for call in personas)
    return counts.most_common(1)[0][0]


def run_house_view(
    name: Name,
    thesis: Thesis,
    position: Position,
    quant: Signal | None = None,
    risk_flags: list[Signal] | None = None,
) -> Recommendation:
    risk_flags = risk_flags or []
    personas = lens_personas(name, thesis)
    debate = lens_debate(name, thesis)
    size = lens_trader(_modal_action(personas), position, risk_flags)
    return synthesize_view(personas, debate, size, quant, thesis)


def _pm_conviction(value: str) -> float:
    return {"High": 8.0, "Medium": 5.0, "Low": 3.0}.get(value, 0.0)


def pm_view(context: str, position: Position) -> Recommendation:
    prompt = f"""Context:
{context}

Position:
ticker={position.name_ref}
shares={position.shares}
avg_cost={position.avg_cost}

You are the PM. Reply JSON only: {{"stance": one of BUY/HOLD/REDUCE/PASS, "conviction": High/Medium/Low, "rationale": 2-3 sentences, "key_risk": one thing, "action": specific next step}}."""
    raw = LLMAdapter().fetch(prompt, system="You are a portfolio manager.", max_tokens=400)
    if not raw:
        return Recommendation(
            name_ref=position.name_ref,
            action=Action.HOLD,
            size="",
            rationale="PM view unavailable",
            persona="pm",
            conviction=0.0,
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return Recommendation(
            name_ref=position.name_ref,
            action=Action.HOLD,
            size="",
            rationale="PM view unavailable",
            persona="pm",
            conviction=0.0,
        )

    stance = str(data.get("stance", "HOLD")).upper()
    action = {
        "BUY": Action.BUY,
        "HOLD": Action.HOLD,
        "REDUCE": Action.TRIM,
        "PASS": Action.HOLD,
    }.get(stance, Action.HOLD)

    return Recommendation(
        name_ref=position.name_ref,
        action=action,
        size="",
        rationale=data.get("rationale", ""),
        persona="pm",
        conviction=_pm_conviction(str(data.get("conviction", ""))),
        price_context=data.get("action", ""),
    )
