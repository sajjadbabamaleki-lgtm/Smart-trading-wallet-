"""Venue-neutral execution models.

These types are the vocabulary the Risk and Execution layers speak. They carry
no Hyperliquid-specific field, so adding a second venue later does not require
rewriting the Strategy, Risk, Portfolio or Research layers
(Build 0.1 Rev.2 §12-13).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from libs.schemas.enums import Side


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    ALO = "ALO"
    """Add-liquidity-only / post-only: rejected rather than crossing the spread."""


class OrderState(StrEnum):
    """Lifecycle of an order (Build 0.1 Rev.1 §49).

    `UNKNOWN` is a real state, not an error path. A network timeout does not
    mean the order failed — the venue may well have received it — so the system
    must be able to represent "we do not know" and reconcile, rather than
    assume (Build 0.1 Rev.1 §53, Phase 6 §41).
    """

    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"

    @property
    def is_terminal(self) -> bool:
        """Whether no further transition is expected.

        `UNKNOWN` is not terminal: it demands reconciliation.
        """
        return self in (
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.EXPIRED,
        )


class MarketState(BaseModel):
    """Snapshot of one instrument, as the adapter observed it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    asset: str
    instrument: str
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    mark_price: Decimal | None = None
    oracle_price: Decimal | None = None
    funding_rate: Decimal | None = None
    open_interest: Decimal | None = None
    observed_at: datetime
    local_receive_monotonic_ns: int

    @property
    def mid_price(self) -> Decimal | None:
        if self.bid_price is None or self.ask_price is None:
            return None
        return (self.bid_price + self.ask_price) / 2

    @property
    def spread_bps(self) -> Decimal | None:
        """Quoted spread in basis points, when both sides are quoted."""
        mid = self.mid_price
        if mid is None or self.bid_price is None or self.ask_price is None or mid == 0:
            return None
        return (self.ask_price - self.bid_price) / mid * Decimal(10_000)


class Position(BaseModel):
    """An open position. `size` is signed: positive long, negative short."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    asset: str
    size: Decimal
    entry_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    liquidation_price: Decimal | None = None
    leverage: Decimal | None = None
    margin_used: Decimal | None = None

    @property
    def side(self) -> Side | None:
        if self.size == 0:
            return None
        return Side.BUY if self.size > 0 else Side.SELL


class AccountState(BaseModel):
    """Venue-side account truth.

    The venue is authoritative for actual exposure; internal state reconciles
    against this rather than the reverse (Phase 6 §45, Phase 8 §53).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    equity: Decimal
    available_margin: Decimal
    positions: tuple[Position, ...] = ()
    observed_at: datetime


class OrderRequest(BaseModel):
    """An order to submit.

    Carries `intent_id` and `correlation_id` so that every venue order traces
    back to the risk decision that authorised it (Build 0.1 Rev.1 §42, §50).
    An adapter must refuse a request without them rather than invent an order
    with no provenance.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_order_id: str
    intent_id: str
    correlation_id: str
    asset: str
    side: Side
    quantity: Decimal = Field(gt=0)
    order_type: OrderType
    limit_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False

    @model_validator(mode="after")
    def _check_limit_price(self) -> OrderRequest:
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("LIMIT order requires limit_price")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("MARKET order must not carry limit_price")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError(f"limit_price must be positive, got {self.limit_price}")
        if self.order_type is OrderType.MARKET and self.time_in_force is TimeInForce.ALO:
            raise ValueError("MARKET order cannot be add-liquidity-only")
        return self


class OrderStatus(BaseModel):
    """Current known state of a submitted order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_order_id: str
    venue_order_id: str | None = None
    state: OrderState
    filled_quantity: Decimal = Decimal(0)
    average_fill_price: Decimal | None = None
    reject_reason: str | None = None
    observed_at: datetime


class Fill(BaseModel):
    """One execution against one of our orders.

    Fees are recorded as reported by the venue rather than estimated: Phase 8
    §17 requires real fee accounting, and a fee tier can move with rolling
    volume.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fill_id: str
    client_order_id: str | None = None
    venue_order_id: str | None = None
    asset: str
    side: Side
    price: Decimal
    quantity: Decimal
    fee: Decimal | None = None
    is_maker: bool | None = None
    filled_at: datetime
    local_receive_monotonic_ns: int | None = None
