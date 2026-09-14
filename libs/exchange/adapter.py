"""The `ExchangeAdapter` contract.

Hyperliquid is the first venue, and must not become the trading system itself
(Build 0.1 Rev.2 §12). Everything venue-specific — endpoints, signing, message
shapes, rate limits — lives behind an implementation of this protocol, so the
layers above it are written against a contract rather than against a venue.

A `Protocol` rather than an abstract base class: an implementation need not
inherit anything, which keeps a test double trivial to write and keeps the
dependency pointing from the adapter to the contract rather than the reverse
(Build 0.1 Rev.1 §68).

Two rules bind every implementation:

- **No direct orders.** Callers never reach `place_order` from application
  code. Orders flow scenario or strategy -> execution intent -> Execution
  Engine -> adapter (Build 0.1 Rev.1 §48). The contract is shaped for that
  path: `place_order` takes an `OrderRequest`, which cannot be constructed
  without an `intent_id`.
- **Idempotency.** `client_order_id` is supplied by the caller and must be
  honoured. A retry after a timeout must never create a second position
  (Phase 6 §41, Build 0.1 Rev.1 §53).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from libs.exchange.models import (
    AccountState,
    Fill,
    MarketState,
    OrderRequest,
    OrderStatus,
    Position,
)


@runtime_checkable
class ExchangeAdapter(Protocol):
    """Venue operations required by the Execution Engine."""

    @property
    def venue(self) -> str:
        """Venue identifier, recorded on every event this adapter produces."""
        ...

    async def get_market_state(self, asset: str) -> MarketState:
        """Current observable state of one instrument."""
        ...

    async def get_account_state(self) -> AccountState:
        """Venue-side account truth, including open positions."""
        ...

    async def place_order(self, request: OrderRequest) -> OrderStatus:
        """Submit an order.

        Must be idempotent on `request.client_order_id`. On an ambiguous
        outcome — timeout, connection loss — implementations return
        `OrderState.UNKNOWN` rather than guessing; the caller then reconciles.
        Raising an exception that hides a possibly-live order is a defect.
        """
        ...

    async def cancel_order(self, client_order_id: str) -> OrderStatus:
        """Request cancellation. Cancelling an unknown order is not an error."""
        ...

    async def get_orders(self) -> tuple[OrderStatus, ...]:
        """All open orders known to the venue, for reconciliation."""
        ...

    async def get_positions(self) -> tuple[Position, ...]:
        """All open positions known to the venue, for reconciliation."""
        ...

    async def get_fills(self, *, since: str | None = None) -> tuple[Fill, ...]:
        """Recent fills.

        `since` is an opaque venue cursor. Callers must not assume complete
        history is retrievable: Hyperliquid's API exposes only the 10,000 most
        recent fills, 2,000 per response (TBIE v1.1 §32), which is precisely why
        the platform runs its own recorder.
        """
        ...

    def subscribe_events(self, assets: tuple[str, ...]) -> AsyncIterator[object]:
        """Stream of venue events for the given assets.

        Yields raw, venue-shaped messages. Normalization is the recorder's
        responsibility, so the preserved raw message stays the authority a
        normalization defect can be re-derived from (Build 0.1 Rev.2 §20).
        """
        ...
