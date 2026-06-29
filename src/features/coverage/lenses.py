from src.core.objects import DriverStatus, Name, Thesis
from src.features.coverage.types import Evidence, LensView


def lens_pillars(name: Name, thesis: Thesis, evidence: Evidence) -> LensView:
    per_driver = {driver.id: driver.status for driver in thesis.drivers}
    return LensView(
        source="pillars",
        per_driver=per_driver,
        summary="pillar status read from saved thesis",
        signal=None,
    )


def lens_fundamentals(name, thesis, evidence) -> LensView:
    return LensView(
        source="fundamentals",
        per_driver={},
        summary="not yet vendored — pending licence verification",
        signal=None,
    )


def lens_valuation(name, thesis, evidence) -> LensView:
    return LensView(
        source="valuation",
        per_driver={},
        summary="not yet vendored — pending licence verification",
        signal=None,
    )
