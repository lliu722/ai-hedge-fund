"""Coverage Analyst callable orchestrator.

degrade_to: if the LLM/evidence layer is unavailable, the desk still runs lens C
on the saved thesis and returns a CoverageResult (verdict unchanged,
pushed=False), so the gap is visible rather than silent. No LLM call exists yet,
so this version always runs cleanly.
"""
from src.core.objects import Name, Thesis
from src.features.coverage.lenses import (
    lens_fundamentals,
    lens_pillars,
    lens_valuation,
)
from src.features.coverage.synthesize import synthesize
from src.features.coverage.types import CoverageResult, Evidence


def run_coverage(name: Name, thesis: Thesis, evidence: Evidence) -> CoverageResult:
    views = [
        lens_fundamentals(name, thesis, evidence),
        lens_valuation(name, thesis, evidence),
        lens_pillars(name, thesis, evidence),
    ]
    return synthesize(views, thesis)
