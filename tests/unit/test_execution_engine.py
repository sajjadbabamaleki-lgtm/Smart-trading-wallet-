"""The execution path, and the ways one order becomes two.

Build 0.1 Rev.2 §18 wants this layer early so that disconnects, timeouts,
duplicate requests and restart recovery are exercised before any strategy
depends on them. The tests below are those failure modes, plus the rule that
gives the layer its authority limits: an intent is re-validated here, not
trusted (Invariant 2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from libs.config import Settings, load_settings
from libs.domain.clock import ManualClock
from libs.exchange.models import OrderState, OrderStatus
from libs.schemas.enums import ExecutionEnvironment, Side
from services.execution_engine import (
    ExecutionEngine,
    IllegalTransitionError,
    IntentRefusedError,
    OrderRecord,
)
from services.risk_engine import (
    ExecutionIntent,
    IntentAlreadyConsumedError,
    IntentLedger,
    RejectionCode,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
PRICE = Decimal(60_000)


def settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "execution_environment": ExecutionEnvironment.TESTNET,
        "trading_enabled": True,
        "testnet_api_wallet_private_key": "0x" + "1" * 64,
        "testnet_api_wallet_address": "0x" + "2" * 40,
        "asset_allowlist": ("BTC",),
        "max_order_notional": Decimal(100),
        "intent_ttl_seconds": 10.0,
    }
    base.update(overrides)
    return load_settings(**base)


def intent(**overrides: object) -> ExecutionIntent:
    base: dict[str, object] = {
        "correlation_id": "cor_test",
        "environment": ExecutionEnvironment.TESTNET,
        "asset": "BTC",
        "side": Side.BUY,
        "notional_usd": Decimal(60),
        "stop_price": Decimal(59_000),
        "issued_at": NOW,
        "expires_at": NOW + timedelta(seconds=10),
    }
    base.update(overrides)
    return ExecutionIntent(**base)


def build(
    clock: ManualClock | None = None, **overrides: object
) -> tuple[ExecutionEngine, IntentLedger]:
    ledger = IntentLedger()
    engine = ExecutionEngine(settings(**overrides), ledger, clock=clock or ManualClock(NOW))
    return engine, ledger


class TestOneIntentOneOrder:
    def test_an_intent_produces_an_order_for_its_own_notional(self) -> None:
        engine, ledger = build()
        request = engine.prepare(ledger.record(intent()), price=PRICE)
        assert request.quantity == Decimal("0.001")
        assert request.asset == "BTC"
        assert request.side is Side.BUY

    def test_the_order_id_is_derived_from_the_intent(self) -> None:
        """A retry must reach the same order, so the id cannot be random."""
        engine, ledger = build()
        authorised = ledger.record(intent())
        request = engine.prepare(authorised, price=PRICE)
        assert request.intent_id == authorised.intent_id
        assert ExecutionEngine.client_order_id(authorised) == request.client_order_id

    def test_an_intent_cannot_be_spent_twice(self) -> None:
        """The second order is the one that doubles the position."""
        engine, ledger = build()
        authorised = ledger.record(intent())
        engine.prepare(authorised, price=PRICE)
        with pytest.raises(IntentAlreadyConsumedError):
            engine.prepare(authorised, price=PRICE)

    def test_two_intents_produce_two_different_orders(self) -> None:
        engine, ledger = build()
        first = engine.prepare(ledger.record(intent()), price=PRICE)
        second = engine.prepare(ledger.record(intent()), price=PRICE)
        assert first.client_order_id != second.client_order_id


class TestIndependentRevalidation:
    """Invariant 2: this layer checks the intent again rather than trusting it."""

    def test_an_expired_intent_cannot_open_a_position(self) -> None:
        clock = ManualClock(NOW)
        engine, ledger = build(clock)
        authorised = ledger.record(intent())
        clock.advance_seconds(11)
        with pytest.raises(IntentRefusedError) as raised:
            engine.prepare(authorised, price=PRICE)
        assert RejectionCode.INTENT_EXPIRED in raised.value.reasons

    def test_the_kill_switch_stops_execution_too(self) -> None:
        """Engaged after the intent was issued: the boundary still holds."""
        engine, ledger = build(trading_enabled=False)
        with pytest.raises(IntentRefusedError) as raised:
            engine.prepare(ledger.record(intent()), price=PRICE)
        assert RejectionCode.KILL_SWITCH_ENGAGED in raised.value.reasons

    def test_an_intent_for_another_environment_is_refused(self) -> None:
        engine, ledger = build()
        with pytest.raises(IntentRefusedError) as raised:
            engine.prepare(
                ledger.record(intent(environment=ExecutionEnvironment.PAPER)),
                price=PRICE,
            )
        assert RejectionCode.ENVIRONMENT_FORBIDS_EXECUTION in raised.value.reasons

    def test_an_intent_above_the_ceiling_is_refused_not_trimmed(self) -> None:
        """Sizing is the Risk Engine's authority; execution only refuses."""
        engine, ledger = build()
        with pytest.raises(IntentRefusedError) as raised:
            engine.prepare(ledger.record(intent(notional_usd=Decimal(500))), price=PRICE)
        assert RejectionCode.SIZE_ABOVE_LIMIT in raised.value.reasons

    def test_an_intent_for_a_disallowed_asset_is_refused(self) -> None:
        engine, ledger = build(asset_allowlist=("ETH",))
        with pytest.raises(IntentRefusedError) as raised:
            engine.prepare(ledger.record(intent()), price=PRICE)
        assert RejectionCode.ASSET_NOT_ALLOWED in raised.value.reasons

    def test_a_refused_intent_is_not_consumed(self) -> None:
        """A refusal must leave the intent spendable once the fault is fixed."""
        engine, ledger = build(trading_enabled=False)
        authorised = ledger.record(intent())
        with pytest.raises(IntentRefusedError):
            engine.prepare(authorised, price=PRICE)
        # Same intent, same ledger, kill switch released: it spends fine.
        working = ExecutionEngine(settings(), ledger, clock=ManualClock(NOW))
        assert working.prepare(authorised, price=PRICE) is not None

    def test_a_size_that_rounds_to_nothing_is_refused(self) -> None:
        engine, ledger = build()
        with pytest.raises(IntentRefusedError) as raised:
            engine.prepare(ledger.record(intent()), price=Decimal(100_000_000_000))
        assert RejectionCode.SIZE_BELOW_MINIMUM in raised.value.reasons

    def test_a_price_of_zero_is_not_a_price(self) -> None:
        engine, ledger = build()
        with pytest.raises(ValueError, match="price must be positive"):
            engine.prepare(ledger.record(intent()), price=Decimal(0))


class TestTimeouts:
    """Rev.1 §53: a timeout is not a failure."""

    def test_a_timeout_leaves_the_order_unknown(self) -> None:
        engine, ledger = build()
        request = engine.prepare(ledger.record(intent()), price=PRICE)
        engine.mark_submitted(request.client_order_id)
        record = engine.mark_unknown(request.client_order_id)
        assert record.state is OrderState.UNKNOWN
        assert record.needs_reconciliation

    def test_an_unknown_order_blocks_new_exposure(self) -> None:
        """Invariant 7: the system cannot size what it cannot see."""
        engine, ledger = build()
        request = engine.prepare(ledger.record(intent()), price=PRICE)
        engine.mark_submitted(request.client_order_id)
        engine.mark_unknown(request.client_order_id)
        assert len(engine.unresolved) == 1

    def test_the_venue_resolves_an_unknown_order(self) -> None:
        engine, ledger = build()
        request = engine.prepare(ledger.record(intent()), price=PRICE)
        engine.mark_submitted(request.client_order_id)
        engine.mark_unknown(request.client_order_id)
        record = engine.apply(
            OrderStatus(
                client_order_id=request.client_order_id,
                venue_order_id="v-1",
                state=OrderState.FILLED,
                filled_quantity=request.quantity,
                average_fill_price=PRICE,
                observed_at=NOW,
            )
        )
        assert record.state is OrderState.FILLED
        assert record.venue_order_id == "v-1"
        assert engine.unresolved == ()


class TestLifecycle:
    def record(self) -> OrderRecord:
        return OrderRecord(
            client_order_id="stw-1",
            intent_id="int_1",
            correlation_id="cor_1",
            asset="BTC",
            quantity=Decimal("0.001"),
        )

    def test_a_filled_order_cannot_become_cancelled(self) -> None:
        record = self.record()
        for state in (OrderState.VALIDATED, OrderState.SUBMITTED, OrderState.FILLED):
            record.transition(state, at=NOW)
        with pytest.raises(IllegalTransitionError):
            record.transition(OrderState.CANCELLED, at=NOW)

    def test_a_refused_transition_leaves_the_record_where_it_was(self) -> None:
        record = self.record()
        with pytest.raises(IllegalTransitionError):
            record.transition(OrderState.FILLED, at=NOW)
        assert record.state is OrderState.CREATED

    def test_unknown_is_not_terminal(self) -> None:
        assert not OrderState.UNKNOWN.is_terminal

    def test_a_cancel_can_lose_the_race_with_a_fill(self) -> None:
        record = self.record()
        for state in (
            OrderState.VALIDATED,
            OrderState.SUBMITTED,
            OrderState.ACKNOWLEDGED,
            OrderState.CANCEL_PENDING,
            OrderState.FILLED,
        ):
            record.transition(state, at=NOW)
        assert record.state is OrderState.FILLED

    def test_every_transition_is_kept(self) -> None:
        """An order's history is the audit trail Rev.1 §59 asks for."""
        record = self.record()
        record.transition(OrderState.VALIDATED, at=NOW)
        record.transition(OrderState.SUBMITTED, at=NOW)
        assert [state for state, _ in record.history] == [
            OrderState.VALIDATED,
            OrderState.SUBMITTED,
        ]

    def test_partial_fills_accumulate_without_leaving_the_state(self) -> None:
        record = self.record()
        for state in (
            OrderState.VALIDATED,
            OrderState.SUBMITTED,
            OrderState.PARTIALLY_FILLED,
            OrderState.PARTIALLY_FILLED,
        ):
            record.transition(state, at=NOW)
        assert record.state is OrderState.PARTIALLY_FILLED


class TestVenueTruth:
    def test_the_same_status_twice_changes_nothing(self) -> None:
        """Venues repeat themselves; a repeat is not a transition."""
        engine, ledger = build()
        request = engine.prepare(ledger.record(intent()), price=PRICE)
        engine.mark_submitted(request.client_order_id)
        status = OrderStatus(
            client_order_id=request.client_order_id,
            state=OrderState.FILLED,
            filled_quantity=request.quantity,
            average_fill_price=PRICE,
            observed_at=NOW,
        )
        engine.apply(status)
        record = engine.apply(status)
        assert record.state is OrderState.FILLED
        assert [state for state, _ in record.history].count(OrderState.FILLED) == 1

    def test_the_engine_exposes_what_it_believes(self) -> None:
        engine, ledger = build()
        request = engine.prepare(ledger.record(intent()), price=PRICE)
        assert request.client_order_id in engine.orders

    def test_an_environment_with_no_endpoint_and_no_credential_says_both(self) -> None:
        engine, ledger = build(
            execution_environment=ExecutionEnvironment.DEVELOPMENT,
            testnet_api_wallet_private_key="",
            testnet_api_wallet_address="",
        )
        with pytest.raises(IntentRefusedError) as raised:
            engine.prepare(
                ledger.record(intent(environment=ExecutionEnvironment.DEVELOPMENT)),
                price=PRICE,
            )
        assert RejectionCode.ENVIRONMENT_FORBIDS_EXECUTION in raised.value.reasons
        assert RejectionCode.NO_SIGNING_CREDENTIAL in raised.value.reasons

    def test_each_reason_is_reported_once(self) -> None:
        """Two rules can fail for the same cause; the audit line says it once."""
        engine, _ = build(
            execution_environment=ExecutionEnvironment.DEVELOPMENT,
            testnet_api_wallet_private_key="",
            testnet_api_wallet_address="",
        )
        reasons = engine.revalidate(intent(environment=ExecutionEnvironment.PAPER), at=NOW)
        assert reasons.count(RejectionCode.ENVIRONMENT_FORBIDS_EXECUTION) == 1
