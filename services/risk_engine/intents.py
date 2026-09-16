"""Execution intents: the only thing the Execution Engine may act on.

Invariant 2 states the rule this module exists to enforce — execution acts only
on an immutable, expiring, single-use intent issued here, and a consumed or
expired intent cannot open a position. All three properties are mechanical:
immutability from a frozen model, expiry from a deadline carried on the intent
itself, and single use from a ledger that refuses a second consumption.

The ledger is in-memory for M7. Its interface is the one a PostgreSQL-backed
ledger will implement at M8, where surviving a process restart starts to matter
(Build 0.1 Rev.1 §53).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from libs.domain.ids import new_intent_id
from libs.schemas.enums import ExecutionEnvironment, Side


class IntentState(StrEnum):
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class ExecutionIntent(BaseModel):
    """Permission to place one order, for a limited time, once.

    Carries the exits with it. The stop is not advice the Execution Engine may
    apply later if convenient: it is part of what was authorised, so an
    execution path that submits the entry without it is submitting something
    the Risk Engine never approved (Invariant 6).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_id: str = Field(default_factory=new_intent_id)
    correlation_id: str
    environment: ExecutionEnvironment
    asset: str
    side: Side
    notional_usd: Decimal = Field(gt=0)
    stop_price: Decimal = Field(gt=0)
    take_profit_price: Decimal | None = Field(default=None, gt=0)
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _check_window(self) -> ExecutionIntent:
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("intent timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ValueError("an intent that expires at or before issue authorises nothing")
        if self.environment.reaches_real_capital:
            # Invariant: mainnet execution is structurally blocked in Build 0.1.
            # Refusing here as well as in configuration means a mis-set
            # environment cannot produce a usable intent even if it reaches
            # this far.
            raise ValueError(f"{self.environment} may not be authorised in Build 0.1")
        return self

    def is_expired_at(self, moment: datetime) -> bool:
        return moment >= self.expires_at


class IntentExpiredError(Exception):
    """Raised when execution is attempted on an intent past its deadline."""


class IntentAlreadyConsumedError(Exception):
    """Raised on the second attempt to execute one intent."""


class IntentNotFoundError(Exception):
    """Raised when execution is attempted on an intent this ledger never issued."""


class IntentLedger:
    """Issues intents and permits each to be consumed exactly once."""

    __slots__ = ("_consumed", "_issued")

    def __init__(self) -> None:
        self._issued: dict[str, ExecutionIntent] = {}
        self._consumed: set[str] = set()

    def record(self, intent: ExecutionIntent) -> ExecutionIntent:
        """Take an intent under this ledger's control.

        The Risk Engine builds the intent, because the policy that decides its
        contents is the engine's; the ledger owns only whether it has been
        spent. Keeping the two apart means a future ledger backed by
        PostgreSQL changes where issuance is written down, not what an intent
        is allowed to say.
        """
        self._issued[intent.intent_id] = intent
        return intent

    def consume(self, intent_id: str, *, at: datetime) -> ExecutionIntent:
        """Spend an intent, or refuse and say which rule refused it.

        Expiry is checked before consumption is recorded, so an expired intent
        stays unconsumed: the reason it cannot be used is that it is too old,
        and that must not decay into "already used" on a later attempt.
        """
        intent = self._issued.get(intent_id)
        if intent is None:
            raise IntentNotFoundError(intent_id)
        if intent_id in self._consumed:
            raise IntentAlreadyConsumedError(intent_id)
        if intent.is_expired_at(at):
            raise IntentExpiredError(intent_id)
        self._consumed.add(intent_id)
        return intent

    def issued(self, intent_id: str) -> ExecutionIntent:
        """Read an intent back without spending it.

        The Risk Engine returns a decision carrying an intent id, not the
        intent, so a caller holding a decision has no way to reach the thing it
        authorises. This is that way, and it is deliberately read-only:
        `consume` is still the only path that spends one.
        """
        intent = self._issued.get(intent_id)
        if intent is None:
            raise IntentNotFoundError(intent_id)
        return intent

    def state_of(self, intent_id: str, *, at: datetime) -> IntentState:
        intent = self._issued.get(intent_id)
        if intent is None:
            raise IntentNotFoundError(intent_id)
        if intent_id in self._consumed:
            return IntentState.CONSUMED
        return IntentState.EXPIRED if intent.is_expired_at(at) else IntentState.ISSUED
