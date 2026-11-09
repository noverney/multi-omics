"""Lab simulator: uploads one lab's files to S3, then announces each on `lab.uploads`.

Scenario files live in `data/scenario/<lab>/d<N>/`. Day N starts (N-1) * DAY_SECONDS after
launch (divided by SIM_SPEED), so labs deliver independently, like real external partners.
"""

import argparse
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from confluent_kafka import Producer

from omics import bus, s3
from omics.models import UploadEvent
from omics.settings import ROOT

DAY_SECONDS = 20.0
FILE_GAP_SECONDS = 2.0


def deliver(s3_client, producer: Producer, lab: str, path: Path) -> UploadEvent:
    """Upload a file under a content-addressed key, then publish its claim-check event."""
    data = path.read_bytes()
    digest = s3.sha256(data)
    key = f"{lab}/{digest}/{path.name}"  # same bytes -> same key: raw/ is never overwritten
    s3_client.put_object(Bucket="raw", Key=key, Body=data)
    event = UploadEvent(
        lab=lab,
        file_name=path.name,
        s3_uri=f"s3://raw/{key}",
        sha256=digest,
        size=len(data),
        uploaded_at=datetime.now(UTC),
    )
    bus.send(producer, "lab.uploads", lab, event.model_dump_json())
    producer.flush(30)
    print(f"{lab}: delivered {path.name} ({len(data)} bytes, sha256 {digest[:12]}…)")
    return event


def run_scenario(lab: str, speed: float) -> None:
    """Deliver every scenario day in order, pausing between days and between files."""
    s3_client, producer = s3.client(), bus.producer()
    start = time.monotonic()
    for day in sorted((ROOT / "data" / "scenario" / lab).glob("d*")):
        day_start = start + (int(day.name[1:]) - 1) * DAY_SECONDS / speed
        time.sleep(max(0.0, day_start - time.monotonic()))
        for path in sorted(day.iterdir()):
            deliver(s3_client, producer, lab, path)
            time.sleep(FILE_GAP_SECONDS / speed)
    print(f"{lab}: scenario complete")


def main() -> None:
    """Run the whole scenario, or deliver a single file with --file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", default=os.environ.get("LAB"))
    parser.add_argument("--file", type=Path, help="deliver only this file")
    parser.add_argument("--speed", type=float, default=float(os.environ.get("SIM_SPEED", "1")))
    args = parser.parse_args()
    if args.file:
        deliver(s3.client(), bus.producer(), args.lab, args.file)
    else:
        run_scenario(args.lab, args.speed)


if __name__ == "__main__":
    main()
