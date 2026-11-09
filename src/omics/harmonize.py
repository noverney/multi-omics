"""Harmonize source rows into canonical measurements, master rows or quarantine issues.

Pure functions: the same row, contract, reference data and masters snapshot always give the
same result. That determinism is what makes retries, reprocessing and replays exact.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from omics.contracts import Contract
from omics.quality import (
    Concept,
    Issue,
    check_range,
    clean,
    clean_id,
    clean_unit,
    nrind,
    parse_decimal,
    parse_dtc,
    to_canonical,
)

NAMESPACE = uuid.UUID("6f1c5a8e-3b8e-4c1e-9a53-0b6d1f0c2a77")  # never change: ids are forever
CONTENT = (  # the fields that define a measurement's content (lineage excluded)
    "concept_id participant_id sample_id encounter_id observed_at "
    "value_num value_text unit qc_flag run_date".split()
)


def stable_id(*parts: object) -> uuid.UUID:
    """Return a deterministic UUIDv5 built from `parts`: no randomness, no clock."""
    return uuid.uuid5(NAMESPACE, "|".join(map(str, parts)))


def content_hash(row: dict) -> str:
    """Hash the harmonized content, so re-sending the same result is a no-op."""
    canonical = {
        k: format(v.normalize(), "f") if isinstance(v, Decimal) else v
        for k, v in row.items()
        if k in CONTENT
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class Reference:
    """Reference data: concepts (units, ranges), unit conversions, studies and their arms."""

    concepts: dict[str, Concept]
    conversions: dict[tuple[str, str], Decimal]
    studies: frozenset[str]
    arms: frozenset[tuple[str, str]]  # (study_id, armcd), e.g. ("IBD-04", "PBO")


@dataclass(frozen=True)
class Masters:
    """Snapshot of the operational masters that resolve who a row belongs to."""

    participants: dict[str, str]  # participant_id -> study_id
    samples: dict[str, tuple[str, str]]  # sample_id -> (participant_id, collected_at)


@dataclass(frozen=True)
class FileContext:
    """Lineage of the file a row came from; identical on every replay."""

    file_id: uuid.UUID
    sha256: str
    source: str
    reported_at: datetime
    uploaded_at: datetime
    version: int


@dataclass
class Outcome:
    """Result for one source row: a `row` to load, or an `issue` to quarantine."""

    kind: str
    file: FileContext
    record_id: uuid.UUID
    row_number: int
    payload: dict
    row: dict | None = None
    issue: Issue | None = None
    measurement_id: uuid.UUID | None = None
    participant_id: str | None = None


def harmonize(
    payloads: list[dict], contract: Contract, ref: Reference, masters: Masters, file: FileContext
) -> list[Outcome]:
    """Harmonize every row of one file (row numbers start at 1, as in a spreadsheet)."""
    return [
        harmonize_row(payload, number, contract, ref, masters, file)
        for number, payload in enumerate(payloads, start=1)
    ]


def harmonize_row(
    payload: dict,
    row_number: int,
    contract: Contract,
    ref: Reference,
    masters: Masters,
    file: FileContext,
) -> Outcome:
    """Map one raw row through its contract version, then apply the rules for its kind."""
    out = Outcome(contract.kind, file, stable_id(file.sha256, row_number), row_number, payload)
    fields = {name: payload.get(col) for name, col in contract.versions[file.version].items()}
    fields.update(contract.fixed)
    build = {"measurement": measurement, "enrollment": enrollment, "sample": sample}[contract.kind]
    try:
        out.row = build(fields, contract, ref, masters, out)
    except Issue as issue:
        out.issue = issue
    return out


def resolve(
    sample_id: str | None, participant_id: str | None, masters: Masters
) -> tuple[str | None, str | None, Issue | None]:
    """Decide whose row this is: the masters decide, a lab's own claim is only cross-checked.

    Returns (participant_id, collected_at, pending issue). Missing master data is retryable;
    a lab contradicting the biobank is not.
    """
    collected_at = None
    if sample_id:
        owner = masters.samples.get(sample_id)
        if owner is None:
            issue = Issue(
                "UNRESOLVED_SAMPLE", f"{sample_id} not in the biobank yet", retryable=True
            )
            return participant_id, None, issue
        if participant_id and participant_id != owner[0]:
            raise Issue(
                "SAMPLE_PARTICIPANT_CONFLICT",
                f"lab says {sample_id} belongs to {participant_id}, biobank says {owner[0]}",
            )
        participant_id, collected_at = owner
    if participant_id not in masters.participants:
        issue = Issue(
            "UNRESOLVED_PARTICIPANT", f"{participant_id} not enrolled yet", retryable=True
        )
        return participant_id, collected_at, issue
    return participant_id, collected_at, None


def measurement(
    f: dict, contract: Contract, ref: Reference, masters: Masters, out: Outcome
) -> dict:
    """Build a canonical measurement: key it, resolve entities, convert and check the value."""
    code = clean(f.get("code")).upper()
    sample_id = clean_id(f.get("sample_id")) or None
    claimed = clean_id(f.get("participant_id")) or None
    encounter_id = clean_id(f.get("encounter_id")) or None
    observed_at = parse_dtc(f["observed_at"]) if "observed_at" in f else None
    run_date = parse_dtc(f["run_date"])[:10] if "run_date" in f else None
    if not (sample_id or claimed):
        raise Issue("MISSING_ID", "row has neither a participant nor a sample id")
    key = {"sample_id": sample_id, "code": code, "encounter_id": encounter_id}
    key |= {"observed_at": observed_at, "run_date": run_date}
    out.measurement_id = stable_id(contract.source, *(key[k] for k in contract.key))
    out.participant_id = claimed  # the lab's claim, until the masters say otherwise
    participant_id, collected_at, pending = resolve(sample_id, claimed, masters)
    out.participant_id = participant_id
    observed_at = observed_at or collected_at
    concept_id = contract.codes.get(code)
    if concept_id is None:
        raise Issue("UNKNOWN_CODE", f"{code!r} is not in the {contract.source} code map")
    concept = ref.concepts[concept_id]
    raw_value, raw_unit = clean(f.get("value")), clean_unit(f.get("unit"))
    if concept.scale == "categorical":  # a genotype: the call as text, ALT dosage as number
        value, note, value_text = parse_decimal(raw_value), "", clean(f.get("value_text")) or None
    else:
        value, note = to_canonical(parse_decimal(raw_value), raw_unit, concept, ref.conversions)
        value_text = None
    check_range(value, concept)  # hard data errors win over pending resolution
    if pending:
        raise pending
    if run_date and run_date < observed_at[:10]:
        raise Issue("RUN_BEFORE_COLLECTION", f"assay run {run_date} precedes collection")
    mapping = f"{code}->{concept_id}" if code != concept_id else ""
    row = {
        "measurement_id": out.measurement_id,
        "source": contract.source,
        "concept_id": concept_id,
        "participant_id": participant_id,
        "sample_id": sample_id,
        "encounter_id": encounter_id,
        "observed_at": observed_at,
        "value_num": value,
        "value_text": value_text,
        "unit": concept.unit,
        "nrind": nrind(value, concept),
        "qc_flag": clean(f.get("qc_flag")).upper() or "NOT_PROVIDED",
        "run_date": run_date,
        "orig_code": code,
        "orig_value": raw_value,
        "orig_unit": raw_unit or None,
        "transform": "; ".join(n for n in (mapping, note) if n) or None,
    }
    row["record_hash"] = content_hash(row)
    return row


def enrollment(f: dict, contract: Contract, ref: Reference, masters: Masters, out: Outcome) -> dict:
    """Build a participant master row (CTMS); USUBJID = STUDYID-SUBJID."""
    participant_id, study_id = clean_id(f.get("participant_id")), clean(f.get("study_id")).upper()
    out.participant_id = participant_id or None
    if not participant_id:
        raise Issue("MISSING_ID", "enrollment row without a participant id")
    if study_id not in ref.studies:
        raise Issue("UNKNOWN_STUDY", f"{study_id!r} is not a registered study")
    arm, sex = clean(f.get("arm")).upper(), clean(f.get("sex")).upper()[:1] or "U"
    if (study_id, arm) not in ref.arms:
        raise Issue("BAD_VALUE", f"arm {arm!r} is not an arm of {study_id}")
    if sex not in ("F", "M", "U"):
        raise Issue("BAD_VALUE", f"sex {sex!r} not in the allowed values")
    age = parse_decimal(f.get("age"))
    if not 0 <= age <= 120:
        raise Issue("OUT_OF_RANGE", f"age {age} is outside [0, 120]")
    enrolled = clean(f.get("enrolled_on"))
    return {
        "participant_id": participant_id,
        "usubjid": f"{study_id}-{participant_id}",
        "study_id": study_id,
        "arm": arm,
        "sex": sex,
        "age": int(age),
        "enrolled_on": parse_dtc(enrolled)[:10] if enrolled else None,
    }


def sample(f: dict, contract: Contract, ref: Reference, masters: Masters, out: Outcome) -> dict:
    """Build a sample master row (biobank); its participant must already be enrolled."""
    sample_id, participant_id = clean_id(f.get("sample_id")), clean_id(f.get("participant_id"))
    out.participant_id = participant_id or None
    if not (sample_id and participant_id):
        raise Issue("MISSING_ID", "sample row needs both a sample and a participant id")
    row = {
        "sample_id": sample_id,
        "participant_id": participant_id,
        "specimen": clean(f.get("specimen")).upper(),
        "collected_at": parse_dtc(f.get("collected_at")),
        "encounter_id": clean_id(f.get("encounter_id")) or None,
        "visit": clean(f.get("visit")).upper() or None,  # v1 manifests have no visit
    }
    if participant_id not in masters.participants:
        raise Issue("UNRESOLVED_PARTICIPANT", f"{participant_id} not enrolled yet", retryable=True)
    return row
