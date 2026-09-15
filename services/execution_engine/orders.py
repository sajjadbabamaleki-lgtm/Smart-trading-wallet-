"""The order lifecycle, as a state machine that refuses illegal moves.

Build 0.1 Rev.1 §49 defines the states; `OrderState` in `libs.exchange.models`
holds them. What lives here is which transitions are permitted, because the
dangerous bugs in an execution path are not unknown states — they are legal
looking jumps: a FILLED order quietly becoming CANCELLED, or an UNKNOWN one
being treated as REJECTED because that is the convenient assumption.

`UNKNOWN` is the state this module exists for. A timeout does not mean the
order failed; the venue may well have received it (Rev.1 §53, Phase 6 §41).
So UNKNOWN is reachable from anything still in flight, is not terminal, and
leaves only by reconciliation against the venue.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from libs.exchange.models import OrderState

# What may follow what. Absent keys are terminal.
ALLOWED: dict[OrderState, frozenset[OrderState]] = {
    OrderState.CREATED: frozenset({OrderState.VALIDATED, OrderState.REJECTED}),
    OrderState.VALIDATED: frozenset({OrderState.SUBMITTED, OrderState.REJECTED}),
    OrderState.SUBMITTED: frozenset(
        {
            OrderState.ACKNOWLEDGED,
            OrderState.REJECTED,
            OrderState.UNKNOWN,
            # Some venues report a fill before, or instead of, an ack.
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
        }
    ),
    OrderState.ACKNOWLEDGED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_PENDING,
            OrderState.CANCELLED,
            OrderState.EXPIRED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.PARTIALLY_FILLED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_PENDING,
            OrderState.CANCELLED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.CANCEL_PENDING: frozenset(
        {
            OrderState.CANCELLED,
            # A cancel can lose the race with a fill.
            OrderState.FILLED,
            OrderState.PARTIALLY_FILLED,
            OrderState.UNKNOWN,
        }
    ),
    # Not terminal: an unknown order is resolved by asking the venue, and every
    # answer it can give is reachable from here.
    OrderState.UNKNOWN: frozenset(
        {
            OrderState.ACKNOWLEDGED,
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.EXPIRED,
        }
    ),
}


class IllegalTransitionError(Exception):
    """Raised when an order is asked to move somewhere it cannot go."""

    def __init__(self, current: OrderState, requested: OrderState) -> None:
        super().__init__(f"{current} cannot become {requested}")
        self.current = current
        self.requested = requested


class OrderRecord(BaseModel):
    """What this system believes about one order it sent.

    Belief, not truth: Invariant 8 makes the venue authoritative, and this
    record is what reconciliation compares against.
    """

    model_config = ConfigDict(extra="forbid")

    client_order_id: str
    intent_id: str
    correlation_id: str
    asset: str
    quantity: Decimal = Field(gt=0)
    state: OrderState = OrderState.CREATED
    venue_order_id: str | None = None
    filled_quantity: Decimal = Decimal(0)
    average_fill_price: Decimal | None = None
    reject_reason: str | None = None
    history: tuple[tuple[OrderState, datetime], ...] = ()

    def can_become(self, state: OrderState) -> bool:
        return state in ALLOWED.get(self.state, frozenset())

    def transition(self, state: OrderState, *, at: datetime) -> None:
        """Move to `state`, or refuse and leave the record untouched."""
        if not self.can_become(state):
            raise IllegalTransitionError(self.state, state)
        self.state = state
        self.history = (*self.history, (state, at))

    @property
    def needs_reconciliation(self) -> bool:
        """Whether the venue must be asked before anything else is decided.

        Invariant 7: when the state of an order is unknown, the answer is no
        new risk until it is known.
        """
        return self.state is OrderState.UNKNOWN
