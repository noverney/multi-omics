"""Redpanda (Kafka API) helpers: topics, an idempotent producer and manual-commit consumers.

Messages are small JSON documents (pointers and records); file contents never travel
through the bus, they live in S3 (claim-check pattern).
"""

import time

from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from omics import settings

# topic -> partitions. RF=3 with min ISR=2: any single broker can fail without losing data.
TOPICS = {"lab.uploads": 3, "harmonized.sdtm": 3, "alerts": 3, "dlq": 1}
REPLICAS = 3


def admin() -> AdminClient:
    """Return an admin client for the cluster."""
    return AdminClient({"bootstrap.servers": settings.KAFKA_BROKERS})


def wait_for_brokers(client: AdminClient, count: int = REPLICAS, timeout: float = 120) -> None:
    """Block until `count` brokers have joined; topics need every replica present."""
    deadline = time.monotonic() + timeout
    while len(client.list_topics(timeout=10).brokers) < count:
        if time.monotonic() > deadline:
            raise TimeoutError(f"fewer than {count} brokers after {timeout}s")
        time.sleep(2)


def ensure_topics(client: AdminClient) -> list[str]:
    """Create missing topics; retention is unlimited so the log can be replayed."""
    existing = set(client.list_topics(timeout=10).topics)
    config = {"min.insync.replicas": "2", "retention.ms": "-1"}
    new = [
        NewTopic(name, num_partitions=parts, replication_factor=REPLICAS, config=config)
        for name, parts in TOPICS.items()
        if name not in existing
    ]
    if new:
        for future in client.create_topics(new).values():
            future.result()
    return [topic.topic for topic in new]


def producer() -> Producer:
    """Return an idempotent producer: acked by all in-sync replicas, no duplicates on retry."""
    return Producer(
        {"bootstrap.servers": settings.KAFKA_BROKERS, "enable.idempotence": True, "acks": "all"}
    )


def send(prod: Producer, topic: str, key: str, value: str) -> None:
    """Queue one JSON message; call `prod.flush()` when the batch must be durable."""
    prod.produce(topic, key=key.encode(), value=value.encode())
    prod.poll(0)


def consumer(group: str, topics: list[str]) -> Consumer:
    """Return a subscribed consumer whose offsets advance only on explicit commit."""
    client = Consumer(
        {
            "bootstrap.servers": settings.KAFKA_BROKERS,
            "group.id": group,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    client.subscribe(topics)
    return client
