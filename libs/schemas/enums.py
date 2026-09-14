"""Enumerations used across schemas and configuration."""

from __future__ import annotations

from enum import StrEnum


class ExecutionEnvironment(StrEnum):
    """Where orders, if any, would actually go.

    The order of these members is the validation ladder from Phase 7 and Phase 8.
    Build 0.1 permits only the first two; see `libs.config.settings`.
    """

    DEVELOPMENT = "DEVELOPMENT"
    TESTNET = "TESTNET"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    LIMITED_LIVE = "LIMITED_LIVE"
    PRODUCTION = "PRODUCTION"

    @property
    def reaches_real_capital(self) -> bool:
        """Whether orders in this environment can move real money."""
        return self in (ExecutionEnvironment.LIMITED_LIVE, ExecutionEnvironment.PRODUCTION)


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        """+1 for a buy, -1 for a sell.

        Used by signed measures such as markout, where the question is whether
        price moved in the aggressor's direction (TBIE v1.1 §6).
        """
        return 1 if self is Side.BUY else -1


class MarketEventType(StrEnum):
    TRADE = "TRADE"
    BBO = "BBO"
    L2_SNAPSHOT = "L2_SNAPSHOT"
    L2_UPDATE = "L2_UPDATE"
    FUNDING = "FUNDING"
    OPEN_INTEREST = "OPEN_INTEREST"
    MARK_PRICE = "MARK_PRICE"
    ORACLE_PRICE = "ORACLE_PRICE"
    ASSET_CONTEXT = "ASSET_CONTEXT"


class TraderEventType(StrEnum):
    """Observable actions of a pseudonymous entity.

    The richer members (rejections, failed cancellations) are recorded only when
    the data path in use exposes them. They are listed here so the schema does
    not have to change later, not because Build 0.1 ingests them — TBIE v1.1
    §30 explicitly declines to justify ingesting every rejected order.
    """

    FILL = "FILL"
    ORDER_PLACED = "ORDER_PLACED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    CANCEL_FAILED = "CANCEL_FAILED"
    POSITION_CHANGE = "POSITION_CHANGE"
    LIQUIDATION = "LIQUIDATION"


class DataQualityStatus(StrEnum):
    """Outcome of validation for one event or batch (Build 0.1 Rev.1 §34)."""

    VALID = "VALID"
    WARNING = "WARNING"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"

    @property
    def usable_for_training(self) -> bool:
        """Only VALID data may enter a training dataset.

        UNKNOWN is deliberately excluded: unknown quality must never silently
        become valid research data (Build 0.1 Rev.2 §21).
        """
        return self is DataQualityStatus.VALID


class PitStatus(StrEnum):
    """Point-in-time integrity of a record or derived feature.

    Phase 3 §7 introduced this for on-chain entity labels, where a provider may
    reclassify a historical address today and thereby leak information backwards
    into a backtest. The same classification applies to any field whose meaning
    can be revised after the fact.
    """

    PIT_SAFE = "PIT_SAFE"
    PIT_APPROXIMATE = "PIT_APPROXIMATE"
    NON_PIT = "NON_PIT"

    @property
    def usable_for_strict_validation(self) -> bool:
        return self is PitStatus.PIT_SAFE
