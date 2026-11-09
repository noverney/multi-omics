"""Monitoring consumer (operations domain): uploads, alerts, lag and lab freshness.

Logs every upload, alert and dead letter, measures each consumer group's lag and raises
LAB_SILENT when a lab stops delivering.
"""

import json
import os
import time
from datetime import UTC, datetime

from confluent_kafka import (
    Consumer,
    ConsumerGroupTopicPartitions,
    Message,
    Producer,
    TopicPartition,
)
from confluent_kafka.admin import AdminClient
from psycopg import Connection

from omics import bus, db
from omics.models import Alert

TOPICS = ["lab.uploads", "alerts", "dlq"]
GROUPS = {"dispatcher": "lab.uploads", "analysis": "harmonized.sdtm", "monitor": "lab.uploads"}
EVERY_SECONDS = 15
FRESHNESS_SECONDS = int(os.environ.get("FRESHNESS_SECONDS", "120"))


def record(conn: Connection, message: Message) -> None:
    """Log one event (idempotent per topic/partition/offset); uploads also refresh freshness."""
    payload = json.loads(message.value())
    new = conn.execute(
        'INSERT INTO monitor.event_log (topic, partition, "offset", key, payload)'
        " VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING 1",
        [message.topic(), message.partition(), message.offset(),
         (message.key() or b"").decode(), json.dumps(payload)],
    ).fetchone()  # fmt: skip
    if new and message.topic() == "lab.uploads":
        conn.execute(
            "INSERT INTO monitor.lab_status (lab, last_upload_at, uploads) VALUES (%s, %s, 1)"
            " ON CONFLICT (lab) DO UPDATE SET uploads = monitor.lab_status.uploads + 1,"
            " last_upload_at = greatest(monitor.lab_status.last_upload_at,"
            " EXCLUDED.last_upload_at),"
            " silent_alerted_at = NULL",
            [payload["lab"], payload["uploaded_at"]],
        )


def measure_lag(conn: Connection, admin: AdminClient, probe: Consumer) -> None:
    """Store, per consumer group, how many messages it has not processed yet."""
    for group, topic in GROUPS.items():
        done = admin.list_consumer_group_offsets([ConsumerGroupTopicPartitions(group)])[group]
        committed = {tp.partition: tp.offset for tp in done.result().topic_partitions
                     if tp.topic == topic}  # fmt: skip
        lag = 0
        for partition in admin.list_topics(topic, timeout=10).topics[topic].partitions:
            low, high = probe.get_watermark_offsets(TopicPartition(topic, partition), timeout=10)
            position = committed.get(partition, -1)
            lag += high - (position if position >= 0 else low)
        conn.execute(
            "INSERT INTO monitor.consumer_lag VALUES (%s, %s, %s, now())"
            " ON CONFLICT (group_id, topic) DO UPDATE SET lag = EXCLUDED.lag,"
            " measured_at = EXCLUDED.measured_at",
            [group, topic, lag],
        )


def check_freshness(conn: Connection, producer: Producer) -> None:
    """Raise LAB_SILENT once per silence when a lab has not delivered within the SLA."""
    silent = conn.execute(
        "UPDATE monitor.lab_status SET silent_alerted_at = now() WHERE silent_alerted_at IS NULL"
        " AND last_upload_at < now() - make_interval(secs => %s) RETURNING lab, last_upload_at",
        [FRESHNESS_SECONDS],
    ).fetchall()
    for lab, last in silent:
        alert = Alert(
            code="LAB_SILENT",
            severity="WARNING",
            message=f"no upload since {last:%H:%M:%S} UTC (SLA {FRESHNESS_SECONDS} s)",
            lab=lab,
            created_at=datetime.now(UTC),
        )
        bus.send(producer, "alerts", lab, alert.model_dump_json())
    producer.flush(10)


def main() -> None:
    """Consume forever; every EVERY_SECONDS also measure lag and check freshness."""
    consumer, producer, admin = bus.consumer("monitor", TOPICS), bus.producer(), bus.admin()
    conn = db.connect(autocommit=True)
    next_check = 0.0
    print("monitor: watching lab.uploads, alerts and dlq")
    while True:
        message = consumer.poll(1.0)
        if message is not None and not message.error():
            record(conn, message)
            consumer.commit(message=message, asynchronous=False)
        if time.monotonic() >= next_check:
            measure_lag(conn, admin, consumer)
            check_freshness(conn, producer)
            next_check = time.monotonic() + EVERY_SECONDS


if __name__ == "__main__":
    main()
