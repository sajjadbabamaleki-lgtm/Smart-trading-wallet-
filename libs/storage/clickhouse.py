"""ClickHouse access.

Holds analytical event history (ADR-002). Uses the HTTP interface, which is
simpler to operate and adequate for the recorder's write rate; the native
protocol is a later optimisation if benchmarks call for it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from libs.config import Settings
from libs.storage.health import StoreHealth, StoreStatus
from libs.storage.migrations import MigrationRunner

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from clickhouse_connect.driver.client import Client

MIGRATION_DIRECTORY = Path("infrastructure/database/clickhouse")


@contextmanager
def connect(
    url: str,
    *,
    username: str,
    password: str,
    database: str,
    timeout_seconds: float = 5.0,
) -> Iterator[Client]:
    """Open a ClickHouse client, closing it on exit.

    Credentials are required arguments rather than defaults: a default
    credential in library code is how a development value becomes reachable in
    production (Phase 10 §10). They come from settings.
    """
    # Imported here rather than at module scope so that importing
    # `libs.storage` does not pull in every database driver — a service that
    # only talks to PostgreSQL should not load the ClickHouse stack.
    import clickhouse_connect  # noqa: PLC0415

    parsed = urlparse(url)
    client = clickhouse_connect.get_client(
        host=parsed.hostname or "localhost",
        port=parsed.port or 8123,
        username=username,
        password=password,
        database=database,
        secure=parsed.scheme == "https",
        connect_timeout=int(timeout_seconds),
        send_receive_timeout=int(timeout_seconds),
    )
    try:
        yield client
    finally:
        client.close()


@contextmanager
def connect_from_settings(settings: Settings) -> Iterator[Client]:
    """Open a client using configured credentials.

    The single place store credentials are read, so no caller has to know which
    settings fields exist or risk passing a stray literal.
    """
    with connect(
        settings.clickhouse_url,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database,
    ) as client:
        yield client


def check_health_from_settings(settings: Settings) -> StoreHealth:
    """Verify ClickHouse using configured credentials."""
    return check_health(
        settings.clickhouse_url,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database,
    )


@contextmanager
def _quiet_driver() -> Iterator[None]:
    """Silence the driver's own error logging for the duration of a check.

    clickhouse-connect logs a connection failure at ERROR on its own logger
    before raising. During a health check that failure is the expected outcome
    and is reported through the returned `StoreHealth`, so the driver's message
    is duplicate noise ahead of our own formatted output.
    """
    driver_logger = logging.getLogger("clickhouse_connect")
    previous = driver_logger.level
    driver_logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        driver_logger.setLevel(previous)


def check_health(url: str, **kwargs: Any) -> StoreHealth:
    """Verify ClickHouse is reachable and answers a query."""
    started = time.monotonic()
    try:
        with _quiet_driver(), connect(url, **kwargs) as client:
            version = client.server_version
            result = client.query("SELECT 1").result_rows
            elapsed_ms = (time.monotonic() - started) * 1000
            if result != [(1,)]:
                return StoreHealth(
                    store="clickhouse",
                    status=StoreStatus.DEGRADED,
                    latency_ms=elapsed_ms,
                    detail=f"SELECT 1 returned {result!r}",
                )
            return StoreHealth(
                store="clickhouse",
                status=StoreStatus.HEALTHY,
                latency_ms=elapsed_ms,
                facts={"version": str(version)},
            )
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return StoreHealth(
            store="clickhouse",
            status=StoreStatus.UNREACHABLE,
            latency_ms=(time.monotonic() - started) * 1000,
            detail=f"{type(exc).__name__}: {exc}",
        )


def build_runner(client: Client, *, directory: Path = MIGRATION_DIRECTORY) -> MigrationRunner:
    """Migration runner bound to an open ClickHouse client.

    ClickHouse DDL is not transactional, so a failed migration can leave a
    partially created object. The runner stops at the first failure, and
    recovery is by writing a corrective migration rather than by editing the
    failed one — which the checksum guard enforces anyway.
    """

    def execute(statement: str) -> None:
        client.command(statement)

    def fetch_applied() -> Sequence[tuple[str, str]]:
        exists = client.query(
            "SELECT count() FROM system.tables "
            "WHERE database = currentDatabase() AND name = 'schema_migrations'"
        ).result_rows
        if not exists or exists[0][0] == 0:
            return ()
        # FINAL collapses ReplacingMergeTree duplicates, so a re-applied
        # version reads as one row rather than two.
        rows = client.query("SELECT version, checksum FROM schema_migrations FINAL").result_rows
        return [(str(version), str(checksum)) for version, checksum in rows]

    return MigrationRunner(directory=directory, execute=execute, fetch_applied=fetch_applied)
