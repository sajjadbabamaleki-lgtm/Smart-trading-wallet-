"""Splitting an insert so it does not touch too many partitions at once.

ClickHouse refuses a single INSERT block that writes to more than
`max_partitions_per_insert_block` partitions — 100 by default — and it is
right to: a block spread across hundreds of partitions creates a part in each
one and makes every later merge and query slower.

This project met the limit the honest way. `candles` partitions by month, six
years of history is 72 partitions and inserted fine, and nine years is 108 and
did not. The error names the setting, which invites raising it; the setting is
not the problem. The insert is.

So writes are grouped by the partition they land in, and flushed before the
count would exceed the limit. Rows arrive in time order, so consecutive
batches cover consecutive stretches of history and each one writes a handful of
parts rather than a hundred.

The limit here is half the server's default on purpose: a batch sized exactly
at the boundary fails on any server configured lower, and a backfill that
fails after writing half its range is worse than one that takes an extra
round trip.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from datetime import datetime
from typing import Final

MAX_PARTITIONS_PER_INSERT: Final = 50
"""Partitions a single insert may touch. Half the ClickHouse default of 100."""


def month_of(moment: datetime) -> tuple[int, int]:
    """The partition a `toYYYYMM` key puts a timestamp in."""
    return (moment.year, moment.month)


def in_partition_batches[Row](
    rows: Sequence[Row],
    *,
    partition: Callable[[Row], tuple[int, int]],
    limit: int = MAX_PARTITIONS_PER_INSERT,
) -> Iterator[Sequence[Row]]:
    """Yield slices of `rows`, each touching at most `limit` partitions.

    Order is preserved and every row is yielded exactly once, which matters
    more than the batching: a helper that silently dropped the last partial
    batch would lose the most recent history, and the most recent history is
    the part anyone notices last.
    """
    if limit < 1:
        raise ValueError("a batch must be allowed at least one partition")
    if not rows:
        return

    start = 0
    seen: set[tuple[int, int]] = set()
    for index, row in enumerate(rows):
        key = partition(row)
        if key not in seen and len(seen) >= limit:
            yield rows[start:index]
            start = index
            seen = {key}
            continue
        seen.add(key)
    yield rows[start:]
