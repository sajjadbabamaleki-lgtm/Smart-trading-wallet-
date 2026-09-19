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

**Adverse selection on a passive fill is a different quantity, and it *is*
measured here.** It is easy to confuse with adverse drift and is not the same
thing. Adverse drift asks what happened to *our signal* while our order was in
flight; adverse selection asks who chose to trade against a resting order, and
that is a property of the book rather than of any strategy. It needs no signal,
so it can be measured now — and it has to be, because it is the entire
difference between the two ways this system could execute. Crossing costs 4.5
bps a side in fees; resting costs 1.5. Whether resting is actually cheaper
depends on what the price does after someone chooses to fill you, and nothing
in this project had measured that.
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
        # An empty range and a range full of trades are different problems with
        # the same symptom, and saying "no two-sided quotes" about zero rows is
        # a true statement pointing at the wrong cause.
        if not rows:
            raise MeasurementError(
                "the sample is empty: no rows in the requested range. Widen it, or "
                "check that the recorder was running over that period"
            )
        raise MeasurementError(
            f"{len(rows)} rows in range but none carry both a bid and an ask; a "
            f"spread cannot be measured from trades alone — include BBO or "
            f"L2_SNAPSHOT rows"
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
    if not quotes:
        if not rows:
            raise MeasurementError(
                "the sample is empty: no rows in the requested range. Widen it, or "
                "check that the recorder was running over that period"
            )
        raise MeasurementError(
            f"{len(rows)} rows in range but none carry both a bid and an ask; mid "
            f"movement needs quotes"
        )
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
class SignedDistribution:
    """A quantity whose sign carries meaning, so the loss tail is kept.

    `Distribution` describes magnitudes and keeps the upper tail, which is right
    for a spread. A markout can go either way and the bad end is the low end, so
    this keeps both and reports the mean as well: for a cost input the average is
    what is actually paid over many fills, even though the average is the wrong
    summary for a risk limit.
    """

    count: int
    mean: Decimal
    p10: Decimal
    p25: Decimal
    p50: Decimal
    p75: Decimal
    p90: Decimal
    minimum: Decimal
    maximum: Decimal

    def as_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "mean": str(self.mean),
            "p10": str(self.p10),
            "p25": str(self.p25),
            "p50": str(self.p50),
            "p75": str(self.p75),
            "p90": str(self.p90),
            "min": str(self.minimum),
            "max": str(self.maximum),
        }


def _summarise_signed(values: list[Decimal]) -> SignedDistribution:
    if not values:
        raise MeasurementError("no observations")
    values.sort()
    total = sum(values, Decimal(0))
    return SignedDistribution(
        count=len(values),
        mean=(total / len(values)).quantize(Decimal("0.0001")),
        p10=_quantile(values, 0.10),
        p25=_quantile(values, 0.25),
        p50=_quantile(values, 0.50),
        p75=_quantile(values, 0.75),
        p90=_quantile(values, 0.90),
        minimum=values[0],
        maximum=values[-1],
    )


def _trades(rows: Sequence[dict[str, Any]]) -> list[tuple[datetime, Decimal, str]]:
    """Trades in receipt order, with the aggressor's side.

    A trade with no side cannot say who chose to trade, which is the whole
    question here, so it is skipped rather than guessed at.
    """
    trades: list[tuple[datetime, Decimal, str]] = []
    for row in rows:
        if str(row.get("event_type", "")).upper() != "TRADE":
            continue
        price, received, side = row.get("price"), row.get("local_receive_time"), row.get("side")
        if not isinstance(price, Decimal) or price <= 0:
            continue
        if not isinstance(received, datetime) or not isinstance(side, str):
            continue
        aggressor = side.strip().upper()
        if aggressor in {"B", "BUY"}:
            trades.append((received, price, "BUY"))
        elif aggressor in {"A", "S", "SELL"}:
            trades.append((received, price, "SELL"))
    trades.sort(key=lambda trade: trade[0])
    return trades


def measure_passive_fill_markout_bps(
    rows: Sequence[dict[str, Any]], *, horizon: timedelta
) -> SignedDistribution:
    """What happens to mid after a resting order would have been filled.

    Signed from the filled order's point of view: negative means the price moved
    against the fill, which is the cost of having been chosen to trade with.

    A resting buy sits at the bid and is filled by someone aggressively selling
    into it. So every recorded trade whose aggressor was a seller, at or below
    the prevailing bid, is treated as a fill of a passive buy at that bid; and
    symmetrically for a passive sell at the ask. The markout is then mid at
    `horizon` later against the fill price.

    Three limits, all of which make this an **optimistic** figure. It is a lower
    bound on adverse selection, and the number to beat rather than the number
    to bank.

    **Queue position is not modelled.** This assumes any aggressive trade at our
    level fills us. In a real book we are behind a queue and are filled
    disproportionately when the level is being cleared — which is exactly the
    adverse case. Real adverse selection is worse than this by an amount this
    data cannot bound.

    **The quote may be stale.** BBO arrives roughly every 1.4 s in the busy
    hours and slower overnight, so the prevailing quote used here can predate
    the trade by a second or more, and a trade may have executed against a book
    this recorder never saw.

    **Fees are not included.** This is the markout alone. The maker fee is added
    by the cost model, which is where the two belong together.
    """
    if horizon <= timedelta(0):
        raise MeasurementError("horizon must be positive")

    quotes = _quotes(rows)
    trades = _trades(rows)
    if not quotes or not trades:
        raise MeasurementError(
            f"need both quotes and trades: found {len(quotes)} two-sided quote(s) and "
            f"{len(trades)} trade(s). A passive fill cannot be located without both"
        )

    observations: list[Decimal] = []
    quote_index = 0
    for received, price, aggressor in trades:
        # Walk the quote series forward to the last quote at or before the trade.
        while quote_index + 1 < len(quotes) and quotes[quote_index + 1][0] <= received:
            quote_index += 1
        quote_at, bid, ask = quotes[quote_index]
        if quote_at > received:
            # The trade predates every quote we hold; there is no book to rest in.
            continue

        if aggressor == "SELL" and price <= bid:
            fill, direction = bid, Decimal(1)
        elif aggressor == "BUY" and price >= ask:
            fill, direction = ask, Decimal(-1)
        else:
            # Traded inside the spread, or against a level we were not at.
            continue

        future = _mid_at_or_after(quotes, quote_index, received + horizon)
        if future is None:
            continue
        observations.append(direction * (future - fill) / fill * Decimal(10000))

    if not observations:
        raise MeasurementError(
            f"no passive fill could be located in {len(trades)} trade(s) against "
            f"{len(quotes)} quote(s) with a quote {horizon} later; widen the range"
        )
    return _summarise_signed(observations)


def _mid_at_or_after(
    quotes: Sequence[tuple[datetime, Decimal, Decimal]], start: int, when: datetime
) -> Decimal | None:
    """Mid from the first quote at or after `when`, or None if the series ends.

    None rather than the last available quote: a gap in the stream must produce
    no observation instead of a markout silently measured over the wrong
    interval.
    """
    for index in range(start, len(quotes)):
        quote_at, bid, ask = quotes[index]
        if quote_at >= when:
            return (bid + ask) / 2
    return None


@dataclass(frozen=True, slots=True)
class Calibration:
    """What the recorded data says about the cost of trading it."""

    half_spread_bps: Distribution
    mid_move_bps: Distribution
    delay: timedelta
    sample_rows: int
    passive_markout_bps: SignedDistribution | None = None
    """Adverse selection on a resting fill, when quotes and trades both exist.

    Optional because the two other measurements need only quotes. A sample of
    BBO alone can still say what crossing costs; it cannot say anything about
    who would have chosen to trade with us.
    """

    markout_horizon: timedelta | None = None

    def as_dict(self) -> dict[str, object]:
        report: dict[str, object] = {
            "sample_rows": self.sample_rows,
            "delay_ms": self.delay.total_seconds() * 1000,
            "half_spread_bps": self.half_spread_bps.as_dict(),
            "mid_move_over_delay_bps": self.mid_move_bps.as_dict(),
        }
        if self.passive_markout_bps is not None and self.markout_horizon is not None:
            report["passive_fill_markout_bps"] = {
                "horizon_seconds": self.markout_horizon.total_seconds(),
                **self.passive_markout_bps.as_dict(),
            }
        return report

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


def calibrate(
    rows: Sequence[dict[str, Any]],
    *,
    delay: timedelta,
    markout_horizon: timedelta = timedelta(seconds=10),
) -> Calibration:
    """Measure what the sample supports, and say nothing about what it does not.

    The markout is attempted and allowed to fail: a sample with no trades, or
    none at the touch, cannot answer the passive question, and reporting a
    number from it would be worse than reporting none. The two quote-only
    measurements are required, because a sample that cannot support them is not
    a sample of market data.
    """
    markout: SignedDistribution | None
    try:
        markout = measure_passive_fill_markout_bps(rows, horizon=markout_horizon)
    except MeasurementError:
        markout = None

    return Calibration(
        half_spread_bps=measure_half_spread_bps(rows),
        mid_move_bps=measure_mid_move_bps(rows, delay=delay),
        delay=delay,
        sample_rows=len(rows),
        passive_markout_bps=markout,
        markout_horizon=markout_horizon if markout is not None else None,
    )
