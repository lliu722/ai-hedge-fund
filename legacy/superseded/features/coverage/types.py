from __future__ import annotations

from dataclasses import dataclass, field

from src.core.objects import DriverStatus, Recommendation, Signal, Thesis


@dataclass
class Evidence:
    name_ref: str
    prices: dict = field(default_factory=dict)
    news: list = field(default_factory=list)
    fundamentals: dict = field(default_factory=dict)
    transcript: str = ""
    filings: list = field(default_factory=list)


@dataclass
class LensView:
    source: str
    per_driver: dict[str, DriverStatus]
    summary: str
    signal: Signal | None = None


@dataclass
class CoverageResult:
    updated_thesis: Thesis
    recommendation: Recommendation | None = None
    pushed: bool = False
