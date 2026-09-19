"""Writing and reading funding-rate history.

Separate from `candle_store` because the grain is different: funding settles on
the venue's schedule, not on candle boundaries, and the whole point of keeping
it at its own grain is that a point-in-time query can then ask "what had
settled by this moment" without a join that rounds.

FINAL on the read, for the reason every read in this project says FINAL: the
table replaces duplicates at merge time, a backfill is re-run, and a duplicated
settlement would shift a percentile without showing up anywhere.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from libs.domain.funding import FundingRate
from libs.storage.batching import in_partition_batches, month_of
from services.research.candle_store import as_utc

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from datetime import datetime

    from clickhouse_connect.driver.client import Client

COLUMNS: Sequence[str] = ("venue", "asset", "funding_time", "rate", "mark_price")


def write_funding(client: Client, rates: Sequence[FundingRate], *, venue: str) -> int:
    """Store settlements, replacing any already held for the same moment."""
    if not rates:
        return 0
    rows: list[list[object]] = [
        [venue, entry.asset, entry.moment, entry.rate, entry.mark_price] for entry in rates
    ]
    # Same monthly partitioning and the same hundred-partition ceiling as
    # `candles`: nine years of eight-hourly settlements spans 108 months, and
    # a single insert across all of them is refused.
    written = 0
    for batch in in_partition_batches(rows, partition=_partition_of):
        client.insert("funding_rates", list(batch), column_names=list(COLUMNS))
        written += len(batch)
    return written


def _partition_of(row: Sequence[object]) -> tuple[int, int]:
    """Which monthly partition a built row lands in.

    Reads `funding_time` by its position in `COLUMNS` rather than by a literal
    index, so reordering the columns cannot quietly start batching on a rate.
    """
    moment = row[COLUMNS.index("funding_time")]
    if not isinstance(moment, datetime):
        raise TypeError("funding_time must be a datetime to determine its partition")
    return month_of(moment)


def read_funding(
    client: Client,
    *,
    venue: str,
    asset: str,
    start: datetime,
    end: datetime,
) -> tuple[FundingRate, ...]:
    """Every stored settlement in the range, oldest first."""
    query = (
        "SELECT funding_time, rate, mark_price FROM funding_rates FINAL "
        "WHERE venue = %(venue)s AND asset = %(asset)s "
        "AND funding_time >= %(range_start)s AND funding_time < %(range_end)s "
        "ORDER BY funding_time"
    )
    result = client.query(
        query,
        parameters={
            "venue": venue,
            "asset": asset,
            "range_start": start,
            "range_end": end,
        },
    )
    return tuple(
        FundingRate(asset=asset, moment=as_utc(row[0]), rate=row[1], mark_price=row[2])
        for row in result.result_rows
    )
