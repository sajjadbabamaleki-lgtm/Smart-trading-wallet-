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
