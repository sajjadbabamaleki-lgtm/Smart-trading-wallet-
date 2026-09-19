"""Splitting an insert so it does not touch too many partitions.

Written because nine years of history failed to store and six years did not:
the tables partition by month, ClickHouse refuses a single insert across more
than a hundred partitions, and 72 months passed where 108 did not. The error
names the setting, which invites raising it. The setting was not the problem.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from libs.storage.batching import (
    MAX_PARTITIONS_PER_INSERT,
    in_partition_batches,
    month_of,
)


def months(count: int, *, per_month: int = 1) -> list[datetime]:
    """Timestamps spanning `count` distinct months."""
    out = []
    for index in range(count):
        year, month = 2017 + index // 12, index % 12 + 1
        for offset in range(per_month):
            out.append(datetime(year, month, 1 + offset, tzinfo=UTC))
    return out


def batches(
    rows: list[datetime], *, limit: int = MAX_PARTITIONS_PER_INSERT
) -> list[list[datetime]]:
    return [list(batch) for batch in in_partition_batches(rows, partition=month_of, limit=limit)]


class TestPartitionKey:
    def test_the_month_is_the_partition(self) -> None:
        assert month_of(datetime(2024, 3, 17, 4, 30, tzinfo=UTC)) == (2024, 3)

    def test_two_days_in_one_month_share_a_partition(self) -> None:
        assert month_of(datetime(2024, 3, 1, tzinfo=UTC)) == month_of(
            datetime(2024, 3, 31, tzinfo=UTC)
        )


class TestBatching:
    def test_a_range_inside_the_limit_is_one_batch(self) -> None:
        """Six years is 72 months and stored fine; it must not be split needlessly."""
        assert len(batches(months(72), limit=100)) == 1

    def test_a_range_past_the_limit_is_split(self) -> None:
        """Nine years is 108 months, which is what failed."""
        assert len(batches(months(108), limit=50)) == 3

    def test_no_batch_exceeds_the_limit(self) -> None:
        limit = 7
        for batch in batches(months(60, per_month=3), limit=limit):
            assert len({month_of(moment) for moment in batch}) <= limit

    def test_every_row_is_yielded_exactly_once(self) -> None:
        """A helper that dropped its last partial batch would lose the most
        recent history, which is the part anyone notices last."""
        rows = months(108, per_month=4)
        assert [moment for batch in batches(rows, limit=9) for moment in batch] == rows

    def test_order_is_preserved(self) -> None:
        rows = months(40, per_month=2)
        flat = [moment for batch in batches(rows, limit=6) for moment in batch]
        assert flat == sorted(flat)

    def test_a_month_is_not_split_across_batches_unnecessarily(self) -> None:
        """A new batch starts on a partition boundary, not mid-partition."""
        rows = months(30, per_month=5)
        for batch in batches(rows, limit=4)[1:]:
            assert batch[0].day == 1

    def test_no_rows_yields_nothing(self) -> None:
        assert batches([]) == []

    def test_a_single_row_is_one_batch(self) -> None:
        assert batches(months(1)) == [months(1)]

    def test_a_zero_limit_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one partition"):
            batches(months(3), limit=0)

    def test_the_default_leaves_headroom_under_the_server_default(self) -> None:
        """A batch sized exactly at the boundary fails on a stricter server."""
        assert MAX_PARTITIONS_PER_INSERT < 100

    def test_many_rows_in_one_partition_stay_together(self) -> None:
        """The limit counts partitions, not rows: a busy month is one batch."""
        one_month = [
            datetime(2024, 3, 1, tzinfo=UTC) + timedelta(hours=index) for index in range(700)
        ]
        assert len(batches(one_month, limit=2)) == 1
