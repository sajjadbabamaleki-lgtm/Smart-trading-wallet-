"""Transaction costs for BTC perpetuals on Hyperliquid (M5).

Build 0.1 Rev.2 §25 is unambiguous: every serious experiment must account for
fees, spread, slippage, funding and execution delay, and

    a strategy profitable before costs but unprofitable afterward has no
    demonstrated trading edge.

So this module exists before any strategy does. Its job is to produce the
number a signal has to beat, and to make that number hard to flatter.

Three rules shape it.

**The pessimistic path is the default.** Taker fees, not maker; the base fee
tier, not a volume discount; the full spread crossed, not the midpoint. Every
one of those can be improved, and every improvement has to be *earned* and
passed in explicitly. A cost model whose defaults are the best case will
approve strategies that do not exist.

**Costs are per round trip.** A position is opened and closed, so the fee is
paid twice and the spread is crossed twice. Quoting a one-way cost is the
commonest way to make an edge look twice as large as it is.

**Latency is a cost, not a caveat.** The M2 acceptance run measured a data
arrival floor near 300 ms that is neither our clock nor our network — it is how
long Hyperliquid takes to publish an event to subscribers. A decision made on
an event is acted on at least that long after the event happened, and the
market moves in between. That drift is charged here rather than mentioned in a
footnote.

Sources for the constants are cited at each one. They are venue policy, not
model parameters, and they change without asking us.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

BPS: Final = Decimal(10000)
"""One basis point is 1/10000. Rates below are in basis points throughout."""

BASE_TAKER_FEE_BPS: Final = Decimal("4.5")
"""Hyperliquid perpetual taker fee, base tier: 0.045%.

The base tier is every wallet under $5M of 14-day rolling volume, which is
where this project is and will remain for a long time. Lower tiers exist and
reach 2.4 bps taker, but a discount that depends on volume the system does not
do is not a cost saving — it is an assumption.
"""

BASE_MAKER_FEE_BPS: Final = Decimal("1.5")
"""Hyperliquid perpetual maker fee, base tier: 0.015%.

Present for completeness and deliberately not the default. A maker order is a
request, not a fill: modelling maker economics means modelling the fills that
never happen, and a backtest that assumes its passive orders filled is
measuring a strategy nobody can run.
"""

FUNDING_INTERVAL_HOURS: Final = 1
"""Hyperliquid settles funding hourly, at 1/8 of the 8-hour rate.

The consequence that matters for a short-horizon strategy: a position opened
and closed inside the same hour pays no funding at all, while one held across
the boundary pays the full hourly amount on its size at the snapshot. That is a
step function, not a proportional cost, and averaging it would misprice exactly
the strategies this project is likely to test first.
"""

MAX_FUNDING_RATE_PER_HOUR_BPS: Final = Decimal(400)
"""Hyperliquid caps funding at 4% per hour.

A bound, not an expectation. It is here so that a stress scenario has a
defensible worst case rather than an invented one.
"""

MEASURED_DATA_ARRIVAL_FLOOR_MS: Final = Decimal(322)
"""Median data arrival latency measured against the live venue, 2026-09-14.

`local_receipt - venue_event_timestamp` over 5725 BBO observations from a
Contabo VPS in Europe. Established as neither clock offset nor network
transport: TCP connect to the venue was 56.95 ms and the host clock was
NTP-synchronised with 274 microseconds of root dispersion. It is the interval
between Hyperliquid stamping an event and publishing it, and therefore the
floor for any consumer of the public feed.

Recorded here because it is the first term in any honest decision-to-fill
delay, and because a research assumption of "50 ms" would be contradicted by
this project's own evidence.
"""


@dataclass(frozen=True, slots=True)
class CostModel:
    """What one round trip costs, in basis points of notional.

    Every field is a cost the venue or the market imposes. None of them is a
    parameter to be fitted: a model that tunes its own costs until a strategy
    passes has stopped being a cost model.
    """

    taker_fee_bps: Decimal = BASE_TAKER_FEE_BPS
    half_spread_bps: Decimal = Decimal("0.5")
    """Half the quoted spread, charged per side.

    Crossing to trade costs the distance from mid to the touch. The default is
    deliberately small — BTC perpetual spreads on Hyperliquid are typically
    around a tick — because an inflated default would hide a real edge, while
    an inflated *fee* would only hide a fake one. Measure it from the recorded
    BBO stream rather than accepting this.
    """

    slippage_bps: Decimal = Decimal("0.0")
    """Price impact beyond the touch, from consuming depth.

    Zero by default and that default is a claim, not a convenience: it is only
    true while order size stays inside the top level. A strategy trading size
    must replace this with a figure derived from the recorded L2 book, and the
    only honest way to get one is to measure it.
    """

    adverse_drift_bps: Decimal = Decimal("0.0")
    """Expected adverse price move between deciding and filling.

    The market does not wait. Over the measured arrival floor plus our own
    processing and transmission, price moves, and it moves against the decision
    more often than for it — the trades a stale signal still wants are
    disproportionately the ones the market has already left behind.

    Zero by default only because it must be measured from the recorded data
    rather than assumed, and `hurdle_bps` will say so when it is still zero.
    """

    def __post_init__(self) -> None:
        for name in (
            "taker_fee_bps",
            "half_spread_bps",
            "slippage_bps",
            "adverse_drift_bps",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative; a cost is not a rebate")

    @property
    def fee_only_bps(self) -> Decimal:
        """The fee alone, for a caller that already pays the spread in its price.

        The event-driven backtester fills at the touch, so crossing is in the
        fill price; adding `half_spread_bps` there would charge it twice and
        overstate the cost of a round trip by roughly a factor of two. This
        exists so that choice is explicit at the call site rather than an
        omission someone later "fixes".
        """
        return self.taker_fee_bps + self.slippage_bps

    @property
    def one_way_bps(self) -> Decimal:
        """Cost of getting into, or out of, a position once."""
        return self.taker_fee_bps + self.half_spread_bps + self.slippage_bps

    @property
    def round_trip_bps(self) -> Decimal:
        """Cost of a complete trade: in and out.

        Adverse drift is charged once rather than twice. It is the cost of
        acting on stale information at the moment of decision, and a round trip
        has one decision that matters — the entry. An exit driven by its own
        signal is a second decision and a second round trip.
        """
        return self.one_way_bps * 2 + self.adverse_drift_bps

    def round_trip_cost(self, notional: Decimal) -> Decimal:
        """Cost of a round trip on this notional, in quote currency."""
        if notional < 0:
            raise ValueError("notional cannot be negative")
        return notional * self.round_trip_bps / BPS

    def funding_cost(
        self, notional: Decimal, *, hourly_rate_bps: Decimal, hours_held_across_boundary: int
    ) -> Decimal:
        """Funding paid over a holding period.

        `hours_held_across_boundary` is the number of hourly snapshots the
        position was open for, not its duration: Hyperliquid charges at the
        boundary, so a 59-minute position that avoids one pays nothing and a
        2-minute position that straddles one pays in full. Callers that pass a
        duration here will understate the cost of short holds and overstate the
        cost of long ones.

        The sign is the caller's: a long paying a positive funding rate has a
        cost, and the same long receives when the rate is negative.
        """
        if hours_held_across_boundary < 0:
            raise ValueError("hours cannot be negative")
        if abs(hourly_rate_bps) > MAX_FUNDING_RATE_PER_HOUR_BPS:
            raise ValueError(
                f"hourly funding of {hourly_rate_bps} bps exceeds the venue cap of "
                f"{MAX_FUNDING_RATE_PER_HOUR_BPS} bps; check the units"
            )
        return notional * hourly_rate_bps / BPS * hours_held_across_boundary


@dataclass(frozen=True, slots=True)
class Hurdle:
    """What a signal must predict before it is worth acting on."""

    round_trip_bps: Decimal
    model: CostModel

    @property
    def is_fully_measured(self) -> bool:
        """Whether every term came from data rather than from a default.

        Slippage and adverse drift default to zero, which is the optimistic
        assumption in both cases. A hurdle computed with either still at zero is
        a lower bound on the real one, and must be reported as such.
        """
        return self.model.slippage_bps > 0 and self.model.adverse_drift_bps > 0

    def required_move(self, price: Decimal) -> Decimal:
        """The price move a round trip must capture just to break even."""
        return price * self.round_trip_bps / BPS

    def describe(self, price: Decimal) -> dict[str, object]:
        """A statement a research note can quote without re-deriving it."""
        return {
            "round_trip_bps": str(self.round_trip_bps),
            "break_even_move": str(self.required_move(price)),
            "reference_price": str(price),
            "fully_measured": self.is_fully_measured,
            "components_bps": {
                "taker_fee_each_way": str(self.model.taker_fee_bps),
                "half_spread_each_way": str(self.model.half_spread_bps),
                "slippage_each_way": str(self.model.slippage_bps),
                "adverse_drift_once": str(self.model.adverse_drift_bps),
            },
        }


def hurdle(model: CostModel | None = None) -> Hurdle:
    """The break-even threshold implied by a cost model.

    With the defaults this is 10 bps: 4.5 taker plus 0.5 half-spread, twice.
    On BTC at 60,000 that is a required move of 60 units per round trip, and a
    signal that cannot predict more than that has no edge regardless of how
    well it predicts direction. Stating it in those terms early is the point of
    doing this before the strategy rather than after.
    """
    resolved = model or CostModel()
    return Hurdle(round_trip_bps=resolved.round_trip_bps, model=resolved)
