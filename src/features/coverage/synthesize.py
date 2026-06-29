from copy import deepcopy
from datetime import datetime

from src.core.objects import Action, DriverStatus, Recommendation, Thesis, Verdict
from src.features.coverage.types import CoverageResult, LensView


_VERDICT_RANK = {
    Verdict.INTACT: 0,
    Verdict.WEAKENING: 1,
    Verdict.BROKEN: 2,
}


def _pillars_statuses(views: list[LensView], thesis: Thesis) -> dict[str, DriverStatus]:
    for view in views:
        if view.source == "pillars":
            return view.per_driver
    return {driver.id: driver.status for driver in thesis.drivers}


def _new_verdict(thesis: Thesis) -> Verdict:
    if any(
        driver.is_core and driver.status == DriverStatus.INVALIDATED
        for driver in thesis.drivers
    ):
        return Verdict.BROKEN
    if any(driver.status == DriverStatus.STRAINED for driver in thesis.drivers):
        return Verdict.WEAKENING
    return Verdict.INTACT


def _first_failing_driver(thesis: Thesis, verdict: Verdict) -> str:
    if verdict == Verdict.BROKEN:
        for driver in thesis.drivers:
            if driver.is_core and driver.status == DriverStatus.INVALIDATED:
                return driver.summary or driver.id
    if verdict == Verdict.WEAKENING:
        for driver in thesis.drivers:
            if driver.status == DriverStatus.STRAINED:
                return driver.summary or driver.id
    return "no failing driver"


def synthesize(views: list[LensView], thesis: Thesis) -> CoverageResult:
    statuses = _pillars_statuses(views, thesis)
    updated = deepcopy(thesis)

    for driver in updated.drivers:
        if driver.id in statuses:
            driver.status = statuses[driver.id]

    prev = thesis.verdict
    verdict = _new_verdict(updated)
    updated.verdict = verdict
    updated.last_reviewed = datetime.now()

    pushed = verdict == Verdict.BROKEN and prev != Verdict.BROKEN
    degraded = _VERDICT_RANK[verdict] > _VERDICT_RANK[prev]
    recommendation = None
    if degraded:
        failing_driver = _first_failing_driver(updated, verdict)
        recommendation = Recommendation(
            name_ref=thesis.name_ref,
            action=Action.SELL if verdict == Verdict.BROKEN else Action.TRIM,
            size="",
            rationale=f"Thesis {verdict.value}: {failing_driver}",
        )

    return CoverageResult(
        updated_thesis=updated,
        recommendation=recommendation,
        pushed=pushed,
    )
