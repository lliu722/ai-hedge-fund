import json

from src.adapters.llm import LLMAdapter
from src.core.objects import Name, Thesis
from src.features.house_view.types import DebateView, PersonaCall
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
