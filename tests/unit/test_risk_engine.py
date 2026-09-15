"""The capital-control boundary, control by control.

Build 0.1 Rev.2 §17 lists eight controls the Risk Engine must carry. Each has a
test here that fails if the control is removed, because a control nobody tests
is a comment. The engine's authority (Invariant 1) and the intent's three
properties (Invariant 2) are tested alongside them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from libs.config import Settings, load_settings
from libs.domain.clock import ManualClock
from libs.schemas.enums import ExecutionEnvironment, Side
from services.risk_engine import (
    ExecutionIntent,
    IntentAlreadyConsumedError,
    IntentExpiredError,
    IntentLedger,
    IntentNotFoundError,
    IntentState,
    MarketSnapshot,
    RejectionCode,
    RiskDecision,
    RiskEngine,
    RiskOutcome,
    TradeProposal,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
BID = Decimal(60_000)


def settings(**overrides: object) -> Settings:
    """A build that is allowed to trade, so a test can remove one thing at a time."""
    base: dict[str, object] = {
        "execution_environment": ExecutionEnvironment.TESTNET,
        "trading_enabled": True,
        "testnet_api_wallet_private_key": "0x" + "1" * 64,
        "testnet_api_wallet_address": "0x" + "2" * 40,
        "asset_allowlist": ("BTC",),
        "max_order_notional": Decimal(100),
        "intent_ttl_seconds": 10.0,
        "data_staleness_limit_seconds": 5.0,
    }
    base.update(overrides)
    return load_settings(**base)


def engine(clock: ManualClock | None = None, **overrides: object) -> RiskEngine:
    return RiskEngine(settings(**overrides), clock=clock or ManualClock(NOW))


def proposal(**overrides: object) -> TradeProposal:
    base: dict[str, object] = {
        "correlation_id": "cor_test",
        "asset": "BTC",
        "side": Side.BUY,
        "notional_usd": Decimal(50),
        "stop_price": Decimal(59_000),
        "take_profit_price": Decimal(62_000),
        "proposed_at": NOW,
    }
    base.update(overrides)
    return TradeProposal(**base)


def fresh(at: datetime = NOW, bid: Decimal = BID) -> MarketSnapshot:
    return MarketSnapshot(bid=bid, observed_at=at)


class TestApproval:
    def test_a_sound_proposal_is_approved_and_carries_an_intent(self) -> None:
        decision = engine().evaluate(proposal(), market=fresh())
        assert decision.outcome is RiskOutcome.APPROVED
        assert decision.approved_notional_usd == Decimal(50)
        assert decision.intent_id is not None
        assert decision.reasons == ()

    def test_the_intent_carries_the_exits_it_authorised(self) -> None:
        """The stop is part of the permission, not a later refinement."""
        risk = engine()
        decision = risk.evaluate(proposal(), market=fresh())
        assert decision.intent_id is not None
        intent = risk.ledger.consume(decision.intent_id, at=NOW)
        assert intent.stop_price == Decimal(59_000)
        assert intent.take_profit_price == Decimal(62_000)


class TestControls:
    """One test per control named in Rev.2 §17."""

    def test_an_asset_outside_the_allowlist_is_rejected(self) -> None:
        decision = engine().evaluate(proposal(asset="ETH"), market=fresh())
        assert decision.outcome is RiskOutcome.REJECTED
        assert RejectionCode.ASSET_NOT_ALLOWED in decision.reasons

    def test_an_environment_with_no_endpoint_cannot_execute(self) -> None:
        # Configuration already refuses to hold a credential in DEVELOPMENT, so
        # this build has neither — the point here is the endpoint.
        decision = engine(
            execution_environment=ExecutionEnvironment.DEVELOPMENT,
            testnet_api_wallet_private_key="",
            testnet_api_wallet_address="",
        ).evaluate(proposal(), market=fresh())
        assert decision.outcome is RiskOutcome.REJECTED
        assert RejectionCode.ENVIRONMENT_FORBIDS_EXECUTION in decision.reasons

    def test_the_kill_switch_blocks_new_exposure(self) -> None:
        decision = engine(trading_enabled=False).evaluate(proposal(), market=fresh())
        assert decision.outcome is RiskOutcome.REJECTED
        assert RejectionCode.KILL_SWITCH_ENGAGED in decision.reasons

    def test_no_credential_means_no_order(self) -> None:
        decision = engine(testnet_api_wallet_private_key="").evaluate(proposal(), market=fresh())
        assert decision.outcome is RiskOutcome.REJECTED
        assert RejectionCode.NO_SIGNING_CREDENTIAL in decision.reasons

    def test_an_oversized_order_is_reduced_rather_than_refused(self) -> None:
        """Invariant 1 gives the engine the authority to reduce."""
        decision = engine().evaluate(proposal(notional_usd=Decimal(250)), market=fresh())
        assert decision.outcome is RiskOutcome.REDUCED
        assert decision.approved_notional_usd == Decimal(100)
        assert decision.requested_notional_usd == Decimal(250)
        assert RejectionCode.SIZE_ABOVE_LIMIT in decision.reasons

    def test_stale_market_data_forces_no_trade(self) -> None:
        """Invariant 9: stale critical data must be able to force NO TRADE."""
        old = fresh(at=NOW - timedelta(seconds=30))
        decision = engine().evaluate(proposal(), market=old)
        assert decision.outcome is RiskOutcome.REJECTED
        assert RejectionCode.MARKET_DATA_STALE in decision.reasons

    def test_missing_market_data_is_not_permission_to_proceed(self) -> None:
        """Invariant 7: unknown is dangerous, and the answer is no new risk."""
        decision = engine().evaluate(proposal(), market=None)
        assert decision.outcome is RiskOutcome.REJECTED
        assert RejectionCode.MARKET_DATA_MISSING in decision.reasons

    def test_the_same_proposal_twice_is_refused_the_second_time(self) -> None:
        clock = ManualClock(NOW)
        risk = engine(clock)
        assert risk.evaluate(proposal(), market=fresh()).outcome is RiskOutcome.APPROVED
        clock.advance_seconds(1)
        again = risk.evaluate(proposal(correlation_id="cor_other"), market=fresh(at=clock.now()))
        assert again.outcome is RiskOutcome.REJECTED
        assert RejectionCode.DUPLICATE_PROPOSAL in again.reasons

    def test_a_repeat_after_the_intent_expires_is_allowed(self) -> None:
        """The window is the intent's life: once it cannot execute, it cannot double."""
        clock = ManualClock(NOW)
        risk = engine(clock)
        risk.evaluate(proposal(), market=fresh())
        clock.advance_seconds(11)
        later = risk.evaluate(proposal(), market=fresh(at=clock.now()))
        assert later.outcome is RiskOutcome.APPROVED


class TestDefinedDownside:
    """Invariant 6: no position opens without a defined downside."""

    def test_a_proposal_without_a_stop_cannot_be_built(self) -> None:
        with pytest.raises(ValueError, match="stop_price"):
            proposal(stop_price=None)

    def test_a_long_stop_above_the_market_is_not_a_stop(self) -> None:
        decision = engine().evaluate(proposal(stop_price=Decimal(61_000)), market=fresh())
        assert decision.outcome is RiskOutcome.REJECTED
        assert RejectionCode.STOP_ON_WRONG_SIDE in decision.reasons

    def test_a_short_stop_below_the_market_is_not_a_stop(self) -> None:
        decision = engine().evaluate(
            proposal(side=Side.SELL, stop_price=Decimal(59_000), take_profit_price=None),
            market=fresh(),
        )
        assert decision.outcome is RiskOutcome.REJECTED
        assert RejectionCode.STOP_ON_WRONG_SIDE in decision.reasons

    def test_a_target_on_the_wrong_side_is_rejected(self) -> None:
        decision = engine().evaluate(proposal(take_profit_price=Decimal(58_000)), market=fresh())
        assert decision.outcome is RiskOutcome.REJECTED
        assert RejectionCode.TAKE_PROFIT_ON_WRONG_SIDE in decision.reasons


class TestReasoning:
    def test_every_reason_is_reported_not_just_the_first(self) -> None:
        """An audit that names one fault hides the others that also applied."""
        decision = engine(trading_enabled=False).evaluate(proposal(asset="DOGE"), market=None)
        assert set(decision.reasons) >= {
            RejectionCode.ASSET_NOT_ALLOWED,
            RejectionCode.KILL_SWITCH_ENGAGED,
            RejectionCode.MARKET_DATA_MISSING,
        }

    def test_a_rejection_approves_nothing_and_issues_nothing(self) -> None:
        decision = engine(trading_enabled=False).evaluate(proposal(), market=fresh())
        assert decision.approved_notional_usd == 0
        assert decision.intent_id is None


class TestIntentLifecycle:
    """Invariant 2: immutable, expiring, single-use."""

    def intent(self, ttl_seconds: int = 10) -> ExecutionIntent:
        return ExecutionIntent(
            correlation_id="cor_test",
            environment=ExecutionEnvironment.TESTNET,
            asset="BTC",
            side=Side.BUY,
            notional_usd=Decimal(50),
            stop_price=Decimal(59_000),
            take_profit_price=None,
            issued_at=NOW,
            expires_at=NOW + timedelta(seconds=ttl_seconds),
        )

    def test_an_intent_is_immutable(self) -> None:
        intent = self.intent()
        with pytest.raises(ValidationError):
            intent.notional_usd = Decimal(1_000)  # type: ignore[misc]

    def test_an_intent_can_be_consumed_once(self) -> None:
        ledger = IntentLedger()
        intent = ledger.record(self.intent())
        assert ledger.consume(intent.intent_id, at=NOW).intent_id == intent.intent_id
        with pytest.raises(IntentAlreadyConsumedError):
            ledger.consume(intent.intent_id, at=NOW)

    def test_an_expired_intent_cannot_open_a_position(self) -> None:
        ledger = IntentLedger()
        intent = ledger.record(self.intent())
        with pytest.raises(IntentExpiredError):
            ledger.consume(intent.intent_id, at=NOW + timedelta(seconds=11))

    def test_an_expired_intent_stays_expired_rather_than_becoming_consumed(self) -> None:
        """The reason it is unusable must not decay into the wrong reason."""
        ledger = IntentLedger()
        intent = ledger.record(self.intent())
        later = NOW + timedelta(seconds=11)
        with pytest.raises(IntentExpiredError):
            ledger.consume(intent.intent_id, at=later)
        assert ledger.state_of(intent.intent_id, at=later) is IntentState.EXPIRED

    def test_an_unknown_intent_is_refused(self) -> None:
        with pytest.raises(IntentNotFoundError):
            IntentLedger().consume("int_never_issued", at=NOW)

    def test_an_intent_that_expires_at_issue_authorises_nothing(self) -> None:
        with pytest.raises(ValueError, match="authorises nothing"):
            ExecutionIntent(
                correlation_id="cor_test",
                environment=ExecutionEnvironment.TESTNET,
                asset="BTC",
                side=Side.BUY,
                notional_usd=Decimal(50),
                stop_price=Decimal(59_000),
                issued_at=NOW,
                expires_at=NOW,
            )

    def test_an_environment_reaching_real_capital_cannot_be_authorised(self) -> None:
        with pytest.raises(ValueError, match="may not be authorised"):
            ExecutionIntent(
                correlation_id="cor_test",
                environment=ExecutionEnvironment.PRODUCTION,
                asset="BTC",
                side=Side.BUY,
                notional_usd=Decimal(50),
                stop_price=Decimal(59_000),
                issued_at=NOW,
                expires_at=NOW + timedelta(seconds=10),
            )


class TestDecisionConsistency:
    """A decision that contradicts itself must not be constructible.

    These are the same rules the engine follows, enforced by the type rather
    than by the engine remembering to: a future caller building a decision by
    hand cannot produce a rejection that also authorises something.
    """

    def decision(self, **overrides: object) -> RiskDecision:
        base: dict[str, object] = {
            "outcome": RiskOutcome.APPROVED,
            "correlation_id": "cor_test",
            "requested_notional_usd": Decimal(50),
            "approved_notional_usd": Decimal(50),
            "decided_at": NOW,
            "intent_id": "int_test",
        }
        base.update(overrides)
        return RiskDecision(**base)

    def test_a_rejection_cannot_approve_a_size(self) -> None:
        with pytest.raises(ValidationError, match="approves nothing"):
            self.decision(outcome=RiskOutcome.REJECTED, intent_id=None)

    def test_a_rejection_must_state_a_reason(self) -> None:
        with pytest.raises(ValidationError, match="must say why"):
            self.decision(
                outcome=RiskOutcome.REJECTED,
                approved_notional_usd=Decimal(0),
                intent_id=None,
            )

    def test_a_rejection_cannot_carry_an_intent(self) -> None:
        with pytest.raises(ValidationError, match="issues no intent"):
            self.decision(
                outcome=RiskOutcome.REJECTED,
                approved_notional_usd=Decimal(0),
                reasons=(RejectionCode.KILL_SWITCH_ENGAGED,),
            )

    def test_an_executable_decision_must_approve_something(self) -> None:
        with pytest.raises(ValidationError, match="must approve a size"):
            self.decision(approved_notional_usd=Decimal(0))

    def test_an_executable_decision_must_carry_its_intent(self) -> None:
        with pytest.raises(ValidationError, match="must carry its intent"):
            self.decision(intent_id=None)

    def test_a_reduction_must_actually_reduce(self) -> None:
        with pytest.raises(ValidationError, match="must approve less"):
            self.decision(outcome=RiskOutcome.REDUCED)

    def test_an_approval_is_the_size_that_was_asked_for(self) -> None:
        with pytest.raises(ValidationError, match="the size that was asked for"):
            self.decision(approved_notional_usd=Decimal(40))

    def test_only_a_rejection_forbids_execution(self) -> None:
        assert RiskOutcome.APPROVED.permits_execution
        assert RiskOutcome.REDUCED.permits_execution
        assert not RiskOutcome.REJECTED.permits_execution


class TestInputValidation:
    def test_a_proposal_needs_a_timezone(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            proposal(proposed_at=datetime(2026, 9, 15, 12, 0))

    def test_a_snapshot_needs_a_positive_bid(self) -> None:
        with pytest.raises(ValueError, match="bid must be positive"):
            MarketSnapshot(bid=Decimal(0), observed_at=NOW)

    def test_a_snapshot_needs_a_timezone(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            MarketSnapshot(bid=BID, observed_at=datetime(2026, 9, 15, 12, 0))

    def test_an_intent_needs_timezone_aware_timestamps(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            ExecutionIntent(
                correlation_id="cor_test",
                environment=ExecutionEnvironment.TESTNET,
                asset="BTC",
                side=Side.BUY,
                notional_usd=Decimal(50),
                stop_price=Decimal(59_000),
                issued_at=datetime(2026, 9, 15, 12, 0),
                expires_at=NOW + timedelta(seconds=10),
            )

    def test_a_size_below_the_venue_minimum_is_refused(self) -> None:
        decision = engine().evaluate(proposal(notional_usd=Decimal("0.5")), market=fresh())
        assert decision.outcome is RiskOutcome.REJECTED
        assert RejectionCode.SIZE_BELOW_MINIMUM in decision.reasons

    def test_a_ceiling_below_the_minimum_cannot_be_reduced_into(self) -> None:
        """Reducing to a size the venue would reject is not a reduction."""
        decision = engine(max_order_notional=Decimal("0.5")).evaluate(proposal(), market=fresh())
        assert decision.outcome is RiskOutcome.REJECTED
        assert RejectionCode.SIZE_BELOW_MINIMUM in decision.reasons

    def test_an_issued_intent_reports_itself_issued(self) -> None:
        ledger = IntentLedger()
        intent = ledger.record(
            ExecutionIntent(
                correlation_id="cor_test",
                environment=ExecutionEnvironment.TESTNET,
                asset="BTC",
                side=Side.BUY,
                notional_usd=Decimal(50),
                stop_price=Decimal(59_000),
                issued_at=NOW,
                expires_at=NOW + timedelta(seconds=10),
            )
        )
        assert ledger.state_of(intent.intent_id, at=NOW) is IntentState.ISSUED
        ledger.consume(intent.intent_id, at=NOW)
        assert ledger.state_of(intent.intent_id, at=NOW) is IntentState.CONSUMED

    def test_the_state_of_an_unknown_intent_is_an_error_not_a_guess(self) -> None:
        with pytest.raises(IntentNotFoundError):
            IntentLedger().state_of("int_never_issued", at=NOW)
