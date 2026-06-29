"""
Canonical objects — the shared language of the system (BLUEPRINT §3.1).

Every Spine function and every Desk reads and writes THESE shapes, never ad-hoc
dicts. They are what flows between the work (Spine) and the operators (Desks).

This module is the STABLE CORE. It imports nothing volatile — no yfinance, no
DeepSeek, no Notion SDK. The dependency direction is inward: the volatile edge
depends on these objects, never the reverse (AGENTS.md rule 4).

Reference convention: objects point at a Name by its ticker string (`name_ref`),
not by holding a Name instance. The ticker is the stable, serialisable key that
also matches Notion and SQLite rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, is_dataclass
from datetime import date, datetime
from enum import Enum


# ── Enums ─────────────────────────────────────────────────────────────────────

class AssetClass(str, Enum):
    EQUITY = "equity"
    FICC = "ficc"
    COMMODITY = "commodity"
    CRYPTO = "crypto"


class Verdict(str, Enum):
    """Thesis health (Coverage Analyst state machine, BLUEPRINT Desk 2 §5)."""
    INTACT = "intact"
    WEAKENING = "weakening"
    BROKEN = "broken"


class DriverStatus(str, Enum):
    """Per-driver health, evaluated against fresh evidence each run."""
    HOLDING = "holding"
    STRAINED = "strained"
    INVALIDATED = "invalidated"


class Action(str, Enum):
    BUY = "buy"
    ADD = "add"
    HOLD = "hold"
    TRIM = "trim"
    SELL = "sell"


class SignalType(str, Enum):
    THRESHOLD = "threshold"     # price/target crossed
    NEWS = "news"               # ranked headline
    THEME = "theme"             # radar / rotation
    RISK = "risk"               # concentration / regime
    THESIS = "thesis"           # verdict degrade
    DATA = "data"               # degrade / could-not-compute marker


class EventType(str, Enum):
    EARNINGS = "earnings"
    FOMC = "fomc"
    CONFERENCE = "conference"
    THRESHOLD = "threshold"


# ── Core objects (BLUEPRINT §3.1) ─────────────────────────────────────────────

@dataclass
class Name:
    """A tradeable subject. The atom everything else references by ticker."""
    ticker: str
    exchange: str = ""
    asset_class: AssetClass = AssetClass.EQUITY
    sector: str = ""
    theme: list[str] = field(default_factory=list)
    currency: str = "USD"


@dataclass
class Position:
    """A holding in an account. name_ref is a ticker."""
    name_ref: str
    account: str = "default"
    shares: float = 0.0
    avg_cost: float = 0.0
    current_price: float = 0.0
    pnl_abs: float = 0.0
    pnl_pct: float = 0.0
    weight: float = 0.0


@dataclass
class Driver:
    """One pillar a thesis rests on. Coverage Analyst classifies its status."""
    id: str
    summary: str
    is_core: bool = False
    status: DriverStatus = DriverStatus.HOLDING
    evidence: str = ""


@dataclass
class Thesis:
    """The live view on a name. drivers[] are the pillars; verdict is the call."""
    name_ref: str
    summary: str = ""
    drivers: list[Driver] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    verdict: Verdict = Verdict.INTACT
    conviction: float = 0.0          # 0-10
    last_reviewed: datetime | None = None
    source: str = ""


@dataclass
class Signal:
    """A flag raised by a desk. severity 1-10; subject_ref is a ticker or theme."""
    type: SignalType
    subject_ref: str
    severity: int = 1
    summary: str = ""
    created_at: datetime | None = None
    source_desk: str = ""


@dataclass
class Recommendation:
    """An action call with a size and a rationale. Written by House View / Coverage."""
    name_ref: str
    action: Action
    size: str = ""                   # e.g. "5%", "trim half" — free text by design
    rationale: str = ""
    persona: str = ""
    conviction: float = 0.0          # 0-10
    price_context: str = ""
    created_at: datetime | None = None


@dataclass
class Report:
    """Ingested external research, structured by the Research Librarian."""
    source: str
    title: str = ""
    asset_class: AssetClass = AssetClass.EQUITY
    date: date | None = None
    extracted_thesis: str = ""
    extracted_risks: list[str] = field(default_factory=list)
    names_mentioned: list[str] = field(default_factory=list)


@dataclass
class Event:
    """A scheduled or threshold-crossing occurrence. subject_ref is a ticker."""
    type: EventType
    subject_ref: str
    date: date | None = None
    details: str = ""


# ── Serialisation helpers (load-bearing: objects flow to Notion / SQLite) ─────

def to_dict(obj) -> dict:
    """Dataclass → plain dict, with enums flattened to their values and
    datetimes/dates to ISO strings. Safe to hand to json / Notion / SQLite."""
    def _convert(v):
        if isinstance(v, Enum):
            return v.value
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        if is_dataclass(v) and not isinstance(v, type):
            return {k: _convert(val) for k, val in asdict(v).items()}
        if isinstance(v, list):
            return [_convert(i) for i in v]
        if isinstance(v, dict):
            return {k: _convert(val) for k, val in v.items()}
        return v

    if not is_dataclass(obj) or isinstance(obj, type):
        raise TypeError(f"to_dict expects a dataclass instance, got {type(obj)!r}")
    return {k: _convert(v) for k, v in asdict(obj).items()}
