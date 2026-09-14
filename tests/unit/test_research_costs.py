"""The cost model, and the number a strategy has to beat.

Build 0.1 Rev.2 §25: a strategy profitable before costs and unprofitable after
has no demonstrated edge. These tests are mostly about the ways a cost model
can be made to flatter one.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.research.costs import (
    BASE_MAKER_FEE_BPS,
    BASE_TAKER_FEE_BPS,
    MAX_FUNDING_RATE_PER_HOUR_BPS,
    CostModel,
    hurdle,
)


class TestDefaults:
    def test_the_default_is_the_taker_fee(self) -> None:
        """Maker fees are a request, not a fill. Defaults must not assume one."""
        assert CostModel().taker_fee_bps == BASE_TAKER_FEE_BPS
        assert BASE_MAKER_FEE_BPS < BASE_TAKER_FEE_BPS

    def test_a_round_trip_pays_the_fee_twice(self) -> None:
        """Quoting one way is the commonest way to double an apparent edge."""
        model = CostModel(half_spread_bps=Decimal(0))
        assert model.round_trip_bps == BASE_TAKER_FEE_BPS * 2

    def test_the_default_hurdle_is_ten_basis_points(self) -> None:
        assert hurdle().round_trip_bps == Decimal(10)

    def test_a_cost_cannot_be_negative(self) -> None:
        with pytest.raises(ValueError, match="not a rebate"):
            CostModel(slippage_bps=Decimal(-1))


class TestHurdle:
    def test_the_break_even_move_is_stated_in_price(self) -> None:
        """10 bps on BTC at 60000 is 60 units, per round trip."""
        assert hurdle().required_move(Decimal(60000)) == Decimal(60)

    def test_an_unmeasured_hurdle_says_so(self) -> None:
        """Slippage and drift default to zero, which is optimistic in both."""
        assert not hurdle().is_fully_measured

    def test_a_measured_hurdle_says_so(self) -> None:
        model = CostModel(slippage_bps=Decimal("0.3"), adverse_drift_bps=Decimal("1.2"))
        assert hurdle(model).is_fully_measured

    def test_the_description_carries_its_own_caveat(self) -> None:
        """A research note quoting this must not be able to drop the caveat."""
        described = hurdle().describe(Decimal(60000))
        assert described["fully_measured"] is False
        assert described["round_trip_bps"] == "10.0"

    def test_drift_is_charged_once_not_twice(self) -> None:
        """A round trip has one decision that acts on stale information."""
        model = CostModel(adverse_drift_bps=Decimal(2), half_spread_bps=Decimal(0))
        assert model.round_trip_bps == BASE_TAKER_FEE_BPS * 2 + 2


class TestFunding:
    def test_a_position_inside_one_hour_pays_nothing(self) -> None:
        """Hyperliquid charges at the boundary, not by duration."""
        cost = CostModel().funding_cost(
            Decimal(60000), hourly_rate_bps=Decimal("1.25"), hours_held_across_boundary=0
        )
        assert cost == 0

    def test_crossing_one_boundary_pays_in_full(self) -> None:
        """A two-minute position that straddles a snapshot pays the whole hour."""
        cost = CostModel().funding_cost(
            Decimal(60000), hourly_rate_bps=Decimal("1.25"), hours_held_across_boundary=1
        )
        assert cost == Decimal("7.5")

    def test_a_negative_rate_is_a_receipt(self) -> None:
        cost = CostModel().funding_cost(
            Decimal(60000), hourly_rate_bps=Decimal("-1.25"), hours_held_across_boundary=1
        )
        assert cost < 0

    def test_a_rate_beyond_the_venue_cap_is_refused(self) -> None:
        """Almost always a unit error — a percentage passed as basis points."""
        with pytest.raises(ValueError, match="exceeds the venue cap"):
            CostModel().funding_cost(
                Decimal(60000),
                hourly_rate_bps=MAX_FUNDING_RATE_PER_HOUR_BPS + 1,
                hours_held_across_boundary=1,
            )


class TestNotionalCost:
    def test_cost_scales_with_notional(self) -> None:
        model = CostModel()
        assert model.round_trip_cost(Decimal(120000)) == model.round_trip_cost(Decimal(60000)) * 2

    def test_a_negative_notional_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot be negative"):
            CostModel().round_trip_cost(Decimal(-1))

    def test_the_default_round_trip_on_btc(self) -> None:
        """The concrete number: 60 units on a 60000 notional."""
        assert CostModel().round_trip_cost(Decimal(60000)) == Decimal(60)
