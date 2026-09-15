"""Checking that what the recorder reported writing is what the store holds.

Invariant 8 says exchange state is authoritative and an unexplained mismatch is
a critical event. The same reasoning applies one layer down, to our own store:
a recorder that reports 6,049 events written while ClickHouse holds 4,000 is
not a recorder with a logging bug, it is a recorder losing data — and the
difference is invisible from either side alone.

This exists because that question could not be answered when it was first
asked. A run's BBO rate came out ten times lower than an earlier run's, and
nothing in the repository could distinguish "the market was quiet" from "the
store path drops rows", because the two numbers had never been compared.

Cheap enough to run every time: one COUNT over a time range the recorder
already knows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from clickhouse_connect.driver.client import Client


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """What the recorder counted, against what the store returned."""

    reported: int
    stored: int
    range_start: datetime
    range_end: datetime

    @property
    def agrees(self) -> bool:
        return self.reported == self.stored

    @property
    def missing(self) -> int:
        """Rows the recorder reported and the store does not have.

        Negative would mean the store holds *more* than this run wrote, which
        is a different problem — an overlapping run, or a range that caught
        someone else's rows — and is reported rather than clamped away.
        """
        return self.reported - self.stored

    def as_dict(self) -> dict[str, object]:
        return {
            "reported": self.reported,
            "stored": self.stored,
            "missing": self.missing,
            "agrees": self.agrees,
            "range_start": self.range_start.isoformat(),
            "range_end": self.range_end.isoformat(),
        }


def count_stored_market_events(
    client: Client, *, range_start: datetime, range_end: datetime
) -> int:
    """Count persisted market events in a receipt-time range.

    Inclusive of both bounds. The recorder's own window is taken from the first
    and last event it handled, so an exclusive upper bound would drop exactly
    one row and turn every clean run into a one-row discrepancy.
    """
    result = client.query(
        "SELECT count() FROM market_events "
        "WHERE local_receive_time >= %(start)s AND local_receive_time <= %(end)s",
        parameters={"start": range_start, "end": range_end},
    )
    return int(result.result_rows[0][0])


def reconcile(
    client: Client, *, reported: int, range_start: datetime, range_end: datetime
) -> Reconciliation:
    """Compare the recorder's count with the store's."""
    return Reconciliation(
        reported=reported,
        stored=count_stored_market_events(client, range_start=range_start, range_end=range_end),
        range_start=range_start,
        range_end=range_end,
    )
