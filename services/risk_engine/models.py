"""What the Risk Engine is asked, and what it answers.

Invariant 1 gives this layer the only authority to permit a trade: the
Strategy Engine proposes, the Risk Engine approves, reduces or rejects, and
that decision cannot be reversed by the proposer. So a proposal and a decision
are separate types — nothing in the system can mistake one for the other, and a
proposal carries no field that could be read as permission.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from libs.schemas.enums import Side


class RiskOutcome(StrEnum):
    """The three answers Invariant 1 allows."""

    APPROVED = "APPROVED"
    REDUCED = "REDUCED"
    REJECTED = "REJECTED"

    @property
    def permits_execution(self) -> bool:
        return self is not RiskOutcome.REJECTED


class RejectionCode(StrEnum):
    """Why a proposal was refused or cut down.

    Coded rather than free text: these are audited, counted, and asserted on in
    tests, and a sentence that someone reworded later would break all three.
    """

    ASSET_NOT_ALLOWED = "ASSET_NOT_ALLOWED"
    ENVIRONMENT_FORBIDS_EXECUTION = "ENVIRONMENT_FORBIDS_EXECUTION"
    KILL_SWITCH_ENGAGED = "KILL_SWITCH_ENGAGED"
    NO_SIGNING_CREDENTIAL = "NO_SIGNING_CREDENTIAL"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    MARKET_DATA_MISSING = "MARKET_DATA_MISSING"
    NO_STOP_LOSS = "NO_STOP_LOSS"
    STOP_ON_WRONG_SIDE = "STOP_ON_WRONG_SIDE"
    TAKE_PROFIT_ON_WRONG_SIDE = "TAKE_PROFIT_ON_WRONG_SIDE"
    SIZE_ABOVE_LIMIT = "SIZE_ABOVE_LIMIT"
    SIZE_BELOW_MINIMUM = "SIZE_BELOW_MINIMUM"
    DUPLICATE_PROPOSAL = "DUPLICATE_PROPOSAL"
    # Raised on the execution side, where the intent is checked again.
    INTENT_EXPIRED = "INTENT_EXPIRED"


class TradeProposal(BaseModel):
    """What a strategy would like to do.

    Invariant 6: no position opens without entry, size, stop and exit logic, so
    the stop is a required field rather than an optional refinement. A proposal
    that cannot state its downside cannot be evaluated, and the type says so
    before the engine is ever called.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: str
    asset: str
    side: Side
    notional_usd: Decimal = Field(gt=0)
    stop_price: Decimal = Field(gt=0)
    take_profit_price: Decimal | None = Field(default=None, gt=0)
    proposed_at: datetime

    @model_validator(mode="after")
    def _require_utc(self) -> TradeProposal:
        if self.proposed_at.tzinfo is None:
            raise ValueError("proposed_at must be timezone-aware")
        return self

    @property
    def fingerprint(self) -> str:
        """Identity for duplicate detection.

        Deliberately excludes the timestamp and the correlation id: the same
        trade proposed twice a second apart under two ids is exactly the
        duplicate this is meant to catch (Rev.2 §17).
        """
        return f"{self.asset}|{self.side}|{self.notional_usd}|{self.stop_price}"


class RiskDecision(BaseModel):
    """The engine's answer, and the reasons for it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: RiskOutcome
    correlation_id: str
    requested_notional_usd: Decimal
    approved_notional_usd: Decimal
    reasons: tuple[RejectionCode, ...] = ()
    decided_at: datetime
    intent_id: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> RiskDecision:
        if self.outcome is RiskOutcome.REJECTED:
            if self.approved_notional_usd != 0:
                raise ValueError("a rejected decision approves nothing")
            if not self.reasons:
                raise ValueError("a rejection must say why")
            if self.intent_id is not None:
                raise ValueError("a rejected decision issues no intent")
        else:
            if self.approved_notional_usd <= 0:
                raise ValueError("an executable decision must approve a size")
            if self.intent_id is None:
                raise ValueError("an executable decision must carry its intent")
        if self.outcome is RiskOutcome.REDUCED and (
            self.approved_notional_usd >= self.requested_notional_usd
        ):
            raise ValueError("a reduced decision must approve less than was asked")
        if self.outcome is RiskOutcome.APPROVED and (
            self.approved_notional_usd != self.requested_notional_usd
        ):
            raise ValueError("an approved decision is the size that was asked for")
        return self
