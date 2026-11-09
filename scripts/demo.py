"""Narrated demo: proves each topic of the brief on the live stack (`make demo`).

Each check returns (passed, evidence). The same checks run as integration tests.
"""

import sys
import time
from decimal import Decimal

import httpx
import psycopg
from confluent_kafka import Consumer, TopicPartition

from omics import settings
from omics.cli import GOLDEN, SCENARIO, checksum, scenario_files, settle

API = "http://api:8000"
RESEARCH, OPS = {"X-API-Key": "research-key-dev"}, {"X-API-Key": "ops-key-dev"}
P001_LAB_B = "304a94fc-27af-5a29-9bde-fecfed02ae04"  # uuid5(lab_b, S200, HSCRP)
CHECKS = []


def check(topic: str):
    """Register a demo check under the brief topic it proves."""

    def register(fn):
        CHECKS.append((topic, fn))
        return fn

    return register


def one(sql: str, *params):
    """Run a query and return its first row."""
    with psycopg.connect(settings.DB_DSN) as conn:
        return conn.execute(sql, params).fetchone()


@check("Idempotency")
def idempotency():
    """Prove that an exact re-delivery and a re-ordered re-send change nothing."""
    (files,) = one("SELECT count(*) FROM ops.ingest_file WHERE file_name = %s",
                   "lab_a_20260310T0900.csv")  # fmt: skip
    (added,) = one(
        "SELECT count(*) FROM sci.measurement m JOIN ops.ingest_file f USING (file_id)"
        " WHERE f.file_name = 'lab_a_20260310T0900_resend.csv'"
    )
    return files == 1 and added == 0, (
        f"2 deliveries of lab_a_20260310T0900.csv -> {files} file; "
        f"the re-ordered re-send added {added} measurements"
    )


@check("Entity resolution")
def entity_resolution():
    """Prove P001 is one person across 4 feeds; contradicting lab claims are caught."""
    (sources,) = one(
        "SELECT count(DISTINCT source) FROM sci.measurement WHERE participant_id = 'P001'"
    )
    (conflicts,) = one(
        "SELECT count(*) FROM ops.quarantine WHERE reason = 'SAMPLE_PARTICIPANT_CONFLICT'"
    )
    return sources == 4 and conflicts == 1, (
        f"P001 has data from {sources} sources; {conflicts} lab claim contradicting "
        "the biobank was quarantined"
    )


@check("Normalization")
def normalization():
    """Prove Lab B's 3200 ug/L becomes 3.2 mg/L with the original kept for lineage."""
    row = one(
        "SELECT orig_value, orig_unit, value_num, unit, transform FROM sci.measurement"
        " WHERE measurement_id = %s",
        P001_LAB_B,
    )
    return row[2] == Decimal("3.2") and row[
        3
    ] == "mg/L", f"{row[0]} {row[1]} -> {row[2]} {row[3]} ({row[4]})"


@check("Validation")
def validation():
    """Prove impossible values are quarantined with a hint and their owner held."""
    (hints,) = one("SELECT count(*) FROM ops.quarantine WHERE reason = 'SUSPECT_UNIT'")
    (held,) = one("SELECT string_agg(participant_id, ',') FROM api.participant_hold")
    return hints >= 2 and held == "P014", (
        f"{hints} SUSPECT_UNIT rows with a conversion hint; on hold now: {held}"
    )


@check("Corrections")
def corrections():
    """Prove current = newest report, even though a stale re-export arrived later."""
    (versions, current) = one(
        "SELECT count(*), max(orig_value) FILTER (WHERE is_current) FROM api.measurement_history"
        " WHERE participant_id = 'P003' AND sample_id = 'S201'"
    )
    return versions == 3 and current == "2400", (
        f"P003/S201 has {versions} versions (1900 stale, 2100, 2400); current = {current}"
    )


@check("Late-arriving data")
def late_data():
    """Prove rows that beat their master data waited, then loaded by themselves."""
    (waited,) = one("SELECT count(*) FROM ops.quarantine WHERE retryable AND status = 'RESOLVED'")
    (s159,) = one("SELECT count(*) FROM sci.measurement WHERE sample_id = 'S159'")
    return waited >= 5 and s159 == 5, (
        f"{waited} rows waited for enrollment/biobank and were released; S159 has {s159}"
    )


@check("Schema evolution")
def schema_evolution():
    """Prove Lab B's v2 header (renamed + new column) loads through contract v2."""
    # Counts stored rows, not the file's load-time counters: when masters arrive late the
    # rows are held first and released later, so those counters depend on arrival order.
    row = one(
        "SELECT f.contract_version, count(m.*), f.warnings FROM ops.ingest_file f"
        " LEFT JOIN sci.measurement m USING (file_id)"
        " WHERE f.file_name = 'lab_b_20260324T1000.csv' GROUP BY f.contract_version, f.warnings"
    )
    return row[0] == 2 and row[
        1
    ] == 5, f"contract v{row[0]}, {row[1]} measurements stored; {row[2]}"


@check("Fault tolerance")
def fault_tolerance():
    """Prove a broken file fails alone while every other file is published."""
    (failed, published, total) = one(
        "SELECT string_agg(file_name, ',') FILTER (WHERE status = 'FAILED'),"
        " count(*) FILTER (WHERE status = 'PUBLISHED'), count(*) FROM ops.ingest_file"
    )
    return failed == "lab_a_20260324T0900.csv" and published == total - 1, (
        f"FAILED: {failed} (unknown header); PUBLISHED: {published}/{total}"
    )


@check("Lineage")
def lineage():
    """Prove one call leads from a published value to its raw row and S3 file."""
    (version,) = httpx.get(f"{API}/measurements/{P001_LAB_B}/lineage", headers=OPS).json()
    raw = version["raw_row"]
    return raw["result"] == "3200", f"raw row {raw} in {version['s3_uri'][:40]}..."


@check("Access control")
def access_control():
    """Prove no key gets 401, research gets no raw rows (403) and no held people."""
    anonymous = httpx.get(f"{API}/sdtm/LB").status_code
    forbidden = httpx.get(f"{API}/quality/quarantine", headers=RESEARCH).status_code
    hidden = httpx.get(f"{API}/sdtm/LB", headers=RESEARCH, params={"usubjid": "CARDIO-01-P014"})
    passed = (anonymous, forbidden, hidden.json()) == (401, 403, [])
    return passed, f"no key -> {anonymous}; research on quarantine -> {forbidden}; P014 hidden"


@check("Analysis consumer")
def analysis_consumer():
    """Prove research gets every participant except the one on hold, plus a model per study."""
    (people, p014) = one(
        "SELECT count(*), count(*) FILTER (WHERE usubjid LIKE '%%-P014')"
        " FROM research.participant_features"
    )
    (studies, worst) = one("SELECT count(*), min(auc) FROM research.model_score")
    return people == 59 and p014 == 0 and studies == 3 and worst >= 0.75, (
        f"features for {people} participants (P014 on hold, excluded); "
        f"case/control ROC AUC >= {worst:.2f} in all {studies} studies"
    )


def topic_size(topic: str) -> int:
    """Count the messages a topic holds (high minus low watermark, summed over partitions)."""
    probe = Consumer({"bootstrap.servers": settings.KAFKA_BROKERS, "group.id": "demo-probe"})
    try:
        partitions = probe.list_topics(topic, timeout=10).topics[topic].partitions
        marks = [
            probe.get_watermark_offsets(TopicPartition(topic, p), timeout=10) for p in partitions
        ]
        return sum(high - low for low, high in marks)
    finally:
        probe.close()


@check("Monitoring")
def monitoring():
    """Prove every delivery and every alert reached the monitor, with lag tracked per group."""
    # How many alerts exist depends on arrival order (an issue corrected before the outbox
    # drains needs none), so compare with what the topic actually holds.
    deliveries = len([p for p in SCENARIO.glob("*/d*/*") if p.is_file()])
    deadline = time.monotonic() + 20
    while True:
        on_topic = topic_size("alerts")
        (uploads, alerts) = one(
            "SELECT count(*) FILTER (WHERE topic = 'lab.uploads'),"
            " count(*) FILTER (WHERE topic = 'alerts') FROM monitor.event_log"
        )
        if alerts >= on_topic or time.monotonic() > deadline:
            break
        time.sleep(2)
    (groups,) = one("SELECT count(*) FROM monitor.consumer_lag")
    return uploads == deliveries and alerts == on_topic and groups == 3, (
        f"{uploads}/{deliveries} deliveries and {alerts}/{on_topic} alerts logged; "
        f"lag tracked for {groups} consumer groups"
    )


def consumers_caught_up(timeout: float = 120) -> None:
    """Wait until both consumers have processed the scenario (they run asynchronously)."""
    deliveries = len([p for p in SCENARIO.glob("*/d*/*") if p.is_file()])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        (models,) = one("SELECT count(*) FROM research.model_score")
        (uploads,) = one("SELECT count(*) FROM monitor.event_log WHERE topic = 'lab.uploads'")
        if models == 3 and uploads == deliveries:
            return
        time.sleep(3)


@check("Determinism")
def determinism():
    """Prove this run produced exactly the golden checksum."""
    current, golden = checksum(), GOLDEN.read_text().strip()
    return current.startswith(golden), f"{current} vs golden {golden}"


def main() -> None:
    """Wait for the scenario to finish, then run every check; exit 1 if any fails."""
    print("waiting for the three-day scenario to be processed...")
    settle(scenario_files())
    consumers_caught_up()
    failures = 0
    for topic, fn in CHECKS:
        passed, evidence = fn()
        failures += not passed
        print(f"{'✅' if passed else '❌'} {topic:<18} {evidence}")
    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
