"""A candle, and the rules that hold for one whatever venue supplied it.

`Candle` and `CandleRequest` started in the Hyperliquid package because
Hyperliquid was the only source of history. They are not venue-specific: an
interval's length, whether it has closed, and how far price moved inside it
mean the same thing everywhere, and a second source made keeping them behind
one venue's name misleading.

What stays venue-specific is everything about *fetching* — the endpoint, the
request shape, the page limit, how much history is retained, and the venue's
own name on the stored row.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

BPS: Final = Decimal(10000)

INTERVAL_SECONDS: Final = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}
"""The intervals this project asks for, with their length in seconds.

An explicit table rather than a parser, because the length is needed to decide
whether a candle has closed, and guessing that from a string is how an "8h"
typo becomes a silently accepted eight-minute candle.
"""


class CandleError(RuntimeError):
    """The venue returned something this module will not interpret."""


@dataclass(frozen=True, slots=True)
class Candle:
    """One closed interval, as the venue reported it."""

    asset: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trades: int

    @property
    def interval_seconds(self) -> int:
        return INTERVAL_SECONDS[self.interval]

    @property
    def range_bps(self) -> Decimal:
        """High to low, in basis points of the open.

        The single most useful number for the question this project spent two
        days on from the wrong end: how much movement an interval contains. A
        candle whose range is smaller than the round-trip cost held nothing to
        take, whatever a signal said about it.
        """
        if self.open <= 0:
            return Decimal(0)
        return (self.high - self.low) / self.open * Decimal(10000)

    @property
    def change_bps(self) -> Decimal:
        """Open to close, signed. What a position held for the whole candle made."""
        if self.open <= 0:
            return Decimal(0)
        return (self.close - self.open) / self.open * Decimal(10000)


def closed_only(candles: Sequence[Candle], *, now: datetime) -> tuple[Candle, ...]:
    """Drop any candle whose interval has not finished.

    Separated from fetching so it can be tested without a network, and so the
    rule is stated in one place: a candle is usable when its close time has
    passed. Everything else is a number still being written.
    """
    return tuple(candle for candle in candles if candle.close_time <= now)


@dataclass(frozen=True, slots=True)
class CandleRequest:
    """What history to download. Validated on construction.

    A dataclass rather than four parameters, because the four travel together
    through the fetch, the pagination and the store, and a call site that can
    pass them in the wrong order eventually does.
    """

    asset: str
    interval: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.interval not in INTERVAL_SECONDS:
            raise CandleError(
                f"unknown interval {self.interval!r}; this project uses "
                f"{', '.join(sorted(INTERVAL_SECONDS))}"
            )
        if self.end <= self.start:
            raise CandleError("the range end must be after its start")

    @property
    def step(self) -> timedelta:
        return timedelta(seconds=INTERVAL_SECONDS[self.interval])
