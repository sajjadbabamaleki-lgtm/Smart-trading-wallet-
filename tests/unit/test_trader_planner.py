"""Risk-based sizing: the stop loss decides the size, never the other way round."""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.trader.planner import (
    PlanRejectedError,
    RiskLimits,
    TradePlan,
    plan_trade,
)
from services.trader.venue import Direction, MarketRules

SOL = MarketRules(
    symbol="SOL",
    tick_size=Decimal("0.01"),
    lot_size=Decimal("0.01"),
    max_leverage=20,
    min_order_usd=Decimal(10),
    max_order_usd=Decimal(1_000_000),
)
NO_COSTS = RiskLimits(
    risk_percent=Decimal(1),
    max_leverage=3,
    taker_fee_rate=Decimal(0),
    slippage_percent=Decimal(0),
)


def _plan(
    *,
    direction: Direction = Direction.LONG,
    entry: str = "150",
    stop: str = "145",
    target: str | None = "160",
    equity: str = "1000",
    available: str | None = None,
    limits: RiskLimits = NO_COSTS,
) -> TradePlan:
    return plan_trade(
        market=SOL,
        direction=direction,
        entry_price=Decimal(entry),
        stop_loss=Decimal(stop),
        take_profit=Decimal(target) if target is not None else None,
        equity=Decimal(equity),
        available=Decimal(available or equity),
        limits=limits,
    )


def test_long_is_sized_so_the_stop_loses_exactly_the_risk_budget() -> None:
    plan = _plan()
    # 1% of $1000 = $10; $5 per SOL to the stop -> 2 SOL.
    assert plan.amount == Decimal(2)
    assert plan.notional == Decimal(300)
    assert plan.loss_at_stop == Decimal(10)
    assert plan.profit_at_target == Decimal(20)
    assert plan.reward_to_risk == Decimal(2)
    assert plan.leverage == 1


def test_short_mirrors_the_long() -> None:
    plan = _plan(direction=Direction.SHORT, stop="155", target="140")
    assert plan.amount == Decimal(2)
    assert plan.loss_at_stop == Decimal(10)
    assert plan.profit_at_target == Decimal(20)


def test_fees_and_slippage_shrink_the_size_so_the_loss_stays_within_budget() -> None:
    limits = RiskLimits(
        risk_percent=Decimal(1),
        max_leverage=3,
        taker_fee_rate=Decimal("0.0005"),
        slippage_percent=Decimal("0.5"),
    )
    plan = _plan(limits=limits)
    assert plan.amount < Decimal(2)
    assert plan.loss_at_stop <= plan.risk_usd


def test_size_rounds_down_to_the_lot_size() -> None:
    plan = _plan(stop="143")  # $10 / $7 = 1.428... SOL
    assert plan.amount == Decimal("1.42")


def test_prices_round_to_the_tick_size() -> None:
    plan = _plan(stop="145.004", target="160.006")
    assert plan.stop_loss == Decimal("145.00")
    assert plan.take_profit == Decimal("160.01")


def test_tight_stop_is_capped_by_leverage() -> None:
    # $10 risk over a $0.10 stop wants 100 SOL ($15,000); 3x of $1000 allows $3000.
    plan = _plan(stop="149.90", target=None)
    assert plan.capped_by_leverage
    assert plan.notional <= Decimal(3000)
    assert plan.leverage == 3
    assert plan.loss_at_stop < plan.risk_usd


def test_leverage_is_what_the_available_margin_requires() -> None:
    plan = _plan(stop="148", available="300")  # $750 notional on $300 margin
    assert plan.amount == Decimal(5)
    assert plan.leverage == 3


@pytest.mark.parametrize(
    ("direction", "stop", "target", "fragment"),
    [
        (Direction.LONG, "151", "160", "stop loss must be below"),
        (Direction.LONG, "150", "160", "stop loss must be below"),
        (Direction.LONG, "145", "149", "take profit must be above"),
        (Direction.SHORT, "149", "140", "stop loss must be above"),
        (Direction.SHORT, "155", "151", "take profit must be below"),
    ],
)
def test_wrong_side_prices_are_refused(
    direction: Direction, stop: str, target: str, fragment: str
) -> None:
    with pytest.raises(PlanRejectedError, match=fragment):
        _plan(direction=direction, stop=stop, target=target)


def test_stop_that_rounds_onto_the_entry_is_refused() -> None:
    with pytest.raises(PlanRejectedError, match="stop loss must be below"):
        _plan(stop="149.999")


def test_position_below_venue_minimum_is_refused_with_a_reason() -> None:
    with pytest.raises(PlanRejectedError, match="move the stop closer"):
        _plan(stop="50", equity="50")


def test_account_too_small_even_at_max_leverage_says_so() -> None:
    with pytest.raises(PlanRejectedError, match="add funds"):
        _plan(stop="149.99", equity="3")


@pytest.mark.parametrize("risk", ["0", "5.01", "20"])
def test_risk_outside_the_hard_bounds_is_refused(risk: str) -> None:
    limits = RiskLimits(
        risk_percent=Decimal(risk),
        max_leverage=3,
        taker_fee_rate=Decimal(0),
        slippage_percent=Decimal(0),
    )
    with pytest.raises(PlanRejectedError, match="risk per trade"):
        _plan(limits=limits)


def test_empty_account_is_refused() -> None:
    with pytest.raises(PlanRejectedError, match="deposit"):
        _plan(equity="0")


def test_market_leverage_limit_wins_over_a_higher_setting() -> None:
    low_leverage_market = MarketRules(
        symbol="SOL",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.01"),
        max_leverage=2,
        min_order_usd=Decimal(10),
        max_order_usd=None,
    )
    plan = plan_trade(
        market=low_leverage_market,
        direction=Direction.LONG,
        entry_price=Decimal(150),
        stop_loss=Decimal("149.90"),
        take_profit=None,
        equity=Decimal(1000),
        available=Decimal(1000),
        limits=RiskLimits(Decimal(1), 10, Decimal(0), Decimal(0)),
    )
    assert plan.notional <= Decimal(2000)
    assert plan.leverage == 2
