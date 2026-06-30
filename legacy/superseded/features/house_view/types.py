from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PersonaCall:
    persona: str
    action: str
    conviction: str
    note: str = ""


@dataclass
class DebateView:
    bull: str = ""
    bear: str = ""
    lean: str = "balanced"


@dataclass
class SizeView:
    size: str = ""
    capped: bool = False
    reason: str = ""
