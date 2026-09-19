"""Turning a chart reading into LONG, SHORT or nothing.

`features.py` describes. This decides. The split is deliberate: a description
can be tested for correctness, a decision can only be tested for
profitability, and code that does both at once can be tested for neither.

Phase 1 §3 lists the position-level decisions as LONG, SHORT, HOLD, REDUCE and
CLOSE. This module emits a **target position** instead — LONG, SHORT or FLAT —
which expresses the same set more simply: HOLD is a target equal to the current
position, CLOSE is a target of FLAT, and REDUCE needs position sizing, which
belongs to the Risk Engine (Phase 6) rather than to a rule. A rule that sized
its own positions would be a rule that could bypass the risk layer.

**FLAT is a real answer.** Phase 1 §1 requires that NO TRADE be available as a
valid and potentially optimal decision, and the product objective names it
explicitly. A rule that is always either long or short has no way to say the
market is not worth trading, and in a market that ranges roughly half the time
that is most of what there is to say.

**The controls are part of this module, not an afterthought.** A candidate's
return means nothing on its own. It has to be compared against holding the
asset, against the same decisions in a different order, and against not trading
at all — and putting those in the same file as the candidate makes it awkward
to report the candidate without them.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Final, Protocol

from services.strategy_engine.features import FeatureSet, TrendRegime, VolatilityRegime


class Decision(StrEnum):
    """The position a rule wants to hold from now until it says otherwise."""

    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"

    @property
    def sign(self) -> int:
        if self is Decision.LONG:
            return 1
        if self is Decision.SHORT:
            return -1
        return 0


class Rule(Protocol):
    """What the backtester requires of a decision rule.

    One feature set in, one target position out. No access to the series, no
    knowledge of its own past performance, and no way to size a position. A
    rule that cannot see the future cannot use it, and a rule that cannot see
    its own equity curve cannot quietly fit itself to the test period.
    """

    name: str

    def decide(self, features: FeatureSet) -> Decision:
        """Choose a target position from this reading of the chart."""
        ...


STRETCH_LIMIT_BPS: Final = Decimal(300)
"""How far above the trend a trend-following rule will still buy.

Three percent. Buying something already far extended from its own average is
how a trend rule buys the top, and the defence is a limit rather than a
prediction. Conventional rather than fitted: it is the sort of number a trader
would say out loud, and it has not been searched for on this data.
"""


@dataclass(slots=True)
class TrendFollowing:
    """Long an uptrend, short a downtrend, flat in a range.

    The most conventional rule there is, chosen for exactly that reason. It is
    the null hypothesis of technical trading: if a trend rule with textbook
    parameters shows nothing on two years of two assets, that is informative,
    and if it shows something it was not arrived at by searching.

    The one refinement is the stretch limit — it will not enter a trend that
    has already run far from its own average — because entering late is the
    documented failure of this family and a rule that ignores it is a straw
    man.
    """

    name: str = "trend-following"
    stretch_limit_bps: Decimal = STRETCH_LIMIT_BPS

    def decide(self, features: FeatureSet) -> Decision:
        if features.trend_regime is TrendRegime.UP:
            if features.distance_from_trend_bps > self.stretch_limit_bps:
                return Decision.FLAT
            return Decision.LONG
        if features.trend_regime is TrendRegime.DOWN:
            if features.distance_from_trend_bps < -self.stretch_limit_bps:
                return Decision.FLAT
            return Decision.SHORT
        return Decision.FLAT


@dataclass(slots=True)
class TrendFollowingCalm:
    """The same rule, but only when volatility is not elevated.

    A comparison, not a second candidate. It asks one question — does avoiding
    the loud periods help — and it is the kind of question that must be asked
    on the training period only. Every rule evaluated against the held-out
    period spends some of that period's ability to surprise us.
    """

    name: str = "trend-following-calm"
    inner: TrendFollowing = field(default_factory=TrendFollowing)

    def decide(self, features: FeatureSet) -> Decision:
        if features.volatility_regime is VolatilityRegime.HIGH:
            return Decision.FLAT
        return self.inner.decide(features)


@dataclass(slots=True)
class BuyAndHold:
    """The control that matters most.

    A strategy that made money over the last two years of crypto has not
    demonstrated anything until it is compared with having bought and waited.
    Most rules lose to this, and a report that omits it is not a report.
    """

    name: str = "control-buy-and-hold"

    def decide(self, features: FeatureSet) -> Decision:  # noqa: ARG002 - by design
        return Decision.LONG


@dataclass(slots=True)
class AlwaysFlat:
    """The control that proves the harness is not inventing trades.

    If this one shows any profit or loss at all, something is wrong with the
    backtester and every other number in the run is suspect.
    """

    name: str = "control-always-flat"

    def decide(self, features: FeatureSet) -> Decision:  # noqa: ARG002 - by design
        return Decision.FLAT


@dataclass(slots=True)
class Shuffled:
    """A candidate's own decisions, in a different order.

    The sharpest control available here, and the reason it is worth more than
    random entry: it holds the *mix* of decisions fixed — the same number of
    longs, shorts and flats, so the same rough trade count and the same fee
    bill — and destroys only the information about *when*. If the candidate
    cannot beat its own shuffled self, its timing carried nothing, and the
    return came from the market's direction rather than from the rule.

    Seeded, so a reported comparison can be reproduced exactly. Run many times
    with different seeds, the shuffles give a distribution, and the candidate's
    position within it is a statement about significance rather than a story.
    """

    decisions: Sequence[Decision]
    seed: int
    name: str = "control-shuffled"
    _index: int = 0
    _order: list[Decision] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._order = list(self.decisions)
        # A seeded Mersenne Twister, deliberately. Reproducibility is the
        # requirement here and unpredictability is not: a control whose order
        # cannot be regenerated is a control whose result cannot be checked.
        random.Random(self.seed).shuffle(self._order)  # noqa: S311
        self.name = f"control-shuffled-{self.seed}"

    def decide(self, features: FeatureSet) -> Decision:  # noqa: ARG002 - by design
        """Return the next decision in the shuffled order.

        Stateful, unlike every other rule here, and it has to be: the whole
        point is to replay a fixed multiset in an order that carries no
        information. It is called exactly once per candle by the engine, in
        order, which is what makes the index meaningful.
        """
        if self._index >= len(self._order):
            return Decision.FLAT
        chosen = self._order[self._index]
        self._index += 1
        return chosen


DEFAULT_CONFIRMATION: Final = 2
"""Candles a new target must persist for before it is acted on.

Two, which is the smallest value that does anything at all. A larger number
would be a parameter to search, and the point of this wrapper is a structural
fix rather than a tuned one.
"""


@dataclass(slots=True)
class Confirmed:
    """Act on a change of mind only after it has held for a few candles.

    **Why this exists, stated before its result was looked at.** The regime
    labels in `features.py` are thresholds on continuous quantities, so near a
    threshold they flip back and forth on movement that carries no information.
    Each flip is a position change, each position change costs a round trip,
    and the first evaluation on SOL 4h showed the consequence exactly: the
    signal earned 9.3 bps of gross profit per trade against 9.98 bps of cost,
    so 150 trades converted a real edge into a net loss of 0.1%.

    The hypothesis this tests is falsifiable and the prediction is recorded
    here: requiring confirmation should cut the trade count and the fee bill
    while leaving gross profit *per trade* roughly unchanged, which would turn
    the net positive. If gross per trade falls by as much as the count does,
    the trades it removed were carrying information and this wrapper is wrong.

    It is not a tuning knob dressed up as a fix. It changes *when* a decision
    is acted on and never *what* the underlying rule thinks, so a rule whose
    signal is real keeps it and a rule whose signal is noise loses nothing
    worth keeping.
    """

    inner: Rule
    confirm: int = DEFAULT_CONFIRMATION
    name: str = ""
    _held: Decision = Decision.FLAT
    _pending: Decision | None = None
    _count: int = 0

    def __post_init__(self) -> None:
        if self.confirm < 1:
            raise ValueError("confirmation must span at least one candle")
        self.name = f"{self.inner.name}-confirmed-{self.confirm}"

    def decide(self, features: FeatureSet) -> Decision:
        wanted = self.inner.decide(features)
        if wanted is self._held:
            # The underlying rule agrees with the position already held, so
            # there is nothing to confirm and any half-built case is dropped.
            self._pending = None
            self._count = 0
            return self._held
        if wanted is self._pending:
            self._count += 1
        else:
            self._pending = wanted
            self._count = 1
        if self._count >= self.confirm:
            self._held = wanted
            self._pending = None
            self._count = 0
        return self._held


@dataclass(slots=True)
class LongWhenActive:
    """The candidate's own market timing, with its direction calls removed.

    **Why this control had to exist.** Over six years of crypto, `Shuffled`
    said 0 of 200 random orderings matched a rule that lost 10%. Both
    statements were true: shuffling separates a long-biased rule's direction
    from a market that rose 55%, so the shuffles lost even more. The control
    was measuring drift capture, not timing, and nothing in the report said so.

    This one holds the exposure fixed and drops the direction. It is LONG
    whenever the candidate wanted a position of either sign, and FLAT whenever
    the candidate wanted none — same trades, same fee bill, same time in the
    market, no opinion about which way. A candidate that cannot beat it has
    short calls worth nothing, and its return came from being in a rising
    market at roughly the right times.

    Stateful and replay-ordered, like `Shuffled`, and for the same reason: it
    is replaying a fixed sequence the candidate already produced.
    """

    decisions: Sequence[Decision]
    name: str = "control-long-when-active"
    _index: int = 0

    def decide(self, features: FeatureSet) -> Decision:  # noqa: ARG002 - by design
        if self._index >= len(self.decisions):
            return Decision.FLAT
        wanted = self.decisions[self._index]
        self._index += 1
        return Decision.FLAT if wanted is Decision.FLAT else Decision.LONG


REVERSION_ENTRY_BPS: Final = Decimal(200)
"""How far from its own average price must be before reversion is expected.

Two percent, conventional and not searched for on this data. A smaller
threshold trades constantly on noise; a larger one waits for moves that rarely
come. The rule below is the next hypothesis family rather than a tuned version
of the last one, so its parameters are declared once and left alone.
"""


@dataclass(slots=True)
class MeanReversion:
    """Buy what has fallen far below its average, sell what has risen far above.

    The opposite hypothesis to trend-following, and it is worth testing for a
    reason the data supplied rather than for symmetry: on daily candles the
    trend rule's gross profit per trade was deeply negative, -26 to -312 bps
    — which is not a weak signal but an inverted one. A signal that is
    reliably wrong is a signal.

    It only acts in a range. In a trend, "far from the average" is where price
    is supposed to be, and betting against it is how a reversion rule loses
    everything in one move. So RANGE is required, which also means this rule
    and the trend rule are never both in the market, and the two together
    cover the regimes neither covers alone.

    The null hypothesis stays what it was: this loses money net of cost, and
    less than buy-and-hold earns.
    """

    name: str = "mean-reversion"
    entry_bps: Decimal = REVERSION_ENTRY_BPS

    def decide(self, features: FeatureSet) -> Decision:
        if features.trend_regime is not TrendRegime.RANGE:
            return Decision.FLAT
        if features.distance_from_trend_bps <= -self.entry_bps:
            return Decision.LONG
        if features.distance_from_trend_bps >= self.entry_bps:
            return Decision.SHORT
        return Decision.FLAT


FUNDING_CROWDED: Final = Decimal("0.90")
FUNDING_DESERTED: Final = Decimal("0.10")
"""Which percentiles count as crowded and deserted.

The top and bottom tenth of the last thirty days. Conventional bounds for "an
extreme", chosen before any result was seen and not revisited: the whole
argument for this rule is that its mechanism is real, and a threshold tuned
until the backtest smiled would replace that argument with a fitted number.
"""


@dataclass(slots=True)
class FundingExtreme:
    """Fade the crowded side.

    The first rule here whose input is not a transformation of price. Funding
    is what the long and short sides are paying each other to hold their
    positions, so a rate in the top tenth of its own month means longs are
    paying unusually hard to stay long — the position is crowded, and a crowded
    position is what gets liquidated when price moves against it.

    So this goes SHORT into crowded longs and LONG into crowded shorts. It is
    contrarian by mechanism rather than by taste, and the mechanism is why it
    is worth testing at all: unlike RSI or MACD it is not a statistic everyone
    computes from the same public candles, so it is not priced in by
    construction.

    **It refuses to act on a missing feed.** `funding_percentile` is None when
    no funding series was supplied or when too few payments have settled to
    form a percentile. None is not neutral and must not be read as 0.5: a
    missing feed would otherwise be indistinguishable from average positioning,
    and the rule would trade on nothing.

    The null hypothesis is unchanged: this loses money net of cost, and less
    than buy-and-hold earns. That is what the six-year test is for.
    """

    name: str = "funding-extreme"
    crowded: Decimal = FUNDING_CROWDED
    deserted: Decimal = FUNDING_DESERTED

    def __post_init__(self) -> None:
        if not Decimal(0) <= self.deserted < self.crowded <= Decimal(1):
            raise ValueError("thresholds must satisfy 0 <= deserted < crowded <= 1")

    def decide(self, features: FeatureSet) -> Decision:
        percentile = features.funding_percentile
        if percentile is None:
            return Decision.FLAT
        if percentile >= self.crowded:
            return Decision.SHORT
        if percentile <= self.deserted:
            return Decision.LONG
        return Decision.FLAT


@dataclass(slots=True)
class FundingWithTrend:
    """Trade the trend, but stand aside when the trend's own side is crowded.

    Not a third hypothesis — a test of whether funding adds anything to a rule
    that already failed. The trend family returned NO_EDGE_FOUND over six
    years; if positioning carries information that price does not, then
    refusing the trades where the crowd is already maximally committed should
    improve it, and if it does not, funding has nothing to add to this signal.

    Stated that way on purpose: this is a question with a clear negative
    answer available, which is what makes it worth asking.
    """

    name: str = "funding-with-trend"
    inner: Rule = field(default_factory=TrendFollowing)
    crowded: Decimal = FUNDING_CROWDED
    deserted: Decimal = FUNDING_DESERTED

    def decide(self, features: FeatureSet) -> Decision:
        wanted = self.inner.decide(features)
        percentile = features.funding_percentile
        if percentile is None or wanted is Decision.FLAT:
            return wanted
        if wanted is Decision.LONG and percentile >= self.crowded:
            return Decision.FLAT
        if wanted is Decision.SHORT and percentile <= self.deserted:
            return Decision.FLAT
        return wanted
