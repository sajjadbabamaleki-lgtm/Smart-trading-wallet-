"""Trader event — an action attributable to a pseudonymous entity.

This schema exists in M0 so that the recorder built in M2 has somewhere to put
identity-linked fields it happens to receive. That is the whole point: bounded
API history (2,000 fills per response, 10,000 most recent) and an archive that
uploads roughly monthly with no completeness guarantee mean information
discarded today may be unreconstructable later (TBIE v1.1 §32, §33, §56).

Recording these fields is not an endorsement of the trader-behaviour
hypothesis. TBIE holds no production authority, its latency viability is
untested, and it is not on the Build 0.1 critical path (TBIE v1.1 §57, §72).
Preserving optionality is cheap; recreating lost history is not.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from libs.domain.timestamps import EventTimestamps
from libs.schemas.enums import DataQualityStatus, PitStatus, Side, TraderEventType

SCHEMA_VERSION = 1


class TraderEvent(BaseModel):
    """One observable action by a pseudonymous trading entity.

    `wallet` is a behavioural identifier, never a verified human trader: one
    person may run many wallets and one wallet may change hands, so wallet
    counts are not people counts (TBIE v1.1 §54). Any clustering of wallets into
    entities is separate research requiring its own validation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    schema_version: int = Field(default=SCHEMA_VERSION)
    source: str
    venue: str
    asset: str
    instrument: str
    event_type: TraderEventType
    timestamps: EventTimestamps

    wallet: str = Field(description="Pseudonymous behavioural identifier, not an identity.")
    counterparty: str | None = Field(
        default=None, description="Other side of the trade, where the venue exposes it."
    )
    side: Side | None = None
    price: Decimal | None = None
    quantity: Decimal | None = None
    notional: Decimal | None = None

    order_id: str | None = None
    client_order_id: str | None = Field(default=None, description="Venue 'cloid', where present.")
    twap_id: str | None = Field(
        default=None,
        description=(
            "Set when the action belongs to a visible TWAP programme. Kept "
            "separate because TWAP and liquidation flow are excluded from "
            "skill scoring, and because visible TWAP behaves differently from "
            "reconstructed hidden metaorders (TBIE v1.1 §7, §31)."
        ),
    )
    start_position: Decimal | None = Field(
        default=None, description="Signed position before the event, where exposed."
    )
    end_position: Decimal | None = Field(
        default=None, description="Signed position after the event, where exposed."
    )

    raw_reference: str | None = None
    quality_status: DataQualityStatus = DataQualityStatus.UNKNOWN
    pit_status: PitStatus = PitStatus.PIT_SAFE

    @model_validator(mode="after")
    def _check_required_fields_for_type(self) -> TraderEvent:
        if self.event_type is TraderEventType.FILL:
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
                raise ValueError(f"FILL event requires {', '.join(missing)}")
        return self

    @model_validator(mode="after")
    def _check_values_are_possible(self) -> TraderEvent:
        if self.price is not None and self.price <= 0:
            raise ValueError(f"price must be positive, got {self.price}")
        for name in ("quantity", "notional"):
            value: Decimal | None = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative, got {value}")
        return self

    @property
    def is_excluded_from_skill_scoring(self) -> bool:
        """Whether this event must be left out of wallet skill estimation.

        TWAP programmes and liquidations are excluded in the primary study's
        scoring design (TBIE v1.1 §7): a liquidation is not a decision by the
        wallet, and a TWAP slice reflects a schedule rather than a view on the
        next few seconds. Counting either as evidence of skill measures the
        wrong thing.
        """
        return self.twap_id is not None or self.event_type is TraderEventType.LIQUIDATION
