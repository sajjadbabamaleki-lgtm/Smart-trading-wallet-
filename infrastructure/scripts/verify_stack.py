#!/usr/bin/env python3
"""Verify the storage stack — M1's deliverable.

Build 0.1 Rev.2 §41 asks M1 to *verify* PostgreSQL, ClickHouse, Redis and raw
object storage, and Rev.1 §77 requires that a clean environment can start the
whole stack. This script is how that claim is checked rather than asserted, and
its output is the M1 evidence artifact.

    python infrastructure/scripts/verify_stack.py            # check only
    python infrastructure/scripts/verify_stack.py --migrate  # check, then migrate
    python infrastructure/scripts/verify_stack.py --json     # machine-readable

Exits non-zero when any store is unusable, so it can gate a later milestone.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs.config import ConfigurationError, Settings, load_settings  # noqa: E402
from libs.storage import StoreHealth, StoreStatus, check_all  # noqa: E402
from libs.storage import clickhouse as ch  # noqa: E402
from libs.storage import object_store as obj  # noqa: E402
from libs.storage import postgres as pg  # noqa: E402
from libs.storage import redis_store as rds  # noqa: E402
from libs.storage.migrations import MigrationError  # noqa: E402


def _run_migrations(settings: Settings) -> list[str]:
    """Apply pending migrations to both SQL stores, returning a report."""
    lines: list[str] = []
    dsn = settings.postgres_dsn

    with pg.connect(dsn) as connection:
        runner = pg.build_runner(connection, directory=REPO_ROOT / pg.MIGRATION_DIRECTORY)
        applied = runner.apply()
        lines.append(
            f"postgres       applied {len(applied)}: "
            f"{', '.join(m.version for m in applied) or 'nothing pending'}"
        )

    with ch.connect_from_settings(settings) as client:
        runner = ch.build_runner(client, directory=REPO_ROOT / ch.MIGRATION_DIRECTORY)
        applied = runner.apply()
        lines.append(
            f"clickhouse     applied {len(applied)}: "
            f"{', '.join(m.version for m in applied) or 'nothing pending'}"
        )

    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--migrate", action="store_true", help="apply pending migrations after checking"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args()

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"configuration refused: {exc}", file=sys.stderr)
        return 2

    results = check_all(
        {
            "postgres": lambda: pg.check_health(settings.postgres_dsn),
            "clickhouse": lambda: ch.check_health_from_settings(settings),
            "redis": lambda: rds.check_health(settings.redis_url),
            "object_store": lambda: obj.check_health_from_settings(settings),
        }
    )

    unusable = [result for result in results if not result.is_usable]
    migration_report: list[str] = []

    # Migrations are attempted only when both SQL stores are healthy. Running
    # DDL against a degraded store risks a partially applied schema, and
    # ClickHouse DDL is not transactional.
    if args.migrate and not unusable:
        try:
            migration_report = _run_migrations(settings)
        except MigrationError as exc:
            migration_report = [f"migration failed: {exc}"]
            unusable.append(
                StoreHealth(store="migrations", status=StoreStatus.DEGRADED, detail=str(exc))
            )
    elif args.migrate:
        migration_report = ["skipped: not every store is usable"]

    if args.json:
        print(
            json.dumps(
                {
                    "environment": settings.execution_environment.value,
                    "stores": [
                        {
                            "store": result.store,
                            "status": result.status.value,
                            "latency_ms": result.latency_ms,
                            "detail": result.detail,
                            "facts": result.facts,
                        }
                        for result in results
                    ],
                    "migrations": migration_report,
                    "usable": not unusable,
                },
                indent=2,
            )
        )
    else:
        print(f"environment    {settings.execution_environment.value}")
        print()
        for result in results:
            print(result.render())
            for key, value in result.facts.items():
                print(f"{'':<14} {key}: {value}")
        if migration_report:
            print()
            for line in migration_report:
                print(line)
        print()
        if unusable:
            print(f"NOT READY — {len(unusable)} store(s) unusable")
        else:
            print("all stores usable")

    return 1 if unusable else 0


if __name__ == "__main__":
    sys.exit(main())
