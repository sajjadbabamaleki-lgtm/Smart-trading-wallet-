"""Writing and reading historical candles.

Kept apart from `store.py` because the two tables answer different questions and
must not be confused. `store.py` reads `market_events`, where every row carries
the moment we received it and selection is point-in-time. This reads `candles`,
where the only timestamp is the venue's and the rows describe a period long
before the system existed.

Both reads say FINAL. The table replaces duplicates at merge time, and a query
without FINAL can see the same hour twice — once from a first backfill, once
from a re-run — which turns every average computed over it into a quiet error.
The cost is a slower scan over a table with tens of thousands of rows, which is
nothing, and the alternative is a wrong number nobody can see.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from libs.exchange.hyperliquid.candles import VENUE, Candle, CandleRequest

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from clickhouse_connect.driver.client import Client

COLUMNS: Sequence[str] = (
    "venue",
    "asset",
    "interval",
    "interval_seconds",
    "open_time",
    "close_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trades",
)


def write_candles(client: Client, candles: Sequence[Candle]) -> int:
    """Store candles, replacing any already held for the same interval.

    Returns the number written. Re-running a backfill is expected and safe:
    replacement is what `ReplacingMergeTree` is for here.
    """
    if not candles:
        return 0
    rows = [
        [
            VENUE,
            candle.asset,
            candle.interval,
            candle.interval_seconds,
            candle.open_time,
            candle.close_time,
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            candle.volume,
            candle.trades,
        ]
        for candle in candles
    ]
    client.insert("candles", rows, column_names=list(COLUMNS))
    return len(rows)


def as_utc(value: datetime) -> datetime:
    """Attach UTC to a timestamp that came back without it.

    ClickHouse stores these columns as `DateTime64(3, 'UTC')` and the driver
    returns them naive. A naive timestamp in a candle is not a cosmetic problem:
    it cannot be compared with an aware one, so it crashes on contact with
    anything that knows what time it is — which is how this was found — and if
    it did not crash it would be read as local time and shift the whole series.

    Coerced at the boundary, once, rather than defended against at each use.
    A value that already carries a zone is returned as it is, because
    re-labelling one would be the same class of error in the other direction.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def read_candles(client: Client, request: CandleRequest) -> tuple[Candle, ...]:
    """Every stored candle the request covers, oldest first.

    Ordered here rather than by the caller because a strategy replayed over
    candles in the wrong order is a strategy reading the future, and that is not
    a mistake worth leaving available.
    """
    query = (
        "SELECT open_time, close_time, open, high, low, close, volume, trades "
        "FROM candles FINAL "
        "WHERE venue = %(venue)s AND asset = %(asset)s AND interval = %(interval)s "
        "AND open_time >= %(range_start)s AND open_time < %(range_end)s "
        "ORDER BY open_time"
    )
    result = client.query(
        query,
        parameters={
            "venue": VENUE,
            "asset": request.asset,
            "interval": request.interval,
            "range_start": request.start,
            "range_end": request.end,
        },
    )
    return tuple(
        Candle(
            asset=request.asset,
            interval=request.interval,
            open_time=as_utc(row[0]),
            close_time=as_utc(row[1]),
            open=row[2],
            high=row[3],
            low=row[4],
            close=row[5],
            volume=row[6],
            trades=row[7],
        )
        for row in result.result_rows
    )


def missing_intervals(candles: Sequence[Candle], *, step: timedelta) -> tuple[tuple[Any, Any], ...]:
    """Holes in an otherwise regular series, as (after, before) pairs.

    A venue's archive is not guaranteed complete, and a strategy tested over a
    series with a silent three-day hole has been tested over a market that
    skipped three days. Declared rather than filled: the same rule the recorder
    follows for its own gaps.
    """
    holes: list[tuple[Any, Any]] = []
    for earlier, later in itertools.pairwise(candles):
        expected = earlier.open_time + step
        if later.open_time > expected:
            holes.append((earlier.open_time, later.open_time))
    return tuple(holes)
