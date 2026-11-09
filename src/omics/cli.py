"""Operator commands: `python -m omics.cli <command>`."""

import argparse
import time
from collections.abc import Callable

from omics import bus, db, s3, settings


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


def main() -> None:
    """Parse arguments and run the chosen command."""
    parser = argparse.ArgumentParser(prog="omics")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="bootstrap db, buckets and topics").set_defaults(func=cmd_init)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
