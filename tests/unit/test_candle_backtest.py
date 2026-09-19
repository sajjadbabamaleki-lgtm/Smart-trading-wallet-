"""Backtesting on candles.

The test this file exists for is `test_a_decision_fills_at_the_next_open`.
Filling at the close of the candle you decided on is the commonest lookahead in
candle backtesting, it is nearly invisible in review, and it is the difference
between a result and a story.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from libs.exchange.hyperliquid.candles import Candle
from services.research.costs import CostModel
from services.strategy_engine.candle_backtest import (
    CandleBacktest,
    execution_pairs,
)
from services.strategy_engine.decisions import (
    AlwaysFlat,
    BuyAndHold,
    Confirmed,
    Decision,
    Shuffled,
    TrendFollowing,
)
from services.strategy_engine.features import (
    FeatureConfig,
    FeatureSet,
    TrendRegime,
    VolatilityRegime,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(hours=4)

# A short config so a test series does not need hundreds of candles.
SMALL = FeatureConfig(
    fast=2, slow=4, momentum=2, atr=2, volatility=2, volatility_reference=6, volume=2, swing=2
)

NO_COST = CostModel(taker_fee_bps=Decimal(0), half_spread_bps=Decimal(0))


def candle(index: int, *, open_: str, close: str) -> Candle:
    low = min(Decimal(open_), Decimal(close))
    high = max(Decimal(open_), Decimal(close))
    return Candle(
        asset="SOL",
        interval="4h",
        open_time=START + STEP * index,
        close_time=START + STEP * (index + 1),
        open=Decimal(open_),
        high=high * Decimal("1.001"),
        low=low * Decimal("0.999"),
        close=Decimal(close),
        volume=Decimal(1000),
        trades=100,
    )


def series(closes: list[str]) -> list[Candle]:
    """Candles whose open equals the previous close: no gaps to reason about."""
    built = []
    for index, close in enumerate(closes):
        opening = closes[index - 1] if index else close
        built.append(candle(index, open_=opening, close=close))
    return built


def rising(count: int, *, start: int = 100) -> list[Candle]:
    return series([str(start + index) for index in range(count)])


def gapped(count: int, *, start: int = 100) -> list[Candle]:
    """Rising, but every candle opens away from where the last one closed.

    Without a gap, `series` makes each open equal the previous close, so "the
    next candle's open" and "the candle we decided on closed at" are the same
    number — and a fill-timing test over that data passes whether the engine is
    right or wrong. The gap is what makes the assertion mean something.
    """
    built = []
    for index in range(count):
        close = start + index * 10
        opening = close + 5 if index else close
        built.append(candle(index, open_=str(opening), close=str(close)))
    return built


@dataclass(slots=True)
class OnceLong:
    """Goes long on the nth decision and stays flat otherwise."""

    at: int
    name: str = "once-long"
    seen: int = 0

    def decide(self, features: FeatureSet) -> Decision:  # noqa: ARG002 - by design
        self.seen += 1
        return Decision.LONG if self.seen == self.at else Decision.FLAT


class TestExecutionPairing:
    def test_a_reading_is_paired_with_the_following_candle(self) -> None:
        candles = rising(12)
        pairs = list(execution_pairs(candles, SMALL))
        reading, fill = pairs[0]
        source = next(c for c in candles if c.close_time == reading.moment)
        assert fill.open_time == source.close_time

    def test_the_last_reading_has_nowhere_to_execute_and_is_dropped(self) -> None:
        """A decision with no next candle is not a trade."""
        candles = rising(12)
        pairs = list(execution_pairs(candles, SMALL))
        assert pairs[-1][1] is candles[-1]
        assert pairs[-1][0].moment == candles[-2].close_time

    def test_a_series_too_short_to_decide_yields_nothing(self) -> None:
        assert list(execution_pairs(rising(SMALL.warmup), SMALL)) == []


class TestFillTiming:
    def test_a_decision_fills_at_the_next_open(self) -> None:
        """The lookahead this module exists to prevent.

        The rule goes long on its first decision. The entry price must be the
        open of the candle *after* the one it read — never that candle's close,
        which was not known when the decision was made.
        """
        candles = gapped(12)
        pairs = list(execution_pairs(candles, SMALL))
        decided_on = next(c for c in candles if c.close_time == pairs[0][0].moment)
        # The fixture guarantees the two candidate prices differ, so the
        # assertion below can fail if the engine fills on the wrong one.
        assert pairs[0][1].open != decided_on.close
        result = CandleBacktest(rule=OnceLong(at=1), costs=NO_COST).run(candles, SMALL)
        assert result.trades[0].entry_price == pairs[0][1].open
        assert result.trades[0].entry_price != decided_on.close


class TestControls:
    def test_always_flat_never_trades_and_never_moves_equity(self) -> None:
        """If this shows any profit or loss, every other number is suspect."""
        result = CandleBacktest(rule=AlwaysFlat()).run(rising(30), SMALL)
        assert result.trades == ()
        assert result.net_pnl == 0
        assert result.exposure_pct == 0
        assert result.max_drawdown_pct == 0

    def test_buy_and_hold_holds_one_position_throughout(self) -> None:
        result = CandleBacktest(rule=BuyAndHold(), costs=NO_COST).run(rising(30), SMALL)
        assert len(result.trades) == 1
        assert result.net_pnl > 0
        assert result.exposure_pct == 100

    def test_a_shuffled_control_keeps_the_mix_and_loses_the_order(self) -> None:
        decisions = [Decision.LONG] * 6 + [Decision.SHORT] * 3 + [Decision.FLAT]
        control = Shuffled(decisions=decisions, seed=7)
        replayed = [control.decide(_FAKE) for _ in decisions]
        assert sorted(replayed) == sorted(decisions)
        assert replayed != decisions

    def test_two_seeds_give_two_orders(self) -> None:
        # Long enough that two orders matching by chance is not a real risk;
        # ten decisions have only a few hundred distinct arrangements.
        decisions = [Decision.LONG] * 10 + [Decision.SHORT] * 10 + [Decision.FLAT] * 10
        first = [Shuffled(decisions=decisions, seed=1).decide(_FAKE) for _ in decisions]
        second = [Shuffled(decisions=decisions, seed=2).decide(_FAKE) for _ in decisions]
        assert first != second

    def test_the_same_seed_gives_the_same_order(self) -> None:
        """A control whose order cannot be regenerated cannot be checked."""
        decisions = [Decision.LONG] * 5 + [Decision.FLAT] * 5
        first = [Shuffled(decisions=decisions, seed=3).decide(_FAKE) for _ in decisions]
        second = [Shuffled(decisions=decisions, seed=3).decide(_FAKE) for _ in decisions]
        assert first == second


class TestCosts:
    def test_a_reversal_pays_two_fills_not_one(self) -> None:
        """Treating it as one understates a flipping rule's cost by half."""
        candles = rising(30)
        costs = CostModel(taker_fee_bps=Decimal(10), half_spread_bps=Decimal(0))
        flipper = _Flipper()
        result = CandleBacktest(rule=flipper, costs=costs, notional=Decimal(1000)).run(
            candles, SMALL
        )
        # Every trade carries an entry fee and an exit fee.
        for trade in result.trades:
            assert trade.fees > trade.notional * Decimal("0.0019")

    def test_costs_can_turn_a_gross_profit_into_a_net_loss(self) -> None:
        """Rev.2 §25's finding, and the engine must be able to report it."""
        candles = rising(40)
        expensive = CostModel(taker_fee_bps=Decimal(200), half_spread_bps=Decimal(0))
        result = CandleBacktest(rule=_Flipper(), costs=expensive).run(candles, SMALL)
        assert result.fees > 0
        assert result.net_pnl < result.gross_pnl


class TestReporting:
    def test_an_open_position_is_closed_at_the_last_known_price(self) -> None:
        """Otherwise a paper gain is reported as though it had been taken."""
        candles = rising(30)
        result = CandleBacktest(rule=BuyAndHold(), costs=NO_COST).run(candles, SMALL)
        assert result.trades[-1].exit_price == candles[-1].close

    def test_a_win_rate_over_no_trades_is_none_not_zero(self) -> None:
        result = CandleBacktest(rule=AlwaysFlat()).run(rising(30), SMALL)
        assert result.win_rate is None
        assert result.costs_exceeded_edge is None

    def test_drawdown_counts_a_fall_inside_an_open_position(self) -> None:
        """A loss recovered before the exit was still lived through.

        Closed-trade drawdown would report zero here: the single trade ends
        profitable, and the dip in the middle would never appear.
        """
        candles = series(
            ["100", "100", "100", "100", "100", "100", "100", "100", "80", "100", "120"]
        )
        result = CandleBacktest(rule=BuyAndHold(), costs=NO_COST, notional=Decimal(1000)).run(
            candles, SMALL
        )
        assert result.trades[-1].net_pnl > 0
        # A 20% fall on $1,000 of notional is $200 against $10,000 of equity,
        # so 2% — drawdown is reported against the account, not the price.
        # Closed-trade drawdown would report zero: the trade ends profitable
        # and the dip never appears.
        assert result.max_drawdown_pct > Decimal("1.5")

    def test_position_hours_are_counted_since_funding_is_not_charged(self) -> None:
        """Funding is real at this horizon; the exposure has to be visible."""
        result = CandleBacktest(rule=BuyAndHold(), costs=NO_COST).run(rising(30), SMALL)
        assert result.position_hours == Decimal(result.candles_in_position) * 4


class TestRefusals:
    def test_a_series_with_no_actionable_decision_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not enough candles"):
            CandleBacktest(rule=BuyAndHold()).run(rising(SMALL.warmup), SMALL)


@dataclass(slots=True)
class _Flipper:
    """Alternates long and short every decision. A worst case for costs."""

    name: str = "flipper"
    seen: int = 0

    def decide(self, features: FeatureSet) -> Decision:  # noqa: ARG002 - by design
        self.seen += 1
        return Decision.LONG if self.seen % 2 else Decision.SHORT


class TestTrendFollowing:
    def test_it_will_not_chase_a_trend_already_far_from_its_average(self) -> None:
        """Entering late is this family's documented failure."""
        rule = TrendFollowing(stretch_limit_bps=Decimal(50))
        stretched = _reading(trend_bps=Decimal(100), slope=Decimal(5), distance=Decimal(400))
        assert rule.decide(stretched) is Decision.FLAT

    def test_it_goes_long_a_fresh_uptrend(self) -> None:
        rule = TrendFollowing(stretch_limit_bps=Decimal(300))
        fresh = _reading(trend_bps=Decimal(100), slope=Decimal(5), distance=Decimal(20))
        assert rule.decide(fresh) is Decision.LONG

    def test_a_range_is_flat_not_a_coin_flip(self) -> None:
        ranging = _reading(trend_bps=Decimal(1), slope=Decimal(0), distance=Decimal(0))
        assert TrendFollowing().decide(ranging) is Decision.FLAT


def _reading(*, trend_bps: Decimal, slope: Decimal, distance: Decimal) -> FeatureSet:
    if trend_bps > 10 and slope > 0:
        trend = TrendRegime.UP
    elif trend_bps < -10 and slope < 0:
        trend = TrendRegime.DOWN
    else:
        trend = TrendRegime.RANGE
    return FeatureSet(
        moment=START,
        close=Decimal(100),
        trend_bps=trend_bps,
        trend_slope_bps=slope,
        distance_from_trend_bps=distance,
        momentum_bps=Decimal(0),
        momentum_acceleration_bps=Decimal(0),
        atr_bps=Decimal(100),
        realized_volatility_bps=Decimal(100),
        volatility_ratio=Decimal(1),
        relative_volume=Decimal(1),
        swing_high_bps=Decimal(100),
        swing_low_bps=Decimal(100),
        trend_regime=trend,
        volatility_regime=VolatilityRegime.NORMAL,
    )


_FAKE = _reading(trend_bps=Decimal(0), slope=Decimal(0), distance=Decimal(0))


class TestConfirmation:
    """Acting only on a change of mind that held (the churn fix).

    Written before the fix's effect on returns was looked at, so these test the
    mechanism rather than the result. The hypothesis — fewer trades, similar
    gross per trade — is checked on data, not here.
    """

    def test_a_one_candle_flip_is_ignored(self) -> None:
        """The churn this exists to remove: a label crossing back and forth."""
        rule = Confirmed(inner=_Flipper(), confirm=2)
        decided = [rule.decide(_FAKE) for _ in range(10)]
        assert set(decided) == {Decision.FLAT}

    def test_a_change_that_holds_is_acted_on(self) -> None:
        rule = Confirmed(inner=BuyAndHold(), confirm=2)
        assert rule.decide(_FAKE) is Decision.FLAT
        assert rule.decide(_FAKE) is Decision.LONG

    def test_a_longer_confirmation_waits_longer(self) -> None:
        rule = Confirmed(inner=BuyAndHold(), confirm=3)
        assert [rule.decide(_FAKE) for _ in range(4)] == [
            Decision.FLAT,
            Decision.FLAT,
            Decision.LONG,
            Decision.LONG,
        ]

    def test_it_never_changes_what_the_inner_rule_thinks(self) -> None:
        """Only when a decision is acted on, never which decision it is.

        A wrapper that could invent a target the inner rule never wanted would
        be a second rule wearing the first one's name.
        """
        inner = TrendFollowing()
        rule = Confirmed(inner=inner, confirm=2)
        readings = [
            _reading(trend_bps=Decimal(100), slope=Decimal(5), distance=Decimal(20))
            for _ in range(5)
        ]
        wrapped = {rule.decide(reading) for reading in readings}
        assert wrapped <= {inner.decide(readings[0]), Decision.FLAT}

    def test_confirmation_must_span_a_candle(self) -> None:
        with pytest.raises(ValueError, match="at least one candle"):
            Confirmed(inner=BuyAndHold(), confirm=0)

    def test_it_cuts_the_trade_count_on_a_churning_series(self) -> None:
        """The mechanism's whole purpose, measured on a backtest."""
        candles = rising(60)
        churn = _Flipper()
        without = CandleBacktest(rule=churn, costs=NO_COST).run(candles, SMALL)
        withc = CandleBacktest(rule=Confirmed(inner=_Flipper(), confirm=2), costs=NO_COST).run(
            candles, SMALL
        )
        assert len(withc.trades) < len(without.trades)


class TestPerTradeEconomics:
    def test_gross_and_fee_per_trade_are_comparable(self) -> None:
        """The two numbers that say whether a signal pays for its transaction."""
        candles = rising(40)
        costs = CostModel(taker_fee_bps=Decimal(5), half_spread_bps=Decimal(0))
        result = CandleBacktest(rule=BuyAndHold(), costs=costs).run(candles, SMALL)
        assert result.fee_bps_per_trade is not None
        assert result.gross_bps_per_trade is not None
        # Both fees are expressed against the *entry* notional. At 5 bps a
        # side that is 10 bps when price is flat, and more on a rising series
        # because the exit fee is charged on the larger exit notional.
        assert result.fee_bps_per_trade > Decimal(10)
        assert result.fee_bps_per_trade < Decimal(15)

    def test_they_are_none_with_no_trades(self) -> None:
        result = CandleBacktest(rule=AlwaysFlat()).run(rising(30), SMALL)
        assert result.gross_bps_per_trade is None
        assert result.fee_bps_per_trade is None
