import json

from src.adapters.llm import LLMAdapter
from src.core.objects import Name, Position, Signal, Thesis
from src.features.house_view.types import DebateView, PersonaCall, SizeView
from src.tools.recommendations import CATHIE_WOOD, DAMODARAN, DRUCKENMILLER, LI_WEI


# Lens A personas: ai-hedge-fund persona panel (MIT). Lens B debate + C trader: TradingAgents (Apache-2.0). See NOTICE.md.
def lens_personas(name: Name, thesis: Thesis) -> list[PersonaCall]:
    personas = [
        ("Cathie Wood", CATHIE_WOOD),
        ("Druckenmiller", DRUCKENMILLER),
        ("Damodaran", DAMODARAN),
        ("Li Wei", LI_WEI),
    ]
    drivers = "\n".join(f"{driver.id}: {driver.summary}" for driver in thesis.drivers)
    calls: list[PersonaCall] = []

    for label, system in personas:
        user_prompt = f"""Ticker: {name.ticker}
Thesis summary: {thesis.summary}
Drivers:
{drivers}

Give your call on this name as JSON only: {{"action": one of buy/add/hold/trim/sell, "conviction": High/Medium/Low, "note": one sentence}}."""
        raw = LLMAdapter().fetch(user_prompt, system=system, max_tokens=200)
        if not raw:
            calls.append(
                PersonaCall(
                    persona=label,
                    action="hold",
                    conviction="Low",
                    note="persona unavailable",
                )
            )
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            calls.append(
                PersonaCall(
                    persona=label,
                    action="hold",
                    conviction="Low",
                    note="persona unavailable",
                )
            )
            continue

        calls.append(
            PersonaCall(
                persona=label,
                action=str(data.get("action", "hold")).lower(),
                conviction=str(data.get("conviction", "Medium")),
                note=data.get("note", ""),
            )
        )

    return calls


def lens_debate(name: Name, thesis: Thesis) -> DebateView:
    prompt = f"""Ticker: {name.ticker}
Thesis summary: {thesis.summary}

Argue both sides. Reply JSON only: {{"bull": one sentence, "bear": one sentence, "lean": one of bull/bear/balanced}}."""
    raw = LLMAdapter().fetch(
        prompt,
        system="You are a balanced analyst arguing both sides.",
        max_tokens=250,
    )
    if not raw:
        return DebateView(bull="", bear="", lean="balanced")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return DebateView(bull="", bear="", lean="balanced")

    return DebateView(
        bull=data.get("bull", ""),
        bear=data.get("bear", ""),
        lean=str(data.get("lean", "balanced")).lower(),
    )


def lens_trader(stance_action: str, position: Position, risk_flags: list[Signal]) -> SizeView:
    sizes = {
        "buy": "5%",
        "add": "+2%",
        "hold": "hold",
        "trim": "-half",
        "sell": "exit",
    }
    action = stance_action.lower()
    size = sizes.get(action, "hold")

    for flag in risk_flags:
        if flag.summary.startswith("CAP:") and position.name_ref in flag.subject_ref:
            if action in {"buy", "add"}:
                return SizeView(
                    size="no add — risk cap",
                    capped=True,
                    reason=flag.summary,
                )
            return SizeView(size=size, capped=True, reason=flag.summary)

    return SizeView(size=size, capped=False, reason="")
