"""Runtime settings from environment variables; dev defaults match `.env.example`."""

import os
from pathlib import Path

from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[2]  # repo root (/app inside containers)


def env(name: str, default: str) -> str:
    """Return environment variable `name`, or `default` when it is unset."""
    return os.environ.get(name, default)


# Each service runs with its own least-privilege identity (set per service in compose).
DB_DSN = make_conninfo(
    host=env("DB_HOST", "postgres"),
    dbname=env("DB_NAME", "omics"),
    user=env("DB_USER", "pipeline_rw"),
    password=env("DB_PASSWORD", "pipeline-dev"),
)
KAFKA_BROKERS = env("KAFKA_BROKERS", "redpanda-0:9092,redpanda-1:9092,redpanda-2:9092")
S3_ENDPOINT = env("S3_ENDPOINT", "http://seaweedfs:8333")
S3_ACCESS_KEY = env("S3_ACCESS_KEY", "pipeline")
S3_SECRET_KEY = env("S3_SECRET_KEY", "pipeline-dev-secret")
