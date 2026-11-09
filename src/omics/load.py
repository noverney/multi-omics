"""Database side of the pipeline: snapshots in, one transaction out, outbox drains."""

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from omics.contracts import Contract
from omics.harmonize import FileContext, Masters, Outcome, Reference, harmonize_row, stable_id
from omics.models import UploadEvent
from omics.quality import Concept


def insert_sql(table: str, columns: tuple[str, ...], conflict: str) -> str:
    """Build an INSERT with named placeholders for `columns`."""
    values = ", ".join(f"%({column})s" for column in columns)
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({values}) {conflict}"


def upsert_newest(table: str, key: str, columns: tuple[str, ...]) -> str:
    """Upsert where the newest *report* wins, whatever order the files arrive in."""
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != key)
    newer = f"WHERE {table}.reported_at <= EXCLUDED.reported_at"
    return insert_sql(table, columns, f"ON CONFLICT ({key}) DO UPDATE SET {updates} {newer}")


MEASUREMENT = (
    "measurement_id record_hash source_reported_at received_at source concept_id "
    "participant_id sample_id encounter_id observed_at value_num value_text unit nrind "
    "qc_flag run_date orig_code orig_value orig_unit transform contract_version file_id record_id"
).split()
PARTICIPANT = (
    "participant_id usubjid study_id arm sex age enrolled_on reported_at record_id".split()
)
SAMPLE = "sample_id participant_id specimen collected_at encounter_id reported_at record_id".split()

# Same content delivered twice (a re-send): keep the lineage of the EARLIEST delivery, so
# the stored result does not depend on which copy happened to be processed first.
FIRST_DELIVERY_WINS = (
    "ON CONFLICT (measurement_id, record_hash, source_reported_at) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in MEASUREMENT[3:] if c != "source")
    + " WHERE (EXCLUDED.received_at, EXCLUDED.record_id)"
    " < (sci.measurement.received_at, sci.measurement.record_id)"
)
STORE_SQL = {
    "measurement": insert_sql("sci.measurement", MEASUREMENT, FIRST_DELIVERY_WINS),
    "enrollment": upsert_newest("core.participant", "participant_id", PARTICIPANT),
    "sample": upsert_newest("core.sample", "sample_id", SAMPLE),
}
QUARANTINE_SQL = """
INSERT INTO ops.quarantine (record_id, file_id, measurement_id, participant_id, reason, detail,
                            retryable)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (record_id) DO UPDATE SET
    measurement_id = EXCLUDED.measurement_id, participant_id = EXCLUDED.participant_id,
    reason = EXCLUDED.reason, detail = EXCLUDED.detail, retryable = EXCLUDED.retryable,
    status = 'OPEN', resolved_at = NULL,
    alerted_at = CASE WHEN ops.quarantine.reason = EXCLUDED.reason
                      THEN ops.quarantine.alerted_at END"""
# A valid, newer report of the same measurement supersedes a quarantined bad one.
RESOLVE_CORRECTED_SQL = """
UPDATE ops.quarantine q SET status = 'RESOLVED', resolved_at = now()
FROM ops.ingest_file f
WHERE q.status = 'OPEN' AND q.file_id = f.file_id AND q.measurement_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM sci.measurement m
              WHERE m.measurement_id = q.measurement_id AND m.source_reported_at > f.reported_at)"""
PENDING_SQL = """
SELECT r.row_number, r.payload, f.file_id, f.sha256, f.source, f.reported_at, f.uploaded_at,
       f.contract_version
FROM ops.quarantine q
JOIN raw.record r USING (record_id)
JOIN ops.ingest_file f ON f.file_id = r.file_id
WHERE q.status = 'OPEN' AND q.retryable
ORDER BY f.reported_at, r.row_number
FOR UPDATE OF q SKIP LOCKED"""


def reference(conn: Connection) -> Reference:
    """Load concepts, unit conversions and studies (seeded from reference/*.csv)."""
    concepts = conn.execute(
        "SELECT concept_id, unit, scale, plausible_low, plausible_high, ref_low, ref_high"
        " FROM core.concept"
    )
    conversions = conn.execute("SELECT from_unit, to_unit, factor FROM core.unit_conversion")
    studies = conn.execute("SELECT study_id FROM core.study")
    return Reference(
        concepts={row[0]: Concept(*row) for row in concepts},
        conversions={(src, dst): factor for src, dst, factor in conversions},
        studies=frozenset(row[0] for row in studies),
    )


def masters(conn: Connection) -> Masters:
    """Snapshot the operational masters: enrolled participants and registered samples."""
    participants = conn.execute("SELECT participant_id, study_id FROM core.participant")
    samples = conn.execute("SELECT sample_id, participant_id, collected_at FROM core.sample")
    return Masters(dict(participants.fetchall()), {s: (p, c) for s, p, c in samples})


def register(conn: Connection, event: UploadEvent, contract: Contract | None) -> tuple[str, int]:
    """Record a delivery as RECEIVED (idempotent) and return its (status, attempts).

    From this moment the reconciler knows the file, so a crashed run can never lose it.
    """
    file_id = stable_id(event.sha256)
    reported = contract.reported_at(event.file_name) if contract else event.uploaded_at
    conn.execute(
        "INSERT INTO ops.ingest_file (file_id, sha256, lab, source, file_name, s3_uri,"
        " size_bytes, reported_at, uploaded_at, status)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'RECEIVED')"
        " ON CONFLICT (file_id) DO NOTHING",
        [file_id, event.sha256, event.lab, contract.source if contract else "unknown",
         event.file_name, event.s3_uri, event.size, reported, event.uploaded_at],
    )  # fmt: skip
    return conn.execute(
        "SELECT status, attempts FROM ops.ingest_file WHERE file_id = %s", [file_id]
    ).fetchone()


def claim_file(conn: Connection, event: UploadEvent, contract: Contract | None) -> str:
    """Mark a delivery PROCESSING (registering it if needed); returns the status it had."""
    status, _ = register(conn, event, contract)
    if status not in ("PUBLISHED", "FAILED"):
        conn.execute(
            "UPDATE ops.ingest_file SET status = 'PROCESSING', attempts = attempts + 1,"
            " error = NULL, updated_at = now() WHERE file_id = %s",
            [stable_id(event.sha256)],
        )
    return status


def set_status(conn: Connection, file_id, status: str, **fields) -> None:
    """Advance a file: RECEIVED -> PROCESSING -> LOADED -> PUBLISHED, or FAILED."""
    extra = "".join(f", {name} = %({name})s" for name in fields)
    conn.execute(
        f"UPDATE ops.ingest_file SET status = %(status)s, updated_at = now(){extra}"
        " WHERE file_id = %(file_id)s",
        {"status": status, "file_id": file_id, **fields},
    )


def lineage(outcome: Outcome) -> dict:
    """Lineage columns shared by every loaded row."""
    file = outcome.file
    return {
        "file_id": file.file_id,
        "record_id": outcome.record_id,
        "contract_version": file.version,
        "source_reported_at": file.reported_at,
        "received_at": file.uploaded_at,
        "reported_at": file.reported_at,
    }


def store(conn: Connection, outcomes: list[Outcome]) -> tuple[int, int]:
    """Load harmonized rows and quarantine the rest; returns (loaded, quarantined)."""
    loaded = [o for o in outcomes if o.issue is None]
    held = [o for o in outcomes if o.issue is not None]
    with conn.cursor() as cur:
        for outcome in loaded:
            cur.execute(STORE_SQL[outcome.kind], outcome.row | lineage(outcome))
        cur.executemany(
            QUARANTINE_SQL,
            [
                (o.record_id, o.file.file_id, o.measurement_id, o.participant_id,
                 o.issue.reason, o.issue.detail, o.issue.retryable)
                for o in held
            ],
        )  # fmt: skip
        cur.executemany(
            "UPDATE ops.quarantine SET status = 'RESOLVED', resolved_at = now()"
            " WHERE record_id = %s AND status = 'OPEN'",
            [(o.record_id,) for o in loaded],
        )
        cur.execute(RESOLVE_CORRECTED_SQL)
    return len(loaded), len(held)


def save(conn: Connection, outcomes: list[Outcome]) -> tuple[int, int]:
    """Persist one file: every raw row first (lineage), then loaded rows or issues."""
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO raw.record (record_id, file_id, row_number, payload)"
            " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            [(o.record_id, o.file.file_id, o.row_number, Jsonb(o.payload)) for o in outcomes],
        )
    return store(conn, outcomes)


def retry_pending(conn: Connection, contracts: dict[str, Contract], ref: Reference) -> int:
    """Re-harmonize rows waiting for master data until a pass resolves nothing new.

    Loops because one resolution can unlock another (enrollment -> sample -> measurement).
    """
    resolved = 0
    while True:
        rows = conn.execute(PENDING_SQL).fetchall()
        snapshot = masters(conn)
        outcomes = [
            harmonize_row(
                payload, number, contracts[source], ref, snapshot,
                FileContext(file_id, sha, source, reported, uploaded, version),
            )
            for number, payload, file_id, sha, source, reported, uploaded, version in rows
        ]  # fmt: skip
        loaded, _ = store(conn, outcomes)
        if loaded == 0:
            return resolved
        resolved += loaded


def unpublished(conn: Connection, limit: int = 10_000) -> tuple[list[tuple], list[dict]]:
    """Lock unpublished measurement rows and return them with their current SDTM records."""
    keys = conn.execute(
        "SELECT measurement_id, record_hash, source_reported_at FROM sci.measurement"
        " WHERE published_at IS NULL LIMIT %s FOR UPDATE SKIP LOCKED",
        [limit],
    ).fetchall()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM api.sdtm_findings WHERE measurement_id = ANY(%s)",
            [list({key[0] for key in keys})],
        )
        return keys, cur.fetchall()


def mark_published(conn: Connection, keys: list[tuple]) -> None:
    """Record that these measurement rows reached the topic."""
    conn.cursor().executemany(
        "UPDATE sci.measurement SET published_at = now()"
        " WHERE measurement_id = %s AND record_hash = %s AND source_reported_at = %s",
        keys,
    )


def unalerted(conn: Connection) -> list[dict]:
    """Return open, non-retryable issues that have not been announced on `alerts` yet."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT q.record_id, q.reason, q.detail, q.created_at, f.lab, f.file_name, p.usubjid"
            " FROM ops.quarantine q JOIN ops.ingest_file f USING (file_id)"
            " LEFT JOIN core.participant p USING (participant_id)"
            " WHERE q.status = 'OPEN' AND NOT q.retryable AND q.alerted_at IS NULL"
            " FOR UPDATE OF q SKIP LOCKED"
        )
        return cur.fetchall()


def mark_alerted(conn: Connection, record_ids: list) -> None:
    """Record that these issues reached the alerts topic."""
    conn.execute(
        "UPDATE ops.quarantine SET alerted_at = now() WHERE record_id = ANY(%s)", [record_ids]
    )


def stuck_files(conn: Connection, older_than_seconds: int) -> list[dict]:
    """Take files stuck before PUBLISHED for a retry; bumping `attempts` gives a fresh run key."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "UPDATE ops.ingest_file SET attempts = attempts + 1, updated_at = now()"
            " WHERE status IN ('RECEIVED', 'PROCESSING', 'LOADED')"
            " AND updated_at < now() - make_interval(secs => %s)"
            " RETURNING lab, file_name, s3_uri, sha256, size_bytes AS size, uploaded_at, attempts",
            [older_than_seconds],
        )
        return cur.fetchall()
