"""Normalized market event."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from libs.domain.timestamps import EventTimestamps
from libs.schemas.enums import DataQualityStatus, MarketEventType, PitStatus, Side

SCHEMA_VERSION = 1


class MarketEvent(BaseModel):
    """One normalized market event.

    Prices and sizes are `Decimal`, not `float`: a float cannot represent a
    venue's tick size exactly, and rounding drift in stored market data is
    unrecoverable once written.

    Not every field applies to every event type (Build 0.1 Rev.1 §19), so most
    are optional — but the combinations that *must* hold are enforced below
    rather than left to the caller.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    schema_version: int = Field(default=SCHEMA_VERSION)
    source: str = Field(description="Which collector produced this record.")
    venue: str
    asset: str
    instrument: str
    event_type: MarketEventType
    timestamps: EventTimestamps

    sequence: int | None = Field(
        default=None, description="Venue sequence number, where one is published."
    )
    price: Decimal | None = None
    quantity: Decimal | None = None
    side: Side | None = None
    bid_price: Decimal | None = None
    bid_quantity: Decimal | None = None
    ask_price: Decimal | None = None
    ask_quantity: Decimal | None = None
    funding_rate: Decimal | None = None
    open_interest: Decimal | None = None

    raw_reference: str | None = Field(
        default=None,
        description=(
            "Pointer to the preserved raw message this was normalized from. A "
            "normalization defect must never destroy the original evidence "
            "(Build 0.1 Rev.2 §20), so this is how a record is re-derived."
        ),
    )
    quality_status: DataQualityStatus = DataQualityStatus.UNKNOWN
    pit_status: PitStatus = PitStatus.PIT_SAFE

    @model_validator(mode="after")
    def _check_required_fields_for_type(self) -> MarketEvent:
        if self.event_type is MarketEventType.TRADE:
            missing = [
                name
                for name, value in (
                    ("price", self.price),
                    ("quantity", self.quantity),
                    ("side", self.side),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"TRADE event requires {', '.join(missing)}")
        if (
            self.event_type is MarketEventType.BBO
            and self.bid_price is None
            and self.ask_price is None
        ):
            raise ValueError("BBO event requires at least one of bid_price, ask_price")
        if self.event_type is MarketEventType.FUNDING and self.funding_rate is None:
            raise ValueError("FUNDING event requires funding_rate")
        return self

    @model_validator(mode="after")
    def _check_values_are_possible(self) -> MarketEvent:
        for name in ("price", "bid_price", "ask_price"):
            value: Decimal | None = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive, got {value}")
        for name in ("quantity", "bid_quantity", "ask_quantity", "open_interest"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative, got {value}")
        if (
            self.bid_price is not None
            and self.ask_price is not None
            and self.bid_price > self.ask_price
        ):
            raise ValueError(f"crossed book: bid {self.bid_price} above ask {self.ask_price}")
        return self

    @property
    def mid_price(self) -> Decimal | None:
        """Midpoint, when both sides are quoted."""
        if self.bid_price is None or self.ask_price is None:
            return None
        return (self.bid_price + self.ask_price) / 2
