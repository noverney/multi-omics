"""Object storage helpers (boto3): works with any S3 API, here SeaweedFS."""

import hashlib

import boto3
from botocore.config import Config

from omics import settings

BUCKETS = ("raw", "curated")  # raw = immutable lab uploads, curated = pipeline outputs


def client(access_key: str = settings.S3_ACCESS_KEY, secret_key: str = settings.S3_SECRET_KEY):
    """Return an S3 client for the configured endpoint and identity."""
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        # Path-style URLs and checksums only when required keep non-AWS stores compatible.
        config=Config(
            s3={"addressing_style": "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            retries={"max_attempts": 5, "mode": "standard"},
        ),
    )


def ensure_buckets(s3) -> list[str]:
    """Create any missing bucket and return the names created."""
    existing = {bucket["Name"] for bucket in s3.list_buckets().get("Buckets", [])}
    created = [name for name in BUCKETS if name not in existing]
    for name in created:
        s3.create_bucket(Bucket=name)
    return created


def sha256(data: bytes) -> str:
    """Return the hex SHA-256 of file bytes: a file's identity throughout the pipeline."""
    return hashlib.sha256(data).hexdigest()
