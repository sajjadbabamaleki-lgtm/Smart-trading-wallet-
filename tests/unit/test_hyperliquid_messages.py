"""Parsing Hyperliquid frames."""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.exchange.hyperliquid.messages import (
    AssetContextRecord,
    BboRecord,
    ControlRecord,
    L2BookRecord,
    MessageParseError,
    TradeRecord,
    parse_message,
)
from libs.schemas.enums import Side


class TestTrades:
    def test_a_trade_is_parsed_exactly(self) -> None:
        message = parse_message(
            '{"channel":"trades","data":[{"coin":"BTC","side":"B","px":"60000.5",'
            '"sz":"0.01","time":1757851200000,"hash":"0xaa","tid":1001,'
            '"users":["0xa","0xb"]}]}'
        )
        assert message.channel == "trades"
        record = message.records[0]
        assert isinstance(record, TradeRecord)
        assert record.price == Decimal("60000.5")
        assert record.quantity == Decimal("0.01")
        assert record.side is Side.BUY
        assert record.trade_id == 1001
        assert record.users == ("0xa", "0xb")

    def test_ask_side_maps_to_sell(self) -> None:
        message = parse_message(
            '{"channel":"trades","data":[{"coin":"BTC","side":"A","px":"1","sz":"1",'
            '"time":1757851200000}]}'
        )
        record = message.records[0]
        assert isinstance(record, TradeRecord)
        assert record.side is Side.SELL

    def test_one_frame_can_carry_several_trades(self) -> None:
        message = parse_message(
            '{"channel":"trades","data":['
            '{"coin":"BTC","side":"B","px":"1","sz":"1","time":1757851200000},'
            '{"coin":"BTC","side":"A","px":"2","sz":"2","time":1757851200001}]}'
        )
        assert len(message.records) == 2

    def test_integer_size_is_accepted(self) -> None:
        """The SDK types `sz` as int; the API sends a string. Accept both."""
        message = parse_message(
            '{"channel":"trades","data":[{"coin":"BTC","side":"B","px":"1","sz":3,'
            '"time":1757851200000}]}'
        )
        record = message.records[0]
        assert isinstance(record, TradeRecord)
        assert record.quantity == Decimal(3)

    def test_a_float_price_is_refused(self) -> None:
        """A float may already have lost precision; storing it hides that."""
        with pytest.raises(MessageParseError, match="float"):
            parse_message(
                '{"channel":"trades","data":[{"coin":"BTC","side":"B","px":60000.5,'
                '"sz":"0.01","time":1757851200000}]}'
            )

    def test_unknown_fields_are_ignored(self) -> None:
        """A venue adding a field must not stop the recorder."""
        message = parse_message(
            '{"channel":"trades","data":[{"coin":"BTC","side":"B","px":"1","sz":"1",'
            '"time":1757851200000,"somethingNew":42}]}'
        )
        assert len(message.records) == 1

    def test_missing_identity_fields_stay_absent(self) -> None:
        message = parse_message(
            '{"channel":"trades","data":[{"coin":"BTC","side":"B","px":"1","sz":"1",'
            '"time":1757851200000}]}'
        )
        record = message.records[0]
        assert isinstance(record, TradeRecord)
        assert record.trade_id is None
        assert record.users == ()

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (
                '{"channel":"trades","data":[{"coin":"BTC","side":"X","px":"1","sz":"1","time":1}]}',
                "side",
            ),
            (
                '{"channel":"trades","data":[{"coin":"BTC","side":"B","px":"x","sz":"1","time":1}]}',
                "not a number",
            ),
            (
                '{"channel":"trades","data":[{"coin":"BTC","side":"B","px":"1","sz":"1"}]}',
                "time is missing",
            ),
            ('{"channel":"trades","data":[{"side":"B","px":"1","sz":"1","time":1}]}', "coin"),
            ('{"channel":"trades","data":{"not":"a list"}}', "not an array"),
        ],
    )
    def test_unusable_trades_are_refused(self, payload: str, expected: str) -> None:
        with pytest.raises(MessageParseError, match=expected):
            parse_message(payload)


class TestBookAndQuotes:
    def test_l2_book_levels_are_ordered_as_sent(self) -> None:
        message = parse_message(
            '{"channel":"l2Book","data":{"coin":"BTC","time":1757851200200,"levels":'
            '[[{"px":"99","sz":"1","n":3},{"px":"98","sz":"2","n":4}],'
            '[{"px":"101","sz":"1","n":2},{"px":"102","sz":"2","n":1}]]}}'
        )
        record = message.records[0]
        assert isinstance(record, L2BookRecord)
        assert record.best_bid is not None
        assert record.best_bid.price == Decimal(99)
        assert record.best_ask is not None
        assert record.best_ask.price == Decimal(101)
        assert record.best_bid.order_count == 3

    def test_l2_book_requires_both_sides_of_the_array(self) -> None:
        with pytest.raises(MessageParseError, match="two-element"):
            parse_message(
                '{"channel":"l2Book","data":{"coin":"BTC","time":1,"levels":'
                '[[{"px":"99","sz":"1"}]]}}'
            )

    def test_bbo_with_one_side_absent_is_representable(self) -> None:
        message = parse_message(
            '{"channel":"bbo","data":{"coin":"BTC","time":1757851200400,'
            '"bbo":[{"px":"99","sz":"1"},null]}}'
        )
        record = message.records[0]
        assert isinstance(record, BboRecord)
        assert record.bid is not None
        assert record.ask is None

    def test_level_without_order_count_is_accepted(self) -> None:
        message = parse_message(
            '{"channel":"bbo","data":{"coin":"BTC","time":1,'
            '"bbo":[{"px":"99","sz":"1"},{"px":"101","sz":"1"}]}}'
        )
        record = message.records[0]
        assert isinstance(record, BboRecord)
        assert record.bid is not None
        assert record.bid.order_count is None


class TestAssetContext:
    def test_derivatives_state_is_parsed(self) -> None:
        message = parse_message(
            '{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{'
            '"funding":"0.0000125","openInterest":"12345.678","prevDayPx":"59000",'
            '"dayNtlVlm":"123","premium":"0.0001","oraclePx":"60000",'
            '"markPx":"60000.25","midPx":"60000.25","dayBaseVlm":"20"}}}'
        )
        record = message.records[0]
        assert isinstance(record, AssetContextRecord)
        assert record.funding == Decimal("0.0000125")
        assert record.open_interest == Decimal("12345.678")
        assert record.mark_price == Decimal("60000.25")

    def test_a_null_mid_price_stays_absent(self) -> None:
        message = parse_message(
            '{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{'
            '"funding":"0.0001","openInterest":"1","markPx":"60000",'
            '"oraclePx":"60000","midPx":null,"premium":"0","dayNtlVlm":"1",'
            '"prevDayPx":"1","dayBaseVlm":"1"}}}'
        )
        record = message.records[0]
        assert isinstance(record, AssetContextRecord)
        assert record.mid_price is None

    def test_negative_funding_is_accepted(self) -> None:
        message = parse_message(
            '{"channel":"activeAssetCtx","data":{"coin":"BTC","ctx":{'
            '"funding":"-0.0000125","openInterest":"1","markPx":"1","oraclePx":"1",'
            '"midPx":"1","premium":"0","dayNtlVlm":"1","prevDayPx":"1","dayBaseVlm":"1"}}}'
        )
        record = message.records[0]
        assert isinstance(record, AssetContextRecord)
        assert record.funding == Decimal("-0.0000125")


class TestControlAndFraming:
    def test_a_pong_is_a_control_frame(self) -> None:
        message = parse_message('{"channel":"pong"}')
        assert not message.is_data
        assert isinstance(message.records[0], ControlRecord)

    def test_an_unknown_channel_is_preserved_not_dropped(self) -> None:
        message = parse_message('{"channel":"somethingNew","data":{"x":1}}')
        assert not message.is_data
        record = message.records[0]
        assert isinstance(record, ControlRecord)
        assert record.payload == {"x": 1}

    def test_invalid_json_is_refused_and_keeps_the_raw_text(self) -> None:
        """The raw frame is evidence; the error must not discard it."""
        with pytest.raises(MessageParseError) as exc:
            parse_message("not json")
        assert exc.value.raw == "not json"

    def test_a_frame_without_a_channel_is_refused(self) -> None:
        with pytest.raises(MessageParseError, match="no channel"):
            parse_message('{"data":[]}')

    def test_a_non_object_frame_is_refused(self) -> None:
        with pytest.raises(MessageParseError, match="not an object"):
            parse_message("[1,2,3]")

    def test_the_raw_frame_is_retained_on_success(self) -> None:
        raw = '{"channel":"pong"}'
        assert parse_message(raw).raw == raw
