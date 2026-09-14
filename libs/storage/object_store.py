"""Object storage — the immutable raw archive.

Phase 2 §8.1 and Build 0.1 Rev.2 §20: raw source data is preserved before
normalization, and raw data is never overwritten because normalization logic
changed. This is the Bronze layer.

Versioning on the bucket is what makes "effectively immutable" real rather than
aspirational: if a provider revises history, or a process writes to a key twice,
both versions remain retrievable (Phase 3 §17). The health check therefore
verifies versioning is enabled and reports DEGRADED when it is not — an archive
that silently overwrites is worse than no archive, because it looks fine.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

from libs.config import Settings
from libs.storage.health import StoreHealth, StoreStatus

ISO_DATE_LENGTH: Final = 10

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from mypy_boto3_s3.client import S3Client


@contextmanager
def connect(
    endpoint: str,
    *,
    access_key: str,
    secret_key: str,
    region: str = "us-east-1",
    timeout_seconds: float = 5.0,
) -> Iterator[S3Client]:
    """Open an S3-compatible client.

    MinIO locally, and the same API for a cloud object store later, so the
    archive layer does not need rewriting when the deployment changes.

    Credentials are required arguments rather than defaults, for the same
    reason as in the ClickHouse client: no secret belongs in library code
    (Phase 10 §10).
    """
    import boto3  # noqa: PLC0415
    from botocore.config import Config  # noqa: PLC0415

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(
            connect_timeout=timeout_seconds,
            read_timeout=timeout_seconds,
            retries={"max_attempts": 1},
            # MinIO serves buckets as paths, not as DNS subdomains.
            s3={"addressing_style": "path"},
        ),
    )
    try:
        yield client
    finally:
        client.close()


@contextmanager
def connect_from_settings(settings: Settings) -> Iterator[S3Client]:
    """Open a client using configured credentials."""
    with connect(
        settings.object_store_endpoint,
        access_key=settings.object_store_access_key,
        secret_key=settings.object_store_secret_key,
    ) as client:
        yield client


def check_health_from_settings(settings: Settings) -> StoreHealth:
    """Verify the archive bucket using configured credentials."""
    return check_health(
        settings.object_store_endpoint,
        settings.object_store_bucket,
        access_key=settings.object_store_access_key,
        secret_key=settings.object_store_secret_key,
    )


# PLR0913: six arguments, and naming them is the point — this function had a
# `**kwargs: Any` tail that hid two required credentials from the type
# checker. Bundling them back into an object would restore the same blind
# spot in a different shape.
def check_health(  # noqa: PLR0913
    endpoint: str,
    bucket: str,
    *,
    access_key: str,
    secret_key: str,
    region: str = "us-east-1",
    timeout_seconds: float = 5.0,
) -> StoreHealth:
    """Verify the archive bucket exists and is versioned.

    Credentials are named here rather than forwarded through `**kwargs`. The
    kwargs form type-checked clean while omitting them, because Any accepts
    anything and mypy cannot see through it to `connect`'s required arguments —
    so the first caller that forgot them failed at runtime, inside an
    integration test that had never been run against a real stack.
    """
    started = time.monotonic()
    try:
        with connect(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            region=region,
            timeout_seconds=timeout_seconds,
        ) as client:
            client.head_bucket(Bucket=bucket)
            versioning = client.get_bucket_versioning(Bucket=bucket)
            elapsed_ms = (time.monotonic() - started) * 1000
            state = versioning.get("Status", "Disabled")
            facts = {"bucket": bucket, "versioning": str(state)}
            if state != "Enabled":
                return StoreHealth(
                    store="object_store",
                    status=StoreStatus.DEGRADED,
                    latency_ms=elapsed_ms,
                    detail=(
                        f"bucket versioning is '{state}'; the raw archive must be "
                        f"versioned so a rewritten key does not destroy the "
                        f"original evidence"
                    ),
                    facts=facts,
                )
            return StoreHealth(
                store="object_store",
                status=StoreStatus.HEALTHY,
                latency_ms=elapsed_ms,
                facts=facts,
            )
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        elapsed_ms = (time.monotonic() - started) * 1000
        name = type(exc).__name__
        # A missing bucket is a configuration problem, not an unreachable
        # store: the distinction tells the operator whether to run the
        # bootstrap or to start the stack.
        if "NoSuchBucket" in name or "404" in str(exc):
            return StoreHealth(
                store="object_store",
                status=StoreStatus.MISCONFIGURED,
                latency_ms=elapsed_ms,
                detail=f"bucket '{bucket}' does not exist; run `make stack-up`",
            )
        return StoreHealth(
            store="object_store",
            status=StoreStatus.UNREACHABLE,
            latency_ms=elapsed_ms,
            detail=f"{name}: {exc}",
        )


def raw_key(*, source: str, channel: str, date: str, raw_id: str) -> str:
    """Archive key for one raw message.

    Shaped `raw/<source>/<channel>/<YYYY-MM-DD>/<raw_id>.json` to match the
    layout in Build 0.1 Rev.1 §14, and date-partitioned so a day's capture can
    be listed or re-read without scanning the bucket.
    """
    for name, value in (("source", source), ("channel", channel), ("raw_id", raw_id)):
        if not value or "/" in value:
            raise ValueError(f"{name} must be non-empty and contain no '/': {value!r}")
    if len(date) != ISO_DATE_LENGTH or date[4] != "-" or date[7] != "-":
        raise ValueError(f"date must be YYYY-MM-DD, got {date!r}")
    return f"raw/{source}/{channel}/{date}/{raw_id}.json"
