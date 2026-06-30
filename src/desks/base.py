"""Desk Contract — the shared spine every idea-generating desk extends.

Canonical definition: docs/DESKS.md §2. Implemented here as a plain abstract
base class (not a LangGraph subgraph yet — that's a later wiring decision; a
plain class is lower-risk, fully reversible, and wrappable in LangGraph later).

A concrete desk overrides only its desk-specific steps (research, idea_generation)
and inherits the orchestration in `run()`. The base guarantees every desk returns
validated IdeaCards and never sizes a position (sizing is pm_risk's job).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.desks.contracts import IdeaCard


class Desk(ABC):
    """Base class for all idea-generating desks (everything except pm_risk).

    desk_id must match the registry key. Subclasses implement `research` and
    `idea_generation`; the other spine steps have safe no-op defaults that a
    desk can override as needed.
    """
    desk_id: str = "base"

    # ── §2 spine — override the desk-specific ones, inherit the rest ──────────
    def universe_definition(self) -> list[str]:
        """Instruments/themes this desk may cover. Override per desk."""
        return []

    def data_screening(self, universe: list[str]) -> dict:
        """Pull + screen data for the universe. Override per desk."""
        return {}

    @abstractmethod
    def research(self, screened: dict) -> dict:
        """Desk-specific analysis (see DESKS.md §4). Must override."""
        ...

    @abstractmethod
    def idea_generation(self, research: dict) -> list[IdeaCard]:
        """Produce candidate IdeaCards. Must override. Must NOT set size."""
        ...

    def thesis_risk(self, ideas: list[IdeaCard]) -> list[IdeaCard]:
        """Annotate what could break each idea. Override to enrich."""
        return ideas

    def rank(self, ideas: list[IdeaCard]) -> list[IdeaCard]:
        """Rank emitted ideas best-first (by conviction by default)."""
        return sorted(ideas, key=lambda c: c.conviction, reverse=True)

    # ── orchestration (shared; desks inherit this) ───────────────────────────
    def run(self) -> list[IdeaCard]:
        """Execute the spine and return ranked, validated IdeaCards.

        on_failure: any step raising is caught at the orchestration layer by the
        caller; a desk that cannot produce ideas returns []. Subclasses should
        keep individual steps defensive.
        """
        universe = self.universe_definition()
        screened = self.data_screening(universe)
        research = self.research(screened)
        ideas = self.idea_generation(research)
        ideas = self.thesis_risk(ideas)
        # Contract guard: stamp the desk id so pm_risk can attribute every card.
        for card in ideas:
            card.desk = self.desk_id
        return self.rank(ideas)
