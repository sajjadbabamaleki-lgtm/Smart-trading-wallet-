"""PostgreSQL access.

Holds transactional application state (ADR-003). Deliberately thin: a
connection factory, a health check, and the two callables the migration runner
needs. No ORM — the schema is the authority, and the tables here are written
and read by a small number of well-understood queries.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from libs.storage.health import StoreHealth, StoreStatus
from libs.storage.migrations import MigrationRunner

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from psycopg import Connection

MIGRATION_DIRECTORY = Path("infrastructure/database/postgres")


@contextmanager
def connect(dsn: str, *, timeout_seconds: float = 5.0) -> Iterator[Connection[Any]]:
    """Open a connection, closing it on exit.

    `autocommit` stays off: DDL in PostgreSQL is transactional, so a migration
    that fails partway rolls back rather than leaving a half-applied schema.
    """
    # Lazy import: see the note in libs/storage/clickhouse.py.
    import psycopg  # noqa: PLC0415

    connection = psycopg.connect(dsn, connect_timeout=int(timeout_seconds))
    try:
        yield connection
    finally:
        connection.close()


def check_health(dsn: str, *, timeout_seconds: float = 5.0) -> StoreHealth:
    """Verify PostgreSQL is reachable and reports a version."""
    started = time.monotonic()
    try:
        with connect(dsn, timeout_seconds=timeout_seconds) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version(), current_database(), current_user")
                row = cursor.fetchone()
            elapsed_ms = (time.monotonic() - started) * 1000
            if row is None:
                return StoreHealth(
                    store="postgres",
                    status=StoreStatus.DEGRADED,
                    latency_ms=elapsed_ms,
                    detail="connected but SELECT version() returned no row",
                )
            version, database, user = row
            return StoreHealth(
                store="postgres",
                status=StoreStatus.HEALTHY,
                latency_ms=elapsed_ms,
                facts={
                    "version": str(version).split(" on ")[0],
                    "database": str(database),
                    "user": str(user),
                },
            )
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return StoreHealth(
            store="postgres",
            status=StoreStatus.UNREACHABLE,
            latency_ms=(time.monotonic() - started) * 1000,
            detail=f"{type(exc).__name__}: {exc}",
        )


def build_runner(
    connection: Connection[Any], *, directory: Path = MIGRATION_DIRECTORY
) -> MigrationRunner:
    """Migration runner bound to an open PostgreSQL connection.

    Each statement is committed as it succeeds, so the ledger reflects exactly
    what was applied if a later migration fails.
    """

    def execute(statement: str) -> None:
        with connection.cursor() as cursor:
            cursor.execute(statement)
        connection.commit()

    def fetch_applied() -> Sequence[tuple[str, str]]:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = 'schema_migrations'"
            )
            if cursor.fetchone() is None:
                # First run: the ledger is itself migration 001.
                return ()
            cursor.execute("SELECT version, checksum FROM schema_migrations")
            return [(str(version), str(checksum)) for version, checksum in cursor.fetchall()]

    return MigrationRunner(directory=directory, execute=execute, fetch_applied=fetch_applied)
