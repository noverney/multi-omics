"""Prefect flows: `ingest-file` runs once per upload; `reconcile` is the safety net.

Run with `python -m omics.flows`: serves both deployments from this process.
"""

import os
import random

from prefect import flow, serve, task
from prefect.cache_policies import NONE
from prefect.deployments import run_deployment

from omics import bus, contracts, db, load, s3
from omics.harmonize import FileContext, harmonize, stable_id
from omics.models import Alert, SdtmFinding, UploadEvent
from omics.parse import PARSERS

CONTRACTS = contracts.load_all()
BY_SOURCE = {contract.source: contract for contract in CONTRACTS}
CHAOS_FAIL_RATE = float(os.environ.get("CHAOS_FAIL_RATE", "0"))
CRITICAL = {"SUSPECT_UNIT", "OUT_OF_RANGE", "SAMPLE_PARTICIPANT_CONFLICT", "FILE_REJECTED"}
RETRY = {"retries": 3, "retry_delay_seconds": 2, "cache_policy": NONE}


def chaos(step: str) -> None:
    """Fail on purpose with probability CHAOS_FAIL_RATE, to show retries at work."""
    if random.random() < CHAOS_FAIL_RATE:
        raise RuntimeError(f"chaos: simulated crash in {step}")


@task(**RETRY)
def fetch(event: UploadEvent) -> bytes:
    """Download the file and check it is byte-for-byte what the lab announced."""
    chaos("fetch")
    bucket, key = event.s3_uri.removeprefix("s3://").split("/", 1)
    data = s3.client().get_object(Bucket=bucket, Key=key)["Body"].read()
    if s3.sha256(data) != event.sha256:
        raise ValueError(f"sha256 mismatch for {event.s3_uri}")
    return data


@task(**RETRY)
def load_file(file: FileContext, source: str, rows: list[dict], unmapped: list[str]) -> dict:
    """Harmonize and load one file in ONE transaction: every row lands, or none does."""
    chaos("load")
    contract = BY_SOURCE[source]
    with db.connect() as conn, conn.transaction():
        # The version must be on record before retry_pending re-reads this file's held rows.
        load.set_status(conn, file.file_id, "PROCESSING", contract_version=file.version)
        ref = load.reference(conn)
        loaded, held = load.save(conn, harmonize(rows, contract, ref, load.masters(conn), file))
        resolved = load.retry_pending(conn, BY_SOURCE, ref)
        warnings = f"unmapped columns kept in raw: {unmapped}" if unmapped else None
        load.set_status(
            conn, file.file_id, "LOADED", warnings=warnings,
            rows_total=len(rows), rows_loaded=loaded, rows_quarantined=held,
        )  # fmt: skip
    return {"rows": len(rows), "loaded": loaded, "quarantined": held, "unblocked": resolved}


@task(**RETRY)
def publish() -> dict:
    """Drain the outbox: send current SDTM records and new alerts, then mark them sent."""
    chaos("publish")
    producer = bus.producer()
    with db.connect() as conn, conn.transaction():
        keys, findings = load.unpublished(conn)
        for row in findings:
            record = SdtmFinding.model_validate(row)
            bus.send(producer, "harmonized.sdtm", record.USUBJID, record.model_dump_json())
        issues = load.unalerted(conn)
        for row in issues:
            alert = Alert(
                code=row["reason"],
                severity="CRITICAL" if row["reason"] in CRITICAL else "WARNING",
                message=row["detail"],
                lab=row["lab"],
                file_name=row["file_name"],
                usubjid=row["usubjid"],
                record_id=row["record_id"],
                created_at=row["created_at"],
            )
            bus.send(producer, "alerts", row["usubjid"] or row["lab"], alert.model_dump_json())
        if producer.flush(30):  # anything still queued was not acknowledged by the brokers
            raise RuntimeError("redpanda did not acknowledge every message; nothing marked sent")
        load.mark_published(conn, keys)
        load.mark_alerted(conn, [row["record_id"] for row in issues])
    return {"records": len(findings), "alerts": len(issues)}


def reject(upload: UploadEvent, reason: str) -> dict:
    """Mark a file FAILED and raise a CRITICAL alert; other files are unaffected."""
    with db.connect() as conn:
        load.set_status(conn, stable_id(upload.sha256), "FAILED", error=reason)
    producer = bus.producer()
    alert = Alert(
        code="FILE_REJECTED",
        severity="CRITICAL",
        message=reason,
        lab=upload.lab,
        file_name=upload.file_name,
        created_at=upload.uploaded_at,
    )
    bus.send(producer, "alerts", upload.lab, alert.model_dump_json())
    producer.flush(30)
    return {"status": "FAILED", "reason": reason}


@flow(name="ingest-file")
def ingest_file(event: dict) -> dict:
    """Process one upload end to end; safe to run any number of times for the same file."""
    upload = UploadEvent.model_validate(event)
    contract = contracts.match(CONTRACTS, upload.lab, upload.file_name)
    with db.connect() as conn:
        previous = load.claim_file(conn, upload, contract)
    if previous in ("PUBLISHED", "FAILED"):
        return {"status": f"skipped: file already {previous}"}
    if contract is None:
        return reject(upload, f"no contract for lab {upload.lab!r}, file {upload.file_name!r}")
    header, rows = PARSERS[contract.parser](fetch(upload))
    version = contract.version_for(header)
    if version is None:
        return reject(upload, f"header {header} matches no {contract.source} contract version")
    file = FileContext(
        stable_id(upload.sha256),
        upload.sha256,
        contract.source,
        contract.reported_at(upload.file_name),
        upload.uploaded_at,
        version,
    )
    counts = load_file(file, contract.source, rows, contract.unmapped(version, header))
    counts |= publish()
    with db.connect() as conn:
        load.set_status(conn, file.file_id, "PUBLISHED")
    return counts


@flow(name="reconcile")
def reconcile(stale_seconds: int = 90) -> dict:
    """Re-run files stuck before PUBLISHED and drain the outbox (level-triggered safety net)."""
    with db.connect() as conn:
        stuck = load.stuck_files(conn, stale_seconds)
    for row in stuck:
        event = UploadEvent(**{k: row[k] for k in UploadEvent.model_fields if k in row})
        run_deployment(
            "ingest-file/main",
            parameters={"event": event.model_dump(mode="json")},
            timeout=0,
            as_subflow=False,
            idempotency_key=f"{row['sha256']}:{row['attempts']}",
        )
    return {"rerun": len(stuck)} | publish()


if __name__ == "__main__":
    serve(
        ingest_file.to_deployment(name="main"),
        reconcile.to_deployment(name="main", interval=60),
        limit=int(os.environ.get("FLOW_CONCURRENCY", "2")),
    )
