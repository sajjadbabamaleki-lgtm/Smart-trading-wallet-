"""Venue-neutral execution models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from libs.exchange import (
    AccountState,
    MarketState,
    OrderRequest,
    OrderState,
    OrderType,
    Position,
    TimeInForce,
)
from libs.schemas.enums import Side

AWARE = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)


def _request(**kwargs: Any) -> OrderRequest:
    base = {
        "client_order_id": "cloid-1",
        "intent_id": "int_1",
        "correlation_id": "cor_1",
        "asset": "BTC",
        "side": Side.BUY,
        "quantity": Decimal("0.01"),
        "order_type": OrderType.MARKET,
    }
    return OrderRequest(**{**base, **kwargs})


class TestOrderState:
    def test_unknown_is_not_terminal_because_it_demands_reconciliation(self) -> None:
        assert not OrderState.UNKNOWN.is_terminal

    def test_terminal_states(self) -> None:
        terminal = {state for state in OrderState if state.is_terminal}
        assert terminal == {
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.EXPIRED,
        }


class TestOrderRequest:
    def test_order_cannot_exist_without_an_intent(self) -> None:
        """Provenance is structural: no intent id, no order."""
        with pytest.raises(ValidationError):
            OrderRequest(  # type: ignore[call-arg]
                client_order_id="cloid-1",
                correlation_id="cor_1",
                asset="BTC",
                side=Side.BUY,
                quantity=Decimal("0.01"),
                order_type=OrderType.MARKET,
            )

    def test_limit_order_requires_a_price(self) -> None:
        with pytest.raises(ValidationError, match="LIMIT order requires"):
            _request(order_type=OrderType.LIMIT)

    def test_market_order_must_not_carry_a_price(self) -> None:
        with pytest.raises(ValidationError, match="must not carry limit_price"):
            _request(order_type=OrderType.MARKET, limit_price=Decimal("60000"))

    def test_market_order_cannot_be_post_only(self) -> None:
        with pytest.raises(ValidationError, match="add-liquidity-only"):
            _request(order_type=OrderType.MARKET, time_in_force=TimeInForce.ALO)

    def test_zero_quantity_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _request(quantity=Decimal(0))

    def test_valid_post_only_limit_order(self) -> None:
        request = _request(
            order_type=OrderType.LIMIT,
            limit_price=Decimal("59000"),
            time_in_force=TimeInForce.ALO,
        )
        assert request.time_in_force is TimeInForce.ALO

    def test_reduce_only_defaults_to_false(self) -> None:
        assert _request().reduce_only is False


class TestMarketState:
    def test_spread_in_basis_points(self) -> None:
        state = MarketState(
            asset="BTC",
            instrument="BTC-PERP",
            bid_price=Decimal("59994"),
            ask_price=Decimal("60006"),
            observed_at=AWARE,
            local_receive_monotonic_ns=0,
        )
        assert state.mid_price == Decimal("60000")
        assert state.spread_bps == Decimal(2)

    def test_spread_unknown_when_one_side_missing(self) -> None:
        state = MarketState(
            asset="BTC",
            instrument="BTC-PERP",
            bid_price=Decimal("59994"),
            observed_at=AWARE,
            local_receive_monotonic_ns=0,
        )
        assert state.spread_bps is None


class TestPosition:
    def test_sign_determines_side(self) -> None:
        assert Position(asset="BTC", size=Decimal("1.5")).side is Side.BUY
        assert Position(asset="BTC", size=Decimal("-1.5")).side is Side.SELL
        assert Position(asset="BTC", size=Decimal(0)).side is None


class TestAccountState:
    def test_flat_account_has_no_positions(self) -> None:
        account = AccountState(
            equity=Decimal(1000), available_margin=Decimal(1000), observed_at=AWARE
        )
        assert account.positions == ()
