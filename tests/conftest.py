"""Shared fixtures: real reference data and contracts, a small masters snapshot."""

import csv
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from omics import contracts
from omics.harmonize import FileContext, Masters, Reference, harmonize_row, stable_id
from omics.quality import Concept
from omics.settings import ROOT


def number(text: str) -> Decimal | None:
    """CSV cell -> Decimal (empty -> None)."""
    return Decimal(text) if text else None


@pytest.fixture(scope="session")
def ref() -> Reference:
    """Load the same reference data the database is seeded with."""
    folder = ROOT / "reference"
    concepts = {
        r["concept_id"]: Concept(
            r["concept_id"], r["unit"] or None, r["scale"], number(r["plausible_low"]),
            number(r["plausible_high"]), number(r["ref_low"]), number(r["ref_high"]),
        )
        for r in csv.DictReader((folder / "concepts.csv").open())
    }  # fmt: skip
    conversions = {
        (r["from_unit"], r["to_unit"]): Decimal(r["factor"])
        for r in csv.DictReader((folder / "units.csv").open())
    }
    studies = frozenset(r["study_id"] for r in csv.DictReader((folder / "studies.csv").open()))
    arms = frozenset(
        (r["study_id"], r["armcd"]) for r in csv.DictReader((folder / "arms.csv").open())
    )
    return Reference(concepts, conversions, studies, arms)


@pytest.fixture(scope="session")
def by_source() -> dict:
    """Every contract, by source name."""
    return {c.source: c for c in contracts.load_all()}


@pytest.fixture
def masters() -> Masters:
    """P001/P002 enrolled; their brief samples registered. P003 is not (late enrollment)."""
    return Masters(
        participants={"P001": "CARDIO-01", "P002": "CARDIO-01"},
        samples={
            "S100": ("P001", "2026-01-10"),
            "S101": ("P002", "2026-01-11"),
            "S200": ("P001", "2026-03-01"),
        },
    )


@pytest.fixture
def run(ref, masters, by_source):
    """Harmonize one payload with the real contract of `source` (file reported 2026-03-10)."""
    stamp = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)

    def _run(payload: dict, source: str, version: int = 1):
        file = FileContext(stable_id(source), "a" * 64, source, stamp, stamp, version)
        return harmonize_row(payload, 1, by_source[source], ref, masters, file)

    return _run
