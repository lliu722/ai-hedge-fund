"""IdeaCard — the handoff contract every desk emits and pm_risk consumes.

Canonical definition: docs/DESKS.md §2. This is the shared language of the
asset-class desk model. Desks NEVER set position size / weight / allocation —
those fields belong to pm_risk only (a desk that sizes is a contract violation),
so they are intentionally absent from IdeaCard.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    AVOID = "avoid"
    HEDGE = "hedge"


class Expression(str, Enum):
    SINGLE_STOCK = "single_stock"
    ETF = "etf"
    BASKET = "basket"
    OPTION = "option"
    PAIR = "pair"
    CASH = "cash"


class TimeHorizon(str, Enum):
    DAYS = "days"
    WEEKS = "weeks"
    MONTHS = "months"


class IdeaStatus(str, Enum):
    NEW = "new"
    LIVE = "live"
    REVIEW = "review"
    CLOSED = "closed"
    KILLED = "killed"


class IdeaCard(BaseModel):
    """One idea handed from a desk to pm_risk. Validated before handoff."""
    desk: str                                  # desk_id from the registry, e.g. "equity_ls"
    ticker_or_instrument: str
    direction: Direction
    conviction: float = Field(ge=0.0, le=1.0)  # 0–1
    expression: Expression
    thesis: str
    catalyst: str = ""
    time_horizon: TimeHorizon = TimeHorizon.WEEKS
    upside: str = ""
    downside: str = ""
    falsifier: str = ""                        # what would prove this wrong
    thesis_risk: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    monitor_triggers: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: IdeaStatus = IdeaStatus.NEW

    # Sizing/allocation fields are deliberately NOT here — pm_risk owns them.
