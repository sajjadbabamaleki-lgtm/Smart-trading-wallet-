"""Measuring cost-model inputs from recorded data (M5).

`costs.CostModel` ships with slippage and adverse drift at zero, and
`Hurdle.is_fully_measured` reports false until they are not. This module is how
they stop being zero — from the events the recorder actually captured, never
from a plausible-looking constant.

What it measures, and what it refuses to.

**Half-spread is measurable and is measured here.** It is the distance from mid
to the touch, which is what crossing costs, and the BBO stream contains it
directly. Reported as a distribution, because a mean spread is the one number
that describes no moment of the day: spreads widen exactly when a strategy most
wants to trade.

**Mid movement over a delay is measurable and is measured here.** Given the
~322 ms arrival floor this project measured against the live venue, price has
already moved by the time any decision can act. The size of that movement is
the scale of the problem, and it comes from the recorded BBO series.

**Adverse drift is not measured here, and that is deliberate.** It looks like it
belongs next to the other two, but it is not a property of the market — it is
the overlap between a signal and the delay, and it cannot be computed without
the signal. If price moves the way a signal predicted during the delay, the
edge was consumed before the order arrived; if it moves the other way, the trade
got a better price. The same market data produces a different adverse drift for
every strategy, so a constant here would be a number that flatters some
strategies and slanders others while looking authoritative. It belongs in the
backtester, against a specific signal, which is M6.

`mid_move_bps` is what M6 will need to do that. It is offered as the input to
the question, not as its answer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

QUANTILES: tuple[float, ...] = (0.5, 0.9, 0.95, 0.99)


class MeasurementError(ValueError):
    """Not enough data, or the wrong kind, to measure what was asked."""


@dataclass(frozen=True, slots=True)
class Distribution:
    """A measured quantity, described by its shape rather than its average.

    An average spread or an average price move is the number least likely to
    describe the moment a strategy trades. Trading systems fail in the tail, so
    the tail is what is carried.
    """

    count: int
    p50: Decimal
    p90: Decimal
    p95: Decimal
    p99: Decimal
    maximum: Decimal

    def as_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "p50": str(self.p50),
            "p90": str(self.p90),
            "p95": str(self.p95),
            "p99": str(self.p99),
            "max": str(self.maximum),
        }


def _quantile(ordered: Sequence[Decimal], fraction: float) -> Decimal:
    """Nearest-rank quantile over an already-sorted sample.

    Nearest-rank rather than interpolated: every value returned is one that was
    actually observed. An interpolated p99 is a number the market never printed,
    which is the wrong kind of figure to put in a cost model.
    """
    if not ordered:
        raise MeasurementError("cannot take a quantile of an empty sample")
    rank = max(1, min(len(ordered), round(fraction * len(ordered) + 0.5)))
    return ordered[rank - 1]


def _summarise(values: list[Decimal]) -> Distribution:
    if not values:
        raise MeasurementError("no observations")
    values.sort()
    return Distribution(
        count=len(values),
        p50=_quantile(values, 0.5),
        p90=_quantile(values, 0.9),
        p95=_quantile(values, 0.95),
        p99=_quantile(values, 0.99),
        maximum=values[-1],
    )


def _quotes(rows: Sequence[dict[str, Any]]) -> list[tuple[datetime, Decimal, Decimal]]:
    """Two-sided quotes, in receipt order.

    One-sided quotes are skipped rather than filled in. A book with no bid has
    no mid and no spread, and inventing one would put a fabricated number into
    a cost model — the precise failure this whole layer exists to prevent.
    """
    quotes: list[tuple[datetime, Decimal, Decimal]] = []
    for row in rows:
        bid, ask = row.get("bid_price"), row.get("ask_price")
        received = row.get("local_receive_time")
        if not isinstance(bid, Decimal) or not isinstance(ask, Decimal):
            continue
        if not isinstance(received, datetime) or bid <= 0 or ask <= 0:
            continue
        if ask < bid:
            # A crossed book is a data defect, not a negative spread to average.
            continue
        quotes.append((received, bid, ask))
    quotes.sort(key=lambda quote: quote[0])
    return quotes


def measure_half_spread_bps(rows: Sequence[dict[str, Any]]) -> Distribution:
    """Half the quoted spread, in basis points of mid.

    Half, because crossing to trade costs the distance from mid to the touch,
    and that is what `CostModel.half_spread_bps` charges per side.
    """
    quotes = _quotes(rows)
    if not quotes:
        raise MeasurementError(
            "no two-sided quotes in the sample; a spread cannot be measured from "
            "trades alone — include BBO or L2_SNAPSHOT rows"
        )
    observations = [(ask - bid) / 2 / ((ask + bid) / 2) * Decimal(10000) for _, bid, ask in quotes]
    return _summarise(observations)


def measure_mid_move_bps(rows: Sequence[dict[str, Any]], *, delay: timedelta) -> Distribution:
    """How far mid moves over `delay`, in basis points, unsigned.

    Unsigned on purpose. Direction is only meaningful relative to a position,
    and there is no position here — this measures the *scale* of what happens
    while a decision is in flight. Whether that movement helps or hurts is the
    question M6 asks against a signal.

    Paired by walking forward to the first quote at least `delay` later, so a
    gap in the stream produces no observation rather than a silently stretched
    one.
    """
    if delay <= timedelta(0):
        raise MeasurementError("delay must be positive")

    quotes = _quotes(rows)
    observations: list[Decimal] = []
    later = 0
    for index, (moment, bid, ask) in enumerate(quotes):
        target = moment + delay
        later = max(later, index + 1)
        while later < len(quotes) and quotes[later][0] < target:
            later += 1
        if later >= len(quotes):
            break
        _, future_bid, future_ask = quotes[later]
        mid = (ask + bid) / 2
        future_mid = (future_ask + future_bid) / 2
        observations.append(abs(future_mid - mid) / mid * Decimal(10000))

    if not observations:
        raise MeasurementError(
            f"no quote pairs separated by {delay}; the sample is shorter than the delay "
            f"or too sparse to measure over it"
        )
    return _summarise(observations)


@dataclass(frozen=True, slots=True)
class Calibration:
    """What the recorded data says about the cost of trading it."""

    half_spread_bps: Distribution
    mid_move_bps: Distribution
    delay: timedelta
    sample_rows: int

    def as_dict(self) -> dict[str, object]:
        return {
            "sample_rows": self.sample_rows,
            "delay_ms": self.delay.total_seconds() * 1000,
            "half_spread_bps": self.half_spread_bps.as_dict(),
            "mid_move_over_delay_bps": self.mid_move_bps.as_dict(),
        }

    @property
    def headline(self) -> str:
        """The comparison that decides whether a horizon is worth testing.

        If mid moves further over the decision delay than a round trip costs,
        the delay is not a tax on the edge — it is larger than the edge has to
        be, and the horizon is unreachable from a public feed regardless of how
        good the signal is.
        """
        return (
            f"median half-spread {self.half_spread_bps.p50} bps; "
            f"median mid move over {self.delay.total_seconds() * 1000:.0f} ms "
            f"{self.mid_move_bps.p50} bps"
        )


def calibrate(rows: Sequence[dict[str, Any]], *, delay: timedelta) -> Calibration:
    """Measure both quantities over one sample."""
    return Calibration(
        half_spread_bps=measure_half_spread_bps(rows),
        mid_move_bps=measure_mid_move_bps(rows, delay=delay),
        delay=delay,
        sample_rows=len(rows),
    )
