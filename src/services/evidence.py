from src.adapters.fundamentals import FundamentalsAdapter
from src.features.coverage.types import Evidence


def assemble(name_ref: str) -> Evidence:
    fundamentals = FundamentalsAdapter().fetch(name_ref)
    return Evidence(name_ref=name_ref, fundamentals=fundamentals)
