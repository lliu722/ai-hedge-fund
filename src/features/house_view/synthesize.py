from collections import Counter

from src.core.objects import Action, Recommendation, Signal, Thesis
from src.features.house_view.types import DebateView, PersonaCall, SizeView


_ACTION_SCORE = {"sell": -2, "trim": -1, "hold": 0, "add": 1, "buy": 2}


def _map_total_to_action(total: float) -> Action:
    if total >= 1.5:
        return Action.BUY
    if total >= 0.5:
        return Action.ADD
    if total > -0.5:
        return Action.HOLD
    if total > -1.5:
        return Action.TRIM
    return Action.SELL


def _conviction(personas: list[PersonaCall]) -> float:
    if personas and all(
        call.action == "hold" and call.conviction == "Low" for call in personas
    ):
        return 3.0
    scores = [_ACTION_SCORE.get(call.action, 0) for call in personas]
    signs = {1 if score > 0 else (-1 if score < 0 else 0) for score in scores}
    if len(signs) == 1:
        return 8.0
    if 2 in scores and -2 in scores:
        return 3.0
    return 5.0


def _persona_split(personas: list[PersonaCall]) -> str:
    counts = Counter(call.action for call in personas)
    if len(counts) == 1:
        return "unanimous"
    return "personas split: " + " / ".join(
        f"{count} {action}" for action, count in sorted(counts.items())
    )


def synthesize_view(
    personas: list[PersonaCall],
    debate: DebateView,
    size: SizeView,
    quant: Signal | None,
    thesis: Thesis,
) -> Recommendation:
    scores = [_ACTION_SCORE.get(call.action, 0) for call in personas]
    persona_score = sum(scores) / len(scores) if scores else 0.0
    debate_adj = 1 if debate.lean == "bull" else (-1 if debate.lean == "bear" else 0)
    quant_adj = 0
    if quant and quant.summary.startswith("BUY"):
        quant_adj = 1
    elif quant and quant.summary.startswith("AVOID"):
        quant_adj = -1

    total = persona_score + 0.5 * debate_adj + 0.5 * quant_adj
    action = _map_total_to_action(total)
    conviction = _conviction(personas)

    dominant = "bull" if total > 0 else ("bear" if total < 0 else "balanced")
    decisive_line = debate.bull if dominant == "bull" else debate.bear
    if not decisive_line:
        decisive_line = thesis.summary or "no decisive debate line"
    rationale = f"{dominant} lean: {decisive_line}; {_persona_split(personas)}"

    return Recommendation(
        name_ref=thesis.name_ref,
        action=action,
        size=size.size,
        rationale=rationale,
        persona="house_view",
        conviction=conviction,
        price_context=size.reason if size.capped else "",
    )
