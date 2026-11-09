"""Value-level quality rules: sanitize text, parse strictly, convert units, check ranges."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

# Spellings seen in the wild -> the spelling used in core.unit_conversion (after NFKC).
UNIT_ALIASES = {"mcg/L": "ug/L", "mmhg": "mmHg", "beats/min": "bpm", "kgs": "kg"}
# A value outside the hard range that lands inside it after one of these factors is most
# likely a unit (or decimal) mix-up: g vs kg, ug/L vs mg/L, lb vs kg, x10 typos.
SUSPECT_FACTORS = ("0.001", "1000", "0.1", "10", "0.45359237", "2.20462262")
# Accepted date/time layouts and how many ISO 8601 characters each keeps (its precision).
DTC_FORMATS = (
    ("%Y-%m-%dT%H:%M:%S", 19),
    ("%Y-%m-%d %H:%M:%S", 19),
    ("%Y-%m-%dT%H:%M", 16),
    ("%Y-%m-%d %H:%M", 16),
    ("%Y-%m-%d", 10),
)
HOLD_REASONS = ("SUSPECT_UNIT", "OUT_OF_RANGE")  # these put the participant on hold


class Issue(Exception):
    """A row-level problem: the row is quarantined with this reason instead of loaded."""

    def __init__(self, reason: str, detail: str, retryable: bool = False):
        """Store the machine-readable reason, a human detail, and whether a retry may fix it."""
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail, self.retryable = reason, detail, retryable


@dataclass(frozen=True)
class Concept:
    """The parts of `core.concept` the rules need."""

    concept_id: str
    unit: str | None
    scale: str
    plausible_low: Decimal | None
    plausible_high: Decimal | None
    ref_low: Decimal | None
    ref_high: Decimal | None


def clean(text: str | None) -> str:
    """Trim and Unicode-normalize (NFKC) a raw cell; missing becomes ''."""
    return unicodedata.normalize("NFKC", text or "").strip()


def clean_id(text: str | None) -> str:
    """Normalize an identifier: ' p-001' -> 'P001' (uppercase, no separators)."""
    return re.sub(r"[\s_\-]", "", clean(text)).upper()


def clean_unit(text: str | None) -> str:
    """Canonical unit spelling: micro sign -> 'u', then known aliases."""
    unit = clean(text).replace("μ", "u")  # NFKC already folded the micro sign into mu
    return UNIT_ALIASES.get(unit, unit)


def parse_decimal(text: str | None) -> Decimal:
    """Parse a number strictly; censored ('<0.3') or malformed ('3,2') values are issues."""
    value = clean(text)
    if value[:1] in ("<", ">"):
        raise Issue("CENSORED_VALUE", f"{value!r} is outside the assay's detection limit")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise Issue("BAD_VALUE", f"{value!r} is not a number") from None
    if not number.is_finite():
        raise Issue("BAD_VALUE", f"{value!r} is not a finite number")
    return number


def parse_dtc(text: str | None) -> str:
    """Parse a date/time to ISO 8601, keeping the source precision (CDISC --DTC)."""
    value = clean(text)
    for layout, width in DTC_FORMATS:
        try:
            return datetime.strptime(value, layout).isoformat()[:width]
        except ValueError:
            continue
    raise Issue("BAD_DATE", f"{value!r} is not an ISO date or date-time")


def to_canonical(
    value: Decimal, unit: str, concept: Concept, conversions: dict
) -> tuple[Decimal, str]:
    """Convert to the concept's canonical unit; returns the value and a lineage note."""
    if concept.scale == "relative_log2":  # NPX: relative, only its own unit is valid
        if unit != concept.unit:
            raise Issue("UNIT_NOT_ALLOWED", f"{concept.concept_id} must be in {concept.unit}")
        return value, ""
    factor = conversions.get((unit, concept.unit))
    if factor is None:
        raise Issue(
            "UNIT_NOT_ALLOWED", f"{unit!r} cannot express {concept.concept_id} ({concept.unit})"
        )
    note = "" if unit == concept.unit else f"{unit}->{concept.unit} x{factor}"
    return value * factor, note


def check_range(value: Decimal, concept: Concept) -> None:
    """Reject physiologically impossible values; flag likely unit mix-ups with a hint."""
    low, high = concept.plausible_low, concept.plausible_high

    def plausible(number: Decimal) -> bool:
        return (low is None or number >= low) and (high is None or number <= high)

    if plausible(value):
        return
    limits = f"outside the plausible range [{low}, {high}] {concept.unit}"
    for factor in map(Decimal, SUSPECT_FACTORS):
        if value != 0 and plausible(value * factor):
            fixed = format((value * factor).normalize(), "f")
            raise Issue(
                "SUSPECT_UNIT", f"{value} is {limits}; x{factor} gives {fixed}: wrong unit?"
            )
    raise Issue("OUT_OF_RANGE", f"{value} is {limits}")


def nrind(value: Decimal, concept: Concept) -> str | None:
    """CDISC reference range indicator: LOW, NORMAL or HIGH (None if no range is defined)."""
    if concept.ref_low is None and concept.ref_high is None:
        return None
    if concept.ref_low is not None and value < concept.ref_low:
        return "LOW"
    if concept.ref_high is not None and value > concept.ref_high:
        return "HIGH"
    return "NORMAL"
