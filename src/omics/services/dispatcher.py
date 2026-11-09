"""Dispatcher: turns each `lab.uploads` event into exactly one Prefect flow run.

Each delivery is first registered in Postgres (RECEIVED), so the reconciler can never lose
it. The run's idempotency key is `sha256:attempts` and offsets are committed only after
Prefect accepted the run: a redelivered event never starts a second run (effectively once).
"""

import json

from confluent_kafka import Message, Producer
from prefect.deployments import run_deployment
from pydantic import ValidationError

from omics import bus, contracts, db, load
from omics.models import UploadEvent

CONTRACTS = contracts.load_all()


def handle(message: Message, producer: Producer) -> None:
    """Validate one event, register the file and start its run; bad events go to the DLQ."""
    try:
        event = UploadEvent.model_validate_json(message.value())
    except ValidationError as exc:
        dead = {"error": str(exc), "raw": message.value().decode(errors="replace")}
        bus.send(producer, "dlq", (message.key() or b"unknown").decode(), json.dumps(dead))
        producer.flush(30)
        print(f"dispatcher: invalid event at offset {message.offset()} -> dlq")
        return
    with db.connect() as conn:
        contract = contracts.match(CONTRACTS, event.lab, event.file_name)
        status, attempts = load.register(conn, event, contract)
    if status != "RECEIVED":  # in flight, done or rejected: reconcile owns stuck files
        print(f"dispatcher: {event.lab}/{event.file_name} is already {status}, skipped")
        return
    run_deployment(
        "ingest-file/main",
        parameters={"event": event.model_dump(mode="json")},
        timeout=0,
        idempotency_key=f"{event.sha256}:{attempts}",
    )
    print(f"dispatcher: {event.lab}/{event.file_name} -> ingest-file run")


def main() -> None:
    """Consume forever; a crash is safe because offsets advance only after `handle`."""
    consumer = bus.consumer("dispatcher", ["lab.uploads"])
    producer = bus.producer()
    print("dispatcher: waiting for lab.uploads")
    while True:
        message = consumer.poll(1.0)
        if message is None:
            continue
        if message.error():
            print(f"dispatcher: {message.error()}")
            continue
        handle(message, producer)
        consumer.commit(message=message, asynchronous=False)


if __name__ == "__main__":
    main()
