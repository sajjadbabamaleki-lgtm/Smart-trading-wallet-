"""The Execution Engine: turns an authorised intent into one order, once.

Invariant 2 is the whole design. Execution acts only on an intent the Risk
Engine issued, and **independently re-validates it** — this layer does not
trust the intent because it arrived, it checks it again, because a component
that assumes an upstream check happened is a component that stops enforcing it
the day the upstream changes (Phase 10 §22-24).

Two properties beyond that matter more than anything else here:

* One intent, one order. The venue order id is derived from the intent id, so
  a retry after a timeout carries the same id the venue already saw. Retrying
  with a fresh id is how a timeout becomes a double position.
* A timeout is not a failure. It moves the order to UNKNOWN and stops. Nothing
  else is decided until the venue has been asked (Invariant 7, Rev.1 §53).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from libs.config import Settings
from libs.domain.clock import Clock, SystemClock
from libs.exchange.models import OrderRequest, OrderState, OrderStatus, OrderType
from services.execution_engine.orders import OrderRecord
from services.risk_engine.intents import (
    ExecutionIntent,
    IntentLedger,
)
from services.risk_engine.models import RejectionCode

# The quantity a venue would round to nothing.
MINIMUM_QUANTITY = Decimal("0.00001")


class IntentRefusedError(Exception):
    """Raised when re-validation rejects an intent the Risk Engine issued.

    Not a redundancy: the intent may have expired between issue and submission,
    or the environment may have changed under a long-lived process.
    """

    def __init__(self, reasons: tuple[RejectionCode, ...]) -> None:
        super().__init__(", ".join(reasons))
        self.reasons = reasons


class VenueTimeout(Exception):  # noqa: N818 - this is a condition, not an error state
    """The adapter could not determine what the venue did with the order."""


class ExecutionEngine:
    """Submits orders for intents, and keeps what it believes about them."""

    __slots__ = ("_clock", "_ledger", "_orders", "_settings")

    def __init__(
        self,
        settings: Settings,
        ledger: IntentLedger,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._settings = settings
        self._ledger = ledger
        self._clock = clock if clock is not None else SystemClock()
        self._orders: dict[str, OrderRecord] = {}

    @property
    def orders(self) -> dict[str, OrderRecord]:
        return self._orders

    @staticmethod
    def client_order_id(intent: ExecutionIntent) -> str:
        """One intent, one order id, for the life of that intent.

        Derived rather than generated: after a timeout the engine must be able
        to re-send or ask about *the same* order, and a random id per attempt
        makes that impossible.
        """
        return f"stw-{intent.intent_id}"

    def revalidate(self, intent: ExecutionIntent, *, at: datetime) -> tuple[RejectionCode, ...]:
        """Check the intent again, on this side of the boundary.

        Expiry is checked here as well as in the ledger. Invariant 2 asks for
        an independent re-validation, and "the ledger will catch it" is exactly
        the assumption that stops being true when the ledger is replaced.
        """
        reasons: list[RejectionCode] = []
        if intent.is_expired_at(at):
            reasons.append(RejectionCode.INTENT_EXPIRED)
        if intent.asset not in self._settings.asset_allowlist:
            reasons.append(RejectionCode.ASSET_NOT_ALLOWED)
        if intent.environment is not self._settings.execution_environment:
            reasons.append(RejectionCode.ENVIRONMENT_FORBIDS_EXECUTION)
        if self._settings.venue_endpoint is None:
            reasons.append(RejectionCode.ENVIRONMENT_FORBIDS_EXECUTION)
        if not self._settings.trading_enabled:
            reasons.append(RejectionCode.KILL_SWITCH_ENGAGED)
        if not self._settings.testnet_api_wallet_private_key:
            reasons.append(RejectionCode.NO_SIGNING_CREDENTIAL)
        if intent.notional_usd > self._settings.max_order_notional:
            reasons.append(RejectionCode.SIZE_ABOVE_LIMIT)
        return tuple(dict.fromkeys(reasons))

    def prepare(self, intent: ExecutionIntent, *, price: Decimal) -> OrderRequest:
        """Consume the intent and build the one order it authorises.

        Consumption happens here, before submission: an intent spent on an
        order that then times out must not be spendable again, or the retry
        path and the fresh-decision path become the same thing.
        """
        now = self._clock.now()
        reasons = self.revalidate(intent, at=now)
        if reasons:
            raise IntentRefusedError(reasons)
        if price <= 0:
            raise ValueError("price must be positive")

        # Expiry and single use are the ledger's to enforce; it raises.
        self._ledger.consume(intent.intent_id, at=now)

        quantity = (intent.notional_usd / price).quantize(MINIMUM_QUANTITY)
        if quantity < MINIMUM_QUANTITY:
            raise IntentRefusedError((RejectionCode.SIZE_BELOW_MINIMUM,))

        request = OrderRequest(
            client_order_id=self.client_order_id(intent),
            intent_id=intent.intent_id,
            correlation_id=intent.correlation_id,
            asset=intent.asset,
            side=intent.side,
            quantity=quantity,
            order_type=OrderType.MARKET,
        )
        record = OrderRecord(
            client_order_id=request.client_order_id,
            intent_id=intent.intent_id,
            correlation_id=intent.correlation_id,
            asset=intent.asset,
            quantity=quantity,
        )
        record.transition(OrderState.VALIDATED, at=now)
        self._orders[request.client_order_id] = record
        return request

    def mark_submitted(self, client_order_id: str) -> OrderRecord:
        record = self._orders[client_order_id]
        record.transition(OrderState.SUBMITTED, at=self._clock.now())
        return record

    def mark_unknown(self, client_order_id: str) -> OrderRecord:
        """A timeout, a dropped socket, a process that died mid-submit.

        The order is not failed and not filled. It is unknown, and it stays
        unknown until the venue answers.
        """
        record = self._orders[client_order_id]
        record.transition(OrderState.UNKNOWN, at=self._clock.now())
        return record

    def apply(self, status: OrderStatus) -> OrderRecord:
        """Record what the venue said about one of our orders.

        Invariant 8: the venue is authoritative. This does not merge the two
        views or prefer the local one — it takes the venue's and refuses only
        transitions the lifecycle forbids, which is how a contradiction becomes
        visible instead of being averaged away.
        """
        record = self._orders[status.client_order_id]
        if status.state is not record.state:
            record.transition(status.state, at=status.observed_at)
        record.venue_order_id = status.venue_order_id or record.venue_order_id
        record.filled_quantity = status.filled_quantity
        record.average_fill_price = status.average_fill_price or record.average_fill_price
        record.reject_reason = status.reject_reason or record.reject_reason
        return record

    @property
    def unresolved(self) -> tuple[OrderRecord, ...]:
        """Orders whose real state nobody knows yet.

        While this is non-empty, Invariant 7 says no new exposure: the system
        cannot size a position it cannot see.
        """
        return tuple(r for r in self._orders.values() if r.needs_reconciliation)
