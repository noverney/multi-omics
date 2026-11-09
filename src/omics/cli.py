"""Operator commands: `python -m omics.cli <init|checksum|settle|replay>`."""

import argparse
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from prefect.deployments import run_deployment
from psycopg.rows import dict_row

from omics import bus, db, s3, settings
from omics.models import UploadEvent

SCENARIO = settings.ROOT / "data" / "scenario"
GOLDEN = SCENARIO / "expected_checksum.txt"
# Everything derived from the raw files, minus wall-clock bookkeeping (received/published
# times change with every fresh delivery). Same input files => same checksum, every time.
CHECKSUM_SQL = """
SELECT md5(coalesce(string_agg(row, '|' ORDER BY row), '')), count(*) FROM (
  SELECT (measurement_id, record_hash, source_reported_at, source, concept_id, participant_id,
          sample_id, encounter_id, observed_at, value_num, value_text, unit, nrind, qc_flag,
          run_date, orig_code, orig_value, orig_unit, transform, contract_version, file_id,
          record_id)::text AS row FROM sci.measurement
  UNION ALL SELECT (participant_id, usubjid, study_id, arm, sex, age, enrolled_on,
                    reported_at)::text FROM core.participant
  UNION ALL SELECT (sample_id, participant_id, specimen, collected_at, encounter_id, visit,
                    reported_at)::text FROM core.sample
  UNION ALL SELECT (record_id, reason)::text FROM ops.quarantine WHERE status = 'OPEN'
) derived"""


def retry(action: Callable, what: str, attempts: int = 30, delay: float = 2.0):
    """Run `action` until it succeeds; dependencies may still be starting up."""
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except Exception as exc:
            if attempt == attempts:
                raise
            print(f"waiting for {what}: {exc}")
            time.sleep(delay)


def scenario_files() -> int:
    """Count the distinct files the scenario delivers (exact re-sends count once)."""
    return len({s3.sha256(p.read_bytes()) for p in SCENARIO.glob("*/d*/*") if p.is_file()})


def checksum() -> str:
    """Return the checksum of all derived data (see CHECKSUM_SQL)."""
    with db.connect() as conn:
        digest, rows = conn.execute(CHECKSUM_SQL).fetchone()
    return f"{digest} ({rows} rows)"


def settle(expected: int, timeout: float = 600) -> None:
    """Wait until `expected` files are registered and none is still in flight."""
    deadline = time.monotonic() + timeout
    while True:
        with db.connect() as conn:
            total, busy = conn.execute(
                "SELECT count(*), count(*) FILTER (WHERE status NOT IN ('PUBLISHED', 'FAILED'))"
                " FROM ops.ingest_file"
            ).fetchone()
        if total >= expected and busy == 0:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(f"{total}/{expected} files registered, {busy} still in flight")
        print(f"  waiting: {total}/{expected} files registered, {busy} in flight")
        time.sleep(5)


def cmd_init(_: argparse.Namespace) -> None:
    """Bootstrap idempotently: roles, schema, reference data, buckets and topics."""
    with db.connect(autocommit=True) as conn:
        db.ensure_roles(conn)
        applied = db.migrate(conn, settings.ROOT / "db")
        db.seed_reference(conn, settings.ROOT / "reference")
    print(f"db: migrations applied {applied or 'none (up to date)'}; reference data seeded")
    created = retry(lambda: s3.ensure_buckets(s3.client()), "s3")
    print(f"s3: buckets ready (created {created or 'none'})")
    admin = bus.admin()
    retry(lambda: bus.wait_for_brokers(admin), "redpanda")
    print(f"redpanda: topics ready (created {bus.ensure_topics(admin) or 'none'})")


def cmd_checksum(args: argparse.Namespace) -> None:
    """Print the checksum; --write stores it as golden, --expect compares against a file."""
    current = checksum()
    print(f"checksum: {current}")
    if args.write:
        args.write.write_text(current.split()[0] + "\n")
        print(f"written to {args.write}")
    if args.expect:
        golden = args.expect.read_text().strip()
        same = current.startswith(golden)
        print(f"{'✅ matches' if same else '❌ differs from'} the golden checksum {golden}")
        sys.exit(0 if same else 1)


def cmd_settle(args: argparse.Namespace) -> None:
    """Block until every scenario file has been processed."""
    settle(args.expected or scenario_files())
    print("settled: every file is PUBLISHED or FAILED")


def cmd_replay(_: argparse.Namespace) -> None:
    """Rebuild everything derived from the immutable raw files and prove it is identical."""
    before = checksum()
    with db.connect(autocommit=True) as conn, conn.cursor(row_factory=dict_row) as cur:
        ledger = cur.execute(
            "SELECT lab, file_name, s3_uri, sha256, size_bytes AS size, uploaded_at"
            " FROM ops.ingest_file ORDER BY uploaded_at"
        ).fetchall()
        cur.execute("TRUNCATE sci.measurement, ops.quarantine, raw.record, core.sample,"
                    " core.participant")  # fmt: skip
        cur.execute(
            "UPDATE ops.ingest_file SET status = 'RECEIVED', attempts = 0, error = NULL,"
            " warnings = NULL, rows_total = NULL, rows_loaded = NULL, rows_quarantined = NULL,"
            " updated_at = now()"
        )
    print(f"replay: derived data truncated; re-running {len(ledger)} files from S3")
    epoch = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    for row in ledger:
        event = UploadEvent(**row).model_dump(mode="json")
        run_deployment(
            "ingest-file/main",
            parameters={"event": event},
            timeout=0,
            idempotency_key=f"{row['sha256']}:replay-{epoch}",
        )
    settle(len(ledger))
    after = checksum()
    print(f"before: {before}\nafter:  {after}")
    print("✅ replay reproduced the same data" if after == before else "❌ replay differs")
    sys.exit(0 if after == before else 1)


def main() -> None:
    """Parse arguments and run the chosen command."""
    parser = argparse.ArgumentParser(prog="omics")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="bootstrap db, buckets and topics").set_defaults(func=cmd_init)
    check = commands.add_parser("checksum", help="checksum of all derived data")
    check.add_argument("--write", type=Path, help="store as the golden checksum")
    check.add_argument("--expect", type=Path, help="fail unless equal to this golden file")
    check.set_defaults(func=cmd_checksum)
    wait = commands.add_parser("settle", help="wait until all scenario files are processed")
    wait.add_argument("--expected", type=int, help="number of files (default: the scenario)")
    wait.set_defaults(func=cmd_settle)
    commands.add_parser("replay", help="rebuild from raw files, compare").set_defaults(
        func=cmd_replay
    )
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
