"""Live examples: `make try-<name>` shows one behaviour of the platform, input to output.

Each example prints its input file, delivers it like a lab would (S3 + claim-check event),
waits for the pipeline, then prints the rows that prove the point. `make try` lists them.
Inputs live in `data/examples/`; run `make demo` afterwards to return to the golden state.
"""

import sys
import time
from collections.abc import Callable

import httpx
import psycopg

from omics import bus, s3, settings
from omics.services.lab_sim import deliver

API = "http://api:8000"
KEYS = {
    "no key": {},
    "research": {"X-API-Key": "research-key-dev"},
    "ops": {"X-API-Key": "ops-key-dev"},
}
DATA = settings.ROOT / "data"
P003_S201 = "84cfcd2e-651b-5bdf-9357-fb454c57f239"  # uuid5("lab_b|S201|HSCRP")
EXAMPLES: dict[str, tuple[str, str, Callable]] = {}


def example(name: str, title: str, why: str):
    """Register an example under the name used by `make try-<name>`."""

    def register(fn):
        EXAMPLES[name] = (title, why, fn)
        return fn

    return register


def rows(sql: str, *params) -> tuple[list[str], list[tuple]]:
    """Run a read-only query and return its column names and rows."""
    with psycopg.connect(settings.DB_DSN) as conn:
        cur = conn.execute(sql, params)
        return [c.name for c in cur.description], cur.fetchall()


def file_state(sha: str) -> tuple | None:
    """Return (status, rows_total, rows_loaded, rows_quarantined, error) of a delivered file."""
    found = rows(
        "SELECT status, rows_total, rows_loaded, rows_quarantined, error FROM ops.ingest_file"
        " WHERE sha256 = %s",
        sha,
    )[1]
    return found[0] if found else None


def send(lab: str, path: str, timeout: float = 120) -> str:
    """Print the input file, deliver it as `lab`, wait until it is processed; return sha256."""
    file = DATA / path
    lines = file.read_text().splitlines()
    print(f"\nINPUT   data/{path}   (sent as {lab})")
    for line in lines[:4]:
        print(f"   {line}")
    if len(lines) > 4:
        print(f"   … {len(lines) - 4} more rows")
    sha = s3.sha256(file.read_bytes())
    before = file_state(sha)
    print("   ", end="")
    deliver(s3.client(), bus.producer(), lab, file)
    if before:
        print(f"   already delivered earlier ({before[0]}): identical bytes are skipped")
        return sha
    start = time.monotonic()
    while (state := file_state(sha)) is None or state[0] not in ("PUBLISHED", "FAILED"):
        if time.monotonic() - start > timeout:
            sys.exit(f"   still {state[0] if state else 'not registered'} after {timeout:.0f} s")
        time.sleep(1)
    status, total, loaded, held, error = state
    took = f"after {time.monotonic() - start:.0f} s"
    if status == "FAILED":
        print(f"   -> FAILED {took}: {error}")
    else:
        print(f"   -> PUBLISHED {took}: rows {total} in, {loaded} loaded, {held} quarantined")
    return sha


def show(caption: str, sql: str, *params, wait: float = 0, vertical: bool = False) -> list:
    """Print a query result as an aligned table (or one field per line); `wait` polls for rows."""
    deadline = time.monotonic() + wait
    while not (result := rows(sql, *params))[1] and time.monotonic() < deadline:
        time.sleep(1)
    names, found = result
    print(f"\nOUTPUT  {caption}")
    if not found:
        print("   (no rows)")
        return found
    if vertical:
        for name, value in zip(names, found[0], strict=True):
            print(f"   {name:<{max(map(len, names))}}  {value}")
        return found
    cells = [names] + [["" if v is None else str(v) for v in row] for row in found]
    widths = [max(len(row[i]) for row in cells) for i in range(len(names))]
    for n, row in enumerate(cells):
        print("   " + " | ".join(v.ljust(w) for v, w in zip(row, widths, strict=True)).rstrip())
        if n == 0:
            print("   " + "-+-".join("-" * w for w in widths))
    return found


def call(path: str, who: str) -> httpx.Response:
    """Call the API as `who` (a key name in KEYS) and print the status and row count."""
    response = httpx.get(f"{API}{path}", headers=KEYS[who])
    body = response.json()
    size = f", {len(body)} rows" if isinstance(body, list) else ""
    print(f"   GET {path}  as {who:<8} -> {response.status_code}{size}")
    return response


def look(text: str) -> None:
    """Print what to point at in the output."""
    print(f"\nLOOK AT {text}")


@example(
    "resend",
    "Send the same file twice",
    "Same bytes -> same sha256 -> same file_id, so the second delivery is skipped.",
)
def resend():
    """Re-deliver a scenario file that was already processed."""
    (before,) = rows("SELECT count(*) FROM sci.measurement")[1][0]
    sha = send("lab-b", "scenario/lab-b/d1/lab_b_20260310T1000.csv")
    time.sleep(3)  # the monitor logs the upload event a moment later
    show(
        "deliveries seen vs times processed",
        "SELECT (SELECT count(*) FROM monitor.event_log WHERE topic = 'lab.uploads'"
        "        AND payload->>'sha256' = %s) AS deliveries_seen,"
        " attempts AS times_processed, status"
        " FROM ops.ingest_file WHERE sha256 = %s",
        sha,
        sha,
    )
    (after,) = rows("SELECT count(*) FROM sci.measurement")[1][0]
    print(f"\n   measurements before: {before}   after: {after}")
    look("it was delivered more than once but processed once; no new measurements.")


@example(
    "correction",
    "Correct a value",
    "A correction is a new row, never an update. 'Current' = the newest report time.",
)
def correction():
    """Send Lab B's new HSCRP value for P003, sample S201."""
    send("lab-b", "examples/lab_b_20261112T1400.csv")
    show(
        "every version of P003's HSCRP on sample S201 (api.measurement_history)",
        "SELECT version, orig_value, orig_unit, value_num, unit,"
        " to_char(source_reported_at, 'YYYY-MM-DD HH24:MI') AS reported, is_current"
        " FROM api.measurement_history WHERE measurement_id = %s ORDER BY version",
        P003_S201,
    )
    look(
        "the 2600 row is current; older versions stay as history. Report time comes from the"
        " file name, so a stale file that arrives late never wins."
    )


@example(
    "bad-unit",
    "Send a weight of 72000 kg",
    "Impossible values are quarantined with a hint, and the person is held from research.",
)
def bad_unit():
    """Send a vital sign that is plausible only in grams."""
    send("clinic", "examples/ehr_vitals_20261112T1405.csv")
    show(
        "the quarantined row",
        "SELECT participant_id, reason, retryable, status, detail FROM api.quarantine"
        " WHERE file_name = 'ehr_vitals_20261112T1405.csv'",
    )
    show("participants on hold", "SELECT participant_id, reasons FROM api.participant_hold")
    print("\nOUTPUT  what a researcher gets for P021's vital signs")
    call("/sdtm/VS?usubjid=RA-02-P021", "research")
    look(
        "SUSPECT_UNIT with the hint 'x0.001 gives 72'; P021 is hidden until fixed"
        " (make try-fix-unit)."
    )


@example(
    "fix-unit",
    "Fix the weight (after try-bad-unit)",
    "A later valid report resolves the issue and lifts the hold in the same transaction.",
)
def fix_unit():
    """Send the corrected weight for P021."""
    send("clinic", "examples/ehr_vitals_20261112T1410.csv")
    show(
        "the 72000 kg row now",
        "SELECT participant_id, reason, status, resolved_at IS NOT NULL AS resolved"
        " FROM api.quarantine WHERE file_name = 'ehr_vitals_20261112T1405.csv'",
    )
    show("participants on hold", "SELECT participant_id, reasons FROM api.participant_hold")
    print("\nOUTPUT  what a researcher gets for P021's vital signs")
    call("/sdtm/VS?usubjid=RA-02-P021", "research")
    look("RESOLVED, only P014 is still on hold, and research sees P021 again.")


@example(
    "late-sample",
    "A lab beats the clinic",
    "A row for an unknown sample waits; it loads by itself once the biobank sends it.",
)
def late_sample():
    """Send a Lab B result for sample S901 before the biobank has registered S901."""
    query = (
        "SELECT participant_id, reason, retryable, status, detail FROM api.quarantine"
        " WHERE file_name = 'lab_b_20261112T1415.csv'"
    )
    send("lab-b", "examples/lab_b_20261112T1415.csv")
    show("the Lab B row", query)
    send("clinic", "examples/biobank_samples_20261112T1420.csv")
    show("the same Lab B row now", query)
    show(
        "the measurement it became",
        "SELECT participant_id, sample_id, value_num, unit, source FROM sci.measurement"
        " WHERE sample_id = 'S901'",
    )
    look("UNRESOLVED_SAMPLE is retryable: no alert, no hold. The biobank file released it.")


@example(
    "bad-header",
    "Break the schema",
    "A file that matches no contract version fails alone; nothing else stops.",
)
def bad_header():
    """Send a Lab B file whose `test_code` column was renamed to `test`."""
    send("lab-b", "examples/lab_b_20261112T1425.csv")
    show(
        "the alert the monitor received",
        "SELECT payload->>'severity' AS severity, payload->>'code' AS code FROM monitor.event_log"
        " WHERE topic = 'alerts' AND payload->>'file_name' = 'lab_b_20261112T1425.csv'",
        wait=20,
    )
    look(
        "FAILED with the reason, a CRITICAL alert, zero rows written. Fix = a new contract"
        " version, then make replay."
    )


@example(
    "wrong-person",
    "A lab names the wrong person",
    "The biobank decides who a sample belongs to; the lab's claim is only cross-checked.",
)
def wrong_person():
    """Send a Lab B row that claims sample S100 belongs to P002 (the biobank says P001)."""
    send("lab-b", "examples/lab_b_20261112T1430.csv")
    show(
        "open sample/participant conflicts",
        "SELECT participant_id, reason, retryable, detail FROM api.quarantine"
        " WHERE reason = 'SAMPLE_PARTICIPANT_CONFLICT' AND status = 'OPEN'",
    )
    look(
        "not retryable (a contradiction won't fix itself), so it raises a CRITICAL alert."
        " The P007 row is the scenario's own planted conflict."
    )


@example(
    "lineage",
    "Where did this number come from?",
    "Every value links back to its raw row, its file and the untouched bytes in S3.",
)
def lineage():
    """Trace P003's current HSCRP value back to the file it arrived in."""
    found = show(
        "the current value of P003's HSCRP on S201, traced back (api.lineage)",
        "SELECT value_num || ' ' || unit AS stored, orig_value || ' ' || orig_unit"
        " AS reported, transform, raw_row::text, row_number AS row_in_file, file_name, s3_uri"
        " FROM api.lineage WHERE measurement_id = %s ORDER BY source_reported_at DESC LIMIT 1",
        P003_S201,
        vertical=True,
    )
    bucket, key = found[0][-1].removeprefix("s3://").split("/", 1)
    body = s3.client().get_object(Bucket=bucket, Key=key)["Body"].read().decode()
    print("\nOUTPUT  the original file, read back from S3 (s3_uri above)")
    for line in body.splitlines()[:4]:
        print(f"   {line}")
    look("stored value -> original value and unit -> raw row -> file -> S3 object.")


@example(
    "access",
    "Who can see what?",
    "No key, research key and ops key get different answers; every call is audited.",
)
def access():
    """Ask for the quarantine list with no key, a research key and an ops key."""
    print("\nOUTPUT  the quarantine list (ops only)")
    for who in KEYS:
        call("/quality/quarantine", who)
    show(
        "the audit log, newest first",
        "SELECT to_char(at, 'HH24:MI:SS') AS at, role, key_id, path, status FROM ops.audit_log"
        " ORDER BY audit_id DESC LIMIT 3",
    )
    look("401 (no key), 403 (research), 200 (ops). key_id is a fingerprint, never the key.")


def main() -> None:
    """List the examples, or run the one named on the command line."""
    sys.stdout.reconfigure(line_buffering=True)
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in EXAMPLES:
        if name:
            print(f"unknown example: {name}\n")
        print("Live examples (run one with make try-<name>):\n")
        for key, (title, why, _) in EXAMPLES.items():
            print(f"  make try-{key:<13} {title}\n  {'':<22} {why}")
        print("\nAfterwards, `make demo` returns to the golden state.")
        return
    title, why, fn = EXAMPLES[name]
    print(f"=== make try-{name}: {title} ===\nWHY     {why}")
    fn()


if __name__ == "__main__":
    main()
