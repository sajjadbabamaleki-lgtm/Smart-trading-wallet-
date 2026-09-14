"""Reading rows and gaps for a dataset build, and recording its manifest.

Separated from `dataset.py` so that the decisions — what is in range, what the
quality filter admits, whether the dataset is VALID — are testable without a
database, and so that the SQL lives in one place rather than inside them.

Every query selects on `local_receive_time`. That is the point-in-time
selection and, since M1's migration 005, also the indexed one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from services.research.dataset import CANONICAL_COLUMNS, DatasetSpec, GapRecord, manifest_row

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from clickhouse_connect.driver.client import Client
    from psycopg import Connection

    from libs.schemas.dataset import DatasetManifest


def fetch_rows(client: Client, spec: DatasetSpec) -> Sequence[dict[str, Any]]:
    """Read the events a dataset covers, in a deterministic order.

    The ORDER BY is not cosmetic: the checksum is computed over the rows in the
    order they arrive, so an unordered read would give the same data a
    different identity on every run. `event_id` breaks ties, because receipt
    time alone does not — two events can share a microsecond.
    """
    columns = ", ".join(CANONICAL_COLUMNS)
    query = (
        f"SELECT {columns} FROM market_events "  # noqa: S608 - columns are a module constant
        "WHERE asset = %(asset)s "
        "AND event_type IN %(event_types)s "
        "AND local_receive_time >= %(range_start)s "
        "AND local_receive_time < %(range_end)s "
        "ORDER BY local_receive_time, event_id"
    )
    result = client.query(
        query,
        parameters={
            "asset": spec.asset,
            "event_types": spec.data_types,
            "range_start": spec.range_start,
            "range_end": spec.range_end,
        },
    )
    return [dict(zip(CANONICAL_COLUMNS, row, strict=True)) for row in result.result_rows]


def fetch_gaps(connection: Connection, spec: DatasetSpec) -> Sequence[GapRecord]:
    """Read every gap overlapping the range.

    Overlap, not containment: a gap that began before the range and has not
    closed still leaves this range missing data, and it is exactly the case a
    containment test would miss. An open gap (`gap_end IS NULL`) therefore
    matches on its start alone.
    """
    query = (
        "SELECT gap_id::text, asset, event_type, gap_start, gap_end, backfill_status "
        "FROM data_gaps "
        "WHERE asset = %(asset)s "
        "AND gap_start < %(range_end)s "
        "AND (gap_end IS NULL OR gap_end >= %(range_start)s) "
        "ORDER BY gap_start, gap_id"
    )
    with connection.cursor() as cursor:
        cursor.execute(
            query,
            {
                "asset": spec.asset,
                "range_start": spec.range_start,
                "range_end": spec.range_end,
            },
        )
        return [
            GapRecord(
                gap_id=str(row[0]),
                asset=str(row[1]),
                event_type=str(row[2]),
                gap_start=row[3],
                gap_end=row[4],
                backfill_status=str(row[5]),
            )
            for row in cursor.fetchall()
        ]


def record_manifest(connection: Connection, manifest: DatasetManifest) -> None:
    """Write the manifest, refusing to overwrite an existing one.

    A dataset_id is derived from its content, so a second build of the same
    rows produces the same id and the same manifest — nothing to change. A
    conflict on that id with *different* content cannot happen without a
    checksum collision, so ON CONFLICT DO NOTHING is the honest behaviour
    rather than a silent overwrite of a record research already cites.
    """
    row = manifest_row(manifest)
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO dataset_manifests ({columns}) "  # noqa: S608 - names are model fields
            f"VALUES ({placeholders}) ON CONFLICT (dataset_id) DO NOTHING",
            row,
        )
    connection.commit()
