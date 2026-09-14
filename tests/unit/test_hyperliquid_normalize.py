"""Normalizing Hyperliquid frames to canonical events."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from libs.domain.timestamps import EventTimestamps
from libs.exchange.hyperliquid.messages import parse_message
from libs.exchange.hyperliquid.normalize import NormalizationError, normalize
from libs.schemas.enums import MarketEventType, Side, TraderEventType
from libs.schemas.market_event import MarketEvent
from libs.schemas.trader_event import TraderEvent

RECEIPT = EventTimestamps(
    local_receive_time=datetime(2026, 9, 14, 12, 0, 0, 500000, tzinfo=UTC),
    local_receive_monotonic_ns=1_000_000,
)
VENUE_MS = 1757851200000  # 2025-09-14T12:00:00Z


def norm(
    payload: str,
) -> tuple[tuple[MarketEvent, ...], tuple[TraderEvent, ...]]:
    return normalize(parse_message(payload), RECEIPT)


class TestTrades:
    def test_a_trade_becomes_one_market_event(self) -> None:
        market, _ = norm(
            f'{{"channel":"trades","data":[{{"coin":"BTC","side":"B","px":"60000.5",'
            f'"sz":"0.01","time":{VENUE_MS},"hash":"0xaa","tid":1001}}]}}'
        )
        assert len(market) == 1
        event = market[0]
        assert event.event_type is MarketEventType.TRADE
        assert event.asset == "BTC"
        assert event.instrument == "BTC-PERP"
        assert event.venue == "hyperliquid"
        assert event.side is Side.BUY
        assert event.price == Decimal("60000.5")
        assert event.sequence == 1001

    def test_both_venue_time_and_receipt_time_are_carried(self) -> None:
        """Only our receipt time is ours to measure (ADR-007)."""
        market, _ = norm(
            f'{{"channel":"trades","data":[{{"coin":"BTC","side":"B","px":"1","sz":"1",'
            f'"time":{VENUE_MS}}}]}}'
        )
        stamps = market[0].timestamps
        assert stamps.exchange_time == datetime(2025, 9, 14, 12, 0, 0, tzinfo=UTC)
        assert stamps.local_receive_time == RECEIPT.local_receive_time
        assert stamps.local_receive_monotonic_ns == 1_000_000

    def test_identified_trades_produce_one_trader_event_per_wallet(self) -> None:
        market, traders = norm(
            f'{{"channel":"trades","data":[{{"coin":"BTC","side":"B","px":"60000",'
            f'"sz":"0.5","time":{VENUE_MS},"users":["0xa","0xb"]}}]}}'
        )
        assert len(market) == 1
        assert len(traders) == 2
        assert {event.wallet for event in traders} == {"0xa", "0xb"}
        assert traders[0].counterparty == "0xb"
        assert traders[1].counterparty == "0xa"
        assert all(event.event_type is TraderEventType.FILL for event in traders)

    def test_notional_is_computed_exactly(self) -> None:
        _, traders = norm(
            f'{{"channel":"trades","data":[{{"coin":"BTC","side":"B","px":"60000.5",'
            f'"sz":"0.01","time":{VENUE_MS},"users":["0xa"]}}]}}'
        )
        assert traders[0].notional == Decimal("600.005")

    def test_an_anonymous_trade_produces_no_trader_events(self) -> None:
        """The market event does not depend on identity being present."""
        market, traders = norm(
            f'{{"channel":"trades","data":[{{"coin":"BTC","side":"B","px":"1","sz":"1",'
            f'"time":{VENUE_MS}}}]}}'
        )
        assert len(market) == 1
        assert traders == ()

    def test_trader_events_share_the_trade_timestamps(self) -> None:
        market, traders = norm(
            f'{{"channel":"trades","data":[{{"coin":"BTC","side":"B","px":"1","sz":"1",'
            f'"time":{VENUE_MS},"users":["0xa"]}}]}}'
        )
        assert traders[0].timestamps == market[0].timestamps

    def test_trader_events_are_not_excluded_from_scoring_by_default(self) -> None:
        _, traders = norm(
            f'{{"channel":"trades","data":[{{"coin":"BTC","side":"B","px":"1","sz":"1",'
            f'"time":{VENUE_MS},"users":["0xa"]}}]}}'
        )
        assert not traders[0].is_excluded_from_skill_scoring


class TestQuotesAndBook:
    def test_bbo_becomes_a_two_sided_quote_event(self) -> None:
        market, _ = norm(
            f'{{"channel":"bbo","data":{{"coin":"BTC","time":{VENUE_MS},'
            f'"bbo":[{{"px":"59999.5","sz":"1.2"}},{{"px":"60001.0","sz":"0.8"}}]}}}}'
        )
        event = market[0]
        assert event.event_type is MarketEventType.BBO
        assert event.bid_price == Decimal("59999.5")
        assert event.ask_price == Decimal("60001.0")
        assert event.mid_price == Decimal("60000.25")

    def test_one_sided_bbo_is_normalized(self) -> None:
        market, _ = norm(
            f'{{"channel":"bbo","data":{{"coin":"BTC","time":{VENUE_MS},'
            f'"bbo":[{{"px":"59999.5","sz":"1.2"}},null]}}}}'
        )
        assert market[0].bid_price == Decimal("59999.5")
        assert market[0].ask_price is None

    def test_an_empty_bbo_is_refused(self) -> None:
        message = parse_message(
            f'{{"channel":"bbo","data":{{"coin":"BTC","time":{VENUE_MS},"bbo":[null,null]}}}}'
        )
        with pytest.raises(NormalizationError, match="neither a bid nor an ask"):
            normalize(message, RECEIPT)

    def test_l2_snapshot_promotes_only_top_of_book(self) -> None:
        """Depth stays in the raw archive; see the note in normalize.py."""
        market, _ = norm(
            f'{{"channel":"l2Book","data":{{"coin":"BTC","time":{VENUE_MS},"levels":'
            f'[[{{"px":"99","sz":"1"}},{{"px":"98","sz":"2"}}],'
            f'[{{"px":"101","sz":"1"}},{{"px":"102","sz":"2"}}]]}}}}'
        )
        assert len(market) == 1
        event = market[0]
        assert event.event_type is MarketEventType.L2_SNAPSHOT
        assert event.bid_price == Decimal(99)
        assert event.ask_price == Decimal(101)

    def test_an_empty_book_is_refused(self) -> None:
        message = parse_message(
            f'{{"channel":"l2Book","data":{{"coin":"BTC","time":{VENUE_MS},"levels":[[],[]]}}}}'
        )
        with pytest.raises(NormalizationError, match="no levels"):
            normalize(message, RECEIPT)


class TestAssetContext:
    def test_each_derivatives_variable_becomes_its_own_event(self) -> None:
        market, _ = norm(
            '{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{'
            '"funding":"0.0000125","openInterest":"12345.678","markPx":"60000.25",'
            '"oraclePx":"60000.0","midPx":"60000.25","premium":"0.0001",'
            '"dayNtlVlm":"1","prevDayPx":"1","dayBaseVlm":"1"}}}'
        )
        by_type = {event.event_type: event for event in market}
        assert set(by_type) == {
            MarketEventType.FUNDING,
            MarketEventType.OPEN_INTEREST,
            MarketEventType.MARK_PRICE,
            MarketEventType.ORACLE_PRICE,
        }
        assert by_type[MarketEventType.FUNDING].funding_rate == Decimal("0.0000125")
        assert by_type[MarketEventType.MARK_PRICE].price == Decimal("60000.25")

    def test_absent_variables_produce_no_events(self) -> None:
        market, _ = norm(
            '{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{'
            '"funding":"0.0001","openInterest":null,"markPx":null,"oraclePx":null,'
            '"midPx":null,"premium":"0","dayNtlVlm":"1","prevDayPx":"1",'
            '"dayBaseVlm":"1"}}}'
        )
        assert [event.event_type for event in market] == [MarketEventType.FUNDING]

    def test_asset_context_events_carry_no_venue_timestamp(self) -> None:
        """The channel supplies none; an absent value stays absent."""
        market, _ = norm(
            '{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{'
            '"funding":"0.0001","openInterest":"1","markPx":"1","oraclePx":"1",'
            '"midPx":"1","premium":"0","dayNtlVlm":"1","prevDayPx":"1",'
            '"dayBaseVlm":"1"}}}'
        )
        assert market[0].timestamps.exchange_time is None
        assert market[0].timestamps.local_receive_time == RECEIPT.local_receive_time


class TestTimestampSanity:
    def test_a_zero_timestamp_is_refused(self) -> None:
        """Zero would silently place the event at the Unix epoch."""
        message = parse_message(
            '{"channel":"trades","data":[{"coin":"BTC","side":"B","px":"1","sz":"1","time":0}]}'
        )
        with pytest.raises(NormalizationError, match="must be positive"):
            normalize(message, RECEIPT)

    def test_a_seconds_timestamp_mistaken_for_milliseconds_is_accepted(self) -> None:
        """1757851200 ms is 1970 — wrong, but not detectably a unit error."""
        message = parse_message(
            '{"channel":"trades","data":[{"coin":"BTC","side":"B","px":"1","sz":"1",'
            '"time":1757851200}]}'
        )
        market, _ = normalize(message, RECEIPT)
        assert market[0].timestamps.exchange_time is not None
        assert market[0].timestamps.exchange_time.year == 1970

    def test_a_microseconds_timestamp_is_refused_as_a_unit_error(self) -> None:
        message = parse_message(
            '{"channel":"trades","data":[{"coin":"BTC","side":"B","px":"1","sz":"1",'
            '"time":1757851200000000}]}'
        )
        with pytest.raises(NormalizationError, match="unit error"):
            normalize(message, RECEIPT)


class TestControlFrames:
    def test_a_control_frame_yields_no_events(self) -> None:
        market, traders = norm('{"channel":"pong"}')
        assert market == ()
        assert traders == ()


class TestDeterminism:
    def test_normalizing_twice_gives_identical_events_apart_from_ids(self) -> None:
        """A pure function of (message, receipt) — the basis of replay."""
        payload = (
            f'{{"channel":"trades","data":[{{"coin":"BTC","side":"B","px":"60000.5",'
            f'"sz":"0.01","time":{VENUE_MS},"users":["0xa","0xb"]}}]}}'
        )
        first_market, first_traders = norm(payload)
        second_market, second_traders = norm(payload)

        def comparable(events: Sequence[Any]) -> list[dict[str, Any]]:
            return [event.model_dump(exclude={"event_id"}) for event in events]

        assert comparable(first_market) == comparable(second_market)
        assert comparable(first_traders) == comparable(second_traders)
