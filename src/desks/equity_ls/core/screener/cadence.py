"""
Step 7 — Review Frequency cadence config by tier.

Consumed by the Market Monitor to decide how often to run the screener
on each name and when to escalate to a full A2 deep dive.
"""
from __future__ import annotations

# Cadence config per tier
_CADENCE: dict[int, dict] = {
    0: {                              # T0 — Holdings
        "price_check":    "daily",
        "score_refresh":  "weekly",
        "thesis_review":  "after_major_event",
        "deep_dive":      "after_major_event",
        "description":    "Daily price/news check; full score refresh weekly; thesis review after major event.",
    },
    1: {                              # T1 — Core Watchlist
        "price_check":    "daily",
        "score_refresh":  "weekly",
        "thesis_review":  "on_demand",
        "deep_dive":      "if_score_above_80",
        "description":    "Daily price/news check; full score refresh weekly.",
    },
    2: {                              # T2 — Sector Leaders
        "price_check":    "weekly",
        "score_refresh":  "weekly",
        "thesis_review":  "event_driven",
        "deep_dive":      "if_score_above_80_or_event",
        "description":    "Weekly score refresh; event-driven checks when news or earnings occur.",
    },
    3: {                              # T3 — Peer / Supply Chain
        "price_check":    "biweekly",
        "score_refresh":  "biweekly",
        "thesis_review":  "on_demand",
        "deep_dive":      "if_score_above_80",
        "description":    "Weekly or biweekly score refresh.",
    },
    4: {                              # T4 — Discovered Names
        "price_check":    "none",
        "score_refresh":  "initial_only",
        "thesis_review":  "if_promoted",
        "deep_dive":      "if_promoted_to_t1_or_t2",
        "description":    "Initial screening only; promote if score/relevance is high enough.",
    },
}

_RESTRICTED = {
    "price_check":   "none",
    "score_refresh": "none",
    "thesis_review": "manual_only",
    "deep_dive":     "never",
    "description":   "No regular screening unless manually reviewed.",
}


def get_cadence(tier: int) -> dict:
    """Return the review cadence config for a given tier (0–4)."""
    return _CADENCE.get(tier, _RESTRICTED)


def should_run_score_refresh(tier: int, days_since_last_run: int) -> bool:
    """Return True if a score refresh is due based on tier cadence."""
    cadence = get_cadence(tier)
    freq = cadence["score_refresh"]
    if freq == "daily":
        return days_since_last_run >= 1
    elif freq == "weekly":
        return days_since_last_run >= 7
    elif freq == "biweekly":
        return days_since_last_run >= 14
    elif freq == "initial_only":
        return days_since_last_run < 0  # never auto-refresh (negative = never true)
    return False


def should_trigger_deep_dive(tier: int, score: float, has_major_event: bool = False) -> bool:
    """Return True if conditions warrant escalating to a full A2 deep dive."""
    cadence = get_cadence(tier)
    trigger = cadence["deep_dive"]

    if trigger == "never":
        return False
    if trigger == "after_major_event":
        return has_major_event
    if trigger == "if_score_above_80":
        return score >= 80
    if trigger == "if_score_above_80_or_event":
        return score >= 80 or has_major_event
    if trigger == "if_promoted_to_t1_or_t2":
        return score >= 75  # promotion threshold for T4 names
    if trigger == "on_demand":
        return score >= 80
    return False
