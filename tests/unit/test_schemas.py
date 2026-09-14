"""Canonical event schemas."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from libs.domain.timestamps import EventTimestamps
from libs.schemas import MarketEvent, TraderEvent
from libs.schemas.enums import (
    DataQualityStatus,
    ExecutionEnvironment,
    MarketEventType,
    PitStatus,
    Side,
    TraderEventType,
)


def _market(stamps: EventTimestamps, **kwargs: Any) -> MarketEvent:
    base = {
        "event_id": "evt_1",
        "source": "hyperliquid_ws",
        "venue": "hyperliquid",
        "asset": "BTC",
        "instrument": "BTC-PERP",
        "timestamps": stamps,
    }
    return MarketEvent(**{**base, **kwargs})


def _trader(stamps: EventTimestamps, **kwargs: Any) -> TraderEvent:
    base = {
        "event_id": "evt_1",
        "source": "hyperliquid_ws",
        "venue": "hyperliquid",
        "asset": "BTC",
        "instrument": "BTC-PERP",
        "wallet": "0xabc",
        "timestamps": stamps,
    }
    return TraderEvent(**{**base, **kwargs})


class TestEnums:
    def test_side_sign_drives_signed_measures(self) -> None:
        assert Side.BUY.sign == 1
        assert Side.SELL.sign == -1

    def test_only_limited_live_and_production_reach_real_capital(self) -> None:
        reaching = {env for env in ExecutionEnvironment if env.reaches_real_capital}
        assert reaching == {
            ExecutionEnvironment.LIMITED_LIVE,
            ExecutionEnvironment.PRODUCTION,
        }

    def test_unknown_quality_is_not_usable_for_training(self) -> None:
        assert DataQualityStatus.VALID.usable_for_training
        for status in (
            DataQualityStatus.WARNING,
            DataQualityStatus.INVALID,
            DataQualityStatus.UNKNOWN,
        ):
            assert not status.usable_for_training

    def test_only_pit_safe_passes_strict_validation(self) -> None:
        assert PitStatus.PIT_SAFE.usable_for_strict_validation
        assert not PitStatus.PIT_APPROXIMATE.usable_for_strict_validation
        assert not PitStatus.NON_PIT.usable_for_strict_validation


class TestMarketEvent:
    def test_schema_version_is_recorded(self, timestamps: EventTimestamps) -> None:
        event = _market(timestamps, event_type=MarketEventType.ASSET_CONTEXT)
        assert event.schema_version == 1

    def test_quality_defaults_to_unknown_not_valid(self, timestamps: EventTimestamps) -> None:
        """Unvalidated data must not present itself as validated."""
        event = _market(timestamps, event_type=MarketEventType.ASSET_CONTEXT)
        assert event.quality_status is DataQualityStatus.UNKNOWN

    def test_trade_requires_price_quantity_and_side(self, timestamps: EventTimestamps) -> None:
        with pytest.raises(ValidationError, match="TRADE event requires"):
            _market(timestamps, event_type=MarketEventType.TRADE, price=Decimal("60000"))

    def test_valid_trade_is_accepted(self, timestamps: EventTimestamps) -> None:
        event = _market(
            timestamps,
            event_type=MarketEventType.TRADE,
            price=Decimal("60000.5"),
            quantity=Decimal("0.01"),
            side=Side.BUY,
        )
        assert event.price == Decimal("60000.5")

    def test_funding_requires_a_rate(self, timestamps: EventTimestamps) -> None:
        with pytest.raises(ValidationError, match="FUNDING event requires"):
            _market(timestamps, event_type=MarketEventType.FUNDING)

    def test_negative_funding_rate_is_allowed(self, timestamps: EventTimestamps) -> None:
        """Funding is legitimately negative when shorts pay longs."""
        event = _market(
            timestamps,
            event_type=MarketEventType.FUNDING,
            funding_rate=Decimal("-0.0001"),
        )
        assert event.funding_rate is not None
        assert event.funding_rate < 0

    def test_bbo_requires_at_least_one_side(self, timestamps: EventTimestamps) -> None:
        with pytest.raises(ValidationError, match="BBO event requires"):
            _market(timestamps, event_type=MarketEventType.BBO)

    def test_impossible_price_is_rejected(self, timestamps: EventTimestamps) -> None:
        with pytest.raises(ValidationError, match="must be positive"):
            _market(
                timestamps,
                event_type=MarketEventType.TRADE,
                price=Decimal(0),
                quantity=Decimal("0.01"),
                side=Side.BUY,
            )

    def test_negative_quantity_is_rejected(self, timestamps: EventTimestamps) -> None:
        with pytest.raises(ValidationError, match="must not be negative"):
            _market(
                timestamps,
                event_type=MarketEventType.TRADE,
                price=Decimal("60000"),
                quantity=Decimal("-1"),
                side=Side.BUY,
            )

    def test_crossed_book_is_rejected(self, timestamps: EventTimestamps) -> None:
        with pytest.raises(ValidationError, match="crossed book"):
            _market(
                timestamps,
                event_type=MarketEventType.BBO,
                bid_price=Decimal("60001"),
                ask_price=Decimal("60000"),
            )

    def test_mid_price_computed_only_when_both_sides_quoted(
        self, timestamps: EventTimestamps
    ) -> None:
        both = _market(
            timestamps,
            event_type=MarketEventType.BBO,
            bid_price=Decimal("59999"),
            ask_price=Decimal("60001"),
        )
        assert both.mid_price == Decimal("60000")

        one_side = _market(timestamps, event_type=MarketEventType.BBO, bid_price=Decimal("59999"))
        assert one_side.mid_price is None

    def test_prices_keep_exact_decimal_precision(self, timestamps: EventTimestamps) -> None:
        """A float would lose the venue's tick, unrecoverably once stored."""
        event = _market(
            timestamps,
            event_type=MarketEventType.TRADE,
            price=Decimal("60000.123456789"),
            quantity=Decimal("0.000000001"),
            side=Side.SELL,
        )
        assert str(event.price) == "60000.123456789"

    def test_unknown_field_is_rejected(self, timestamps: EventTimestamps) -> None:
        with pytest.raises(ValidationError):
            _market(timestamps, event_type=MarketEventType.ASSET_CONTEXT, unexpected="x")

    def test_event_is_immutable(self, timestamps: EventTimestamps) -> None:
        event = _market(timestamps, event_type=MarketEventType.ASSET_CONTEXT)
        with pytest.raises(ValidationError):
            event.asset = "ETH"  # type: ignore[misc]


class TestTraderEvent:
    def test_identity_fields_are_optional(self, timestamps: EventTimestamps) -> None:
        """A source that does not expose a field leaves it empty."""
        event = _trader(timestamps, event_type=TraderEventType.POSITION_CHANGE)
        assert event.counterparty is None
        assert event.start_position is None
        assert event.twap_id is None

    def test_fill_requires_price_quantity_and_side(self, timestamps: EventTimestamps) -> None:
        with pytest.raises(ValidationError, match="FILL event requires"):
            _trader(timestamps, event_type=TraderEventType.FILL, price=Decimal("60000"))

    def test_identity_linked_fields_are_preserved(self, timestamps: EventTimestamps) -> None:
        event = _trader(
            timestamps,
            event_type=TraderEventType.FILL,
            side=Side.BUY,
            price=Decimal("60000"),
            quantity=Decimal("0.5"),
            counterparty="0xdef",
            order_id="o-1",
            client_order_id="cloid-1",
            start_position=Decimal("-0.5"),
            end_position=Decimal(0),
        )
        assert event.counterparty == "0xdef"
        assert event.start_position == Decimal("-0.5")

    def test_twap_slices_are_excluded_from_skill_scoring(self, timestamps: EventTimestamps) -> None:
        event = _trader(
            timestamps,
            event_type=TraderEventType.FILL,
            side=Side.BUY,
            price=Decimal("60000"),
            quantity=Decimal("0.1"),
            twap_id="twap-7",
        )
        assert event.is_excluded_from_skill_scoring

    def test_liquidations_are_excluded_from_skill_scoring(
        self, timestamps: EventTimestamps
    ) -> None:
        """A liquidation is not a decision by the wallet."""
        event = _trader(timestamps, event_type=TraderEventType.LIQUIDATION)
        assert event.is_excluded_from_skill_scoring

    def test_ordinary_fill_is_included_in_skill_scoring(self, timestamps: EventTimestamps) -> None:
        event = _trader(
            timestamps,
            event_type=TraderEventType.FILL,
            side=Side.SELL,
            price=Decimal("60000"),
            quantity=Decimal("0.1"),
        )
        assert not event.is_excluded_from_skill_scoring

    def test_short_position_is_representable(self, timestamps: EventTimestamps) -> None:
        """Positions are signed; only quantities are non-negative."""
        event = _trader(
            timestamps,
            event_type=TraderEventType.POSITION_CHANGE,
            start_position=Decimal(0),
            end_position=Decimal("-2.5"),
        )
        assert event.end_position == Decimal("-2.5")
