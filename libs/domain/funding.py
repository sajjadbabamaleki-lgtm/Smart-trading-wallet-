"""Funding rates, and how to ask about them without reading the future.

A perpetual future has no expiry, so it is tied to spot by a payment between
the two sides: when more capital is long than short, longs pay shorts, and the
rate is how much. That makes it the one number in this project that is not a
transformation of price. It is **positioning** — what traders have actually
committed, in money, right now — and unlike RSI or MACD it is not a statistic
everyone computes from the same public series and therefore already prices in.

The hypothesis it supports is structural rather than fitted: funding far above
its own normal means the long side is crowded and paying to stay there, and a
crowded side is the one that gets liquidated when price moves against it. High
funding is therefore a reason to be cautious about longs, not a reason to join
them.

**Point-in-time is enforced by the query, not by discipline.** `percentile_at`
takes the moment being decided and looks only at payments at or before it. A
funding percentile computed over a window that includes tomorrow's payments is
a number nobody could have had, and it is the easiest lookahead to introduce
here because the series is short enough to be tempting to handle as an array.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

BPS: Final = Decimal(10000)

DEFAULT_PERCENTILE_WINDOW: Final = timedelta(days=30)
"""How much history a funding reading is judged against.

Thirty days. Long enough that one crowded weekend does not become the new
normal, short enough that a percentile still describes the current regime
rather than the last two years. Conventional rather than searched for.
"""

MINIMUM_SAMPLE: Final = 20
"""Payments needed before a percentile is reported at all.

A percentile over five observations is a number with a decimal point and no
information. Below this the reading is None, which callers must handle, rather
than a confident value computed from nothing.
"""


class FundingError(RuntimeError):
    """A funding series this module will not interpret."""


@dataclass(frozen=True, slots=True)
class FundingRate:
    """One settled funding payment, as the venue reported it."""

    asset: str
    moment: datetime
    rate: Decimal
    """The fraction paid, per settlement. 0.0001 is one basis point."""

    mark_price: Decimal | None = None

    @property
    def rate_bps(self) -> Decimal:
        return self.rate * BPS

    @property
    def annualised_pct(self) -> Decimal:
        """The rate as a yearly percentage, at three settlements a day.

        The figure a person can judge: 0.01% per eight hours is about 11% a
        year, which is a real cost of carry rather than a rounding error. The
        three-a-day assumption is Binance's historical schedule and some
        symbols have moved to other intervals, so this is an approximation and
        is used for display only — never in a decision.
        """
        return self.rate * Decimal(3) * Decimal(365) * Decimal(100)


@dataclass(frozen=True, slots=True)
class FundingHistory:
    """A funding series that can only be asked about its own past.

    Built once per asset and queried per candle. The moments are kept sorted so
    a point-in-time cut is a bisect rather than a scan, which is what makes a
    six-year backtest affordable.
    """

    asset: str
    moments: tuple[datetime, ...]
    rates: tuple[Decimal, ...]

    def __post_init__(self) -> None:
        if len(self.moments) != len(self.rates):
            raise FundingError("a funding history needs one rate per moment")
        if any(
            later < earlier for earlier, later in zip(self.moments, self.moments[1:], strict=False)
        ):
            raise FundingError(
                "funding moments are not in time order; a point-in-time cut over "
                "an unsorted series silently includes the future"
            )

    @classmethod
    def build(cls, rates: Sequence[FundingRate]) -> FundingHistory:
        """From records in any order, sorted here so callers cannot forget to."""
        if not rates:
            raise FundingError("cannot build a funding history from no payments")
        ordered = sorted(rates, key=lambda entry: entry.moment)
        return cls(
            asset=ordered[0].asset,
            moments=tuple(entry.moment for entry in ordered),
            rates=tuple(entry.rate for entry in ordered),
        )

    def _cut(self, moment: datetime) -> int:
        """How many payments had settled at or before `moment`."""
        return bisect.bisect_right(self.moments, moment)

    def latest_at(self, moment: datetime) -> Decimal | None:
        """The most recent payment known at `moment`, or None before the first."""
        index = self._cut(moment)
        if index == 0:
            return None
        return self.rates[index - 1]

    def settlements_between(self, start: datetime, end: datetime) -> tuple[Decimal, ...]:
        """Payments that settled after `start` and at or before `end`.

        Half-open at the start so consecutive candles neither double-charge a
        settlement nor drop one: candle N covers (close of N-1, close of N].
        A position held across a boundary pays at that boundary exactly once.
        """
        first = bisect.bisect_right(self.moments, start)
        last = bisect.bisect_right(self.moments, end)
        return self.rates[first:last]

    def percentile_at(
        self,
        moment: datetime,
        *,
        window: timedelta = DEFAULT_PERCENTILE_WINDOW,
        minimum: int = MINIMUM_SAMPLE,
    ) -> Decimal | None:
        """Where the latest known rate sits in its own recent range, 0 to 1.

        1 means the highest funding of the window — the long side paying more
        than at any point in the last month. 0 means the lowest.

        None when fewer than `minimum` payments are available, because a
        percentile over a handful of observations reads like a measurement and
        is not one.
        """
        end = self._cut(moment)
        if end == 0:
            return None
        start = bisect.bisect_left(self.moments, moment - window, hi=end)
        sample = self.rates[start:end]
        if len(sample) < minimum:
            return None
        current = sample[-1]
        below = sum(1 for rate in sample if rate < current)
        equal = sum(1 for rate in sample if rate == current)
        # Mid-rank for ties, so a flat stretch of identical rates sits in the
        # middle rather than being reported as an extreme by accident.
        return (Decimal(below) + Decimal(equal) / 2) / Decimal(len(sample))
