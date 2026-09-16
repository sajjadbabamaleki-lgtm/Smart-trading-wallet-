"""The Hyperliquid adapter, its wire format, and its refusals.

Driven against a transport that answers from a script rather than against the
venue. That covers everything except whether the venue agrees, which no test in
this repository can establish and only a testnet run can.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from libs.config import Settings, load_settings
from libs.domain.clock import ManualClock
from libs.exchange.adapter import ExchangeAdapter
from libs.exchange.hyperliquid.adapter import (
    HyperliquidAdapter,
    UnsupportedEnvironmentError,
    VenueRefusedError,
)
from libs.exchange.hyperliquid.signing import (
    action_hash,
    sign_l1_action,
    signer_address,
    typed_data,
)
from libs.exchange.hyperliquid.wire import (
    cancel_action,
    cloid_for,
    market_limit_price,
    order_action,
    round_price,
    round_size,
    to_wire,
)
from libs.exchange.models import OrderRequest, OrderState, OrderType, TimeInForce
from libs.schemas.enums import ExecutionEnvironment, Side

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
KEY = "0x" + "11" * 32
META = {"universe": [{"name": "BTC", "szDecimals": 5}, {"name": "ETH", "szDecimals": 4}]}


def settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "execution_environment": ExecutionEnvironment.TESTNET,
        "trading_enabled": True,
        "testnet_api_wallet_private_key": KEY,
        "asset_allowlist": ("BTC",),
    }
    base.update(overrides)
    return load_settings(**base)


def request(**overrides: object) -> OrderRequest:
    base: dict[str, object] = {
        "client_order_id": "0f8c1e2a-3b4d-4e5f-8a9b-0c1d2e3f4a5b",
        "intent_id": "0f8c1e2a-3b4d-4e5f-8a9b-0c1d2e3f4a5b",
        "correlation_id": "corr-1",
        "asset": "BTC",
        "side": Side.BUY,
        "quantity": Decimal("0.001"),
        "order_type": OrderType.LIMIT,
        "limit_price": Decimal(60_000),
    }
    base.update(overrides)
    return OrderRequest(**base)


class Venue:
    """A scripted venue. Records what it was asked, answers what it was told to."""

    def __init__(self, **answers: Any) -> None:
        self.answers = answers
        self.requests: list[dict[str, Any]] = []
        self.raise_on_exchange: Exception | None = None

    async def handle(self, httpx_request: httpx.Request) -> httpx.Response:
        body = json.loads(httpx_request.content)
        self.requests.append(body)
        if httpx_request.url.path == "/exchange":
            if self.raise_on_exchange is not None:
                raise self.raise_on_exchange
            return httpx.Response(200, json=self.answers.get("exchange", {"status": "ok"}))
        return httpx.Response(200, json=self.answers.get(body["type"], {}))

    def adapter(self, **overrides: object) -> HyperliquidAdapter:
        transport = httpx.MockTransport(self.handle)
        return HyperliquidAdapter(
            settings(**overrides),
            clock=ManualClock(NOW),
            client=httpx.AsyncClient(transport=transport),
        )


class TestWireFormat:
    def test_numbers_never_travel_in_scientific_notation(self) -> None:
        """A price the venue cannot parse is an order that never existed."""
        assert to_wire(Decimal("0.00001")) == "0.00001"
        assert to_wire(Decimal("1E-5")) == "0.00001"
        assert to_wire(Decimal("100.000")) == "100"
        assert to_wire(Decimal("-0")) == "0"

    def test_a_buy_rounds_its_price_down_and_a_sell_rounds_up(self) -> None:
        """Rounding may only ever make our price less aggressive."""
        assert round_price(Decimal("60000.567"), sz_decimals=5, side=Side.BUY) == Decimal("60000")
        assert round_price(Decimal("60000.567"), sz_decimals=5, side=Side.SELL) == Decimal("60001")

    def test_an_integer_price_is_left_alone(self) -> None:
        """The significant-figure rule does not apply to it, and applying it would move it."""
        assert round_price(Decimal(108_000), sz_decimals=5, side=Side.BUY) == Decimal(108_000)

    def test_the_decimal_place_rule_binds_where_it_is_tighter(self) -> None:
        """szDecimals 4 leaves two decimal places, which is fewer than five figures allows."""
        assert round_price(Decimal("1.234567"), sz_decimals=4, side=Side.BUY) == Decimal("1.23")

    def test_five_significant_figures_bind_where_they_are_tighter(self) -> None:
        """szDecimals 0 leaves six decimal places, so the figure count is what stops it."""
        assert round_price(Decimal("1.234567"), sz_decimals=0, side=Side.BUY) == Decimal("1.2345")

    def test_a_large_price_falls_back_to_whole_units(self) -> None:
        """Five figures cannot reach the decimal point, and the venue allows integers."""
        assert round_price(Decimal("123456.7"), sz_decimals=0, side=Side.BUY) == Decimal(123_456)

    def test_size_always_rounds_down(self) -> None:
        """A rounding rule that can increase exposure will, eventually."""
        assert round_size(Decimal("0.0019999"), sz_decimals=5) == Decimal("0.00199")

    def test_the_same_order_id_always_derives_the_same_cloid(self) -> None:
        """Idempotency after a timeout rests entirely on this."""
        assert cloid_for("abc") == cloid_for("abc")
        assert cloid_for("abc") != cloid_for("abd")
        assert len(cloid_for("abc")) == 34

    def test_a_uuid_maps_onto_the_sixteen_bytes_directly(self) -> None:
        assert cloid_for("0f8c1e2a-3b4d-4e5f-8a9b-0c1d2e3f4a5b") == (
            "0x0f8c1e2a3b4d4e5f8a9b0c1d2e3f4a5b"
        )

    def test_the_order_action_keeps_the_field_order_the_venue_hashes(self) -> None:
        """Re-ordering these keys changes the signature's recovered signer."""
        action = order_action(request(), asset_index=0, sz_decimals=5, limit_price=Decimal(60_000))
        assert list(action) == ["type", "orders", "grouping"]
        assert list(action["orders"][0]) == ["a", "b", "p", "s", "r", "t", "c"]

    def test_a_market_order_becomes_an_immediate_or_cancel_limit(self) -> None:
        action = order_action(
            request(order_type=OrderType.MARKET, limit_price=None),
            asset_index=0,
            sz_decimals=5,
            limit_price=Decimal(60_300),
        )
        assert action["orders"][0]["t"] == {"limit": {"tif": "Ioc"}}

    def test_post_only_is_carried_through(self) -> None:
        action = order_action(
            request(time_in_force=TimeInForce.ALO),
            asset_index=0,
            sz_decimals=5,
            limit_price=Decimal(60_000),
        )
        assert action["orders"][0]["t"] == {"limit": {"tif": "Alo"}}

    def test_a_market_buy_crosses_up_and_a_market_sell_crosses_down(self) -> None:
        up = market_limit_price(
            reference=Decimal(60_000), side=Side.BUY, slippage=Decimal("0.01"), sz_decimals=5
        )
        down = market_limit_price(
            reference=Decimal(60_000), side=Side.SELL, slippage=Decimal("0.01"), sz_decimals=5
        )
        assert up > Decimal(60_000) > down

    def test_a_cancel_carries_our_id_not_the_venue_s(self) -> None:
        """Cancelling after a timeout means having no venue id to cancel by."""
        action = cancel_action(asset_index=0, client_order_id="abc")
        assert action["cancels"][0]["cloid"] == cloid_for("abc")


class TestSigning:
    def test_the_signature_recovers_to_the_signing_key(self) -> None:
        action = {"type": "order", "orders": [], "grouping": "na"}
        signature = sign_l1_action(action, private_key=KEY, nonce=1, is_mainnet=False)
        message = encode_typed_data(
            full_message=typed_data(action_hash(action, nonce=1), is_mainnet=False)
        )
        recovered = Account.recover_message(
            message, vrs=(signature["v"], signature["r"], signature["s"])
        )
        assert recovered == signer_address(KEY)

    def test_testnet_and_mainnet_produce_different_signatures(self) -> None:
        """A testnet signature is worthless on mainnet, which is a safety property."""
        action = {"type": "order", "orders": [], "grouping": "na"}
        testnet = sign_l1_action(action, private_key=KEY, nonce=1, is_mainnet=False)
        mainnet = sign_l1_action(action, private_key=KEY, nonce=1, is_mainnet=True)
        assert testnet != mainnet

    def test_the_nonce_is_part_of_the_hash(self) -> None:
        action = {"type": "dummy"}
        assert action_hash(action, nonce=1) != action_hash(action, nonce=2)

    def test_field_order_changes_the_hash(self) -> None:
        """Stated as a test because it is the reason wire.py may not be tidied."""
        assert action_hash({"a": 1, "b": 2}, nonce=1) != action_hash({"b": 2, "a": 1}, nonce=1)

    def test_signing_never_returns_the_key(self) -> None:
        signature = sign_l1_action({"type": "dummy"}, private_key=KEY, nonce=1, is_mainnet=False)
        assert set(signature) == {"r", "s", "v"}
        assert KEY.removeprefix("0x") not in str(signature)


class TestRefusals:
    def test_it_cannot_be_constructed_against_a_non_testnet_environment(self) -> None:
        """Settings refuse mainnet too. This refuses again, on purpose."""
        with pytest.raises(UnsupportedEnvironmentError, match="TESTNET"):
            HyperliquidAdapter(
                settings(
                    execution_environment=ExecutionEnvironment.DEVELOPMENT,
                    testnet_api_wallet_private_key="",
                    trading_enabled=False,
                )
            )

    def test_it_refuses_to_start_without_a_credential(self) -> None:
        with pytest.raises(UnsupportedEnvironmentError, match="key"):
            HyperliquidAdapter(settings(testnet_api_wallet_private_key="", trading_enabled=False))

    def test_it_satisfies_the_adapter_contract(self) -> None:
        assert isinstance(Venue().adapter(), ExchangeAdapter)

    async def test_an_unlisted_asset_is_refused_rather_than_guessed(self) -> None:
        venue = Venue(meta=META)
        adapter = venue.adapter()
        with pytest.raises(VenueRefusedError, match="DOGE"):
            await adapter.place_order(request(asset="DOGE"))
        assert not any(r.get("type") == "order" for r in venue.requests)

    async def test_market_data_is_not_this_adapter_s_socket(self) -> None:
        with pytest.raises(NotImplementedError):
            Venue().adapter().subscribe_events(("BTC",))


class TestPlaceOrder:
    async def test_a_resting_order_is_acknowledged_with_its_venue_id(self) -> None:
        venue = Venue(
            meta=META,
            exchange={
                "status": "ok",
                "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 77}}]}},
            },
        )
        status = await venue.adapter().place_order(request())
        assert status.state is OrderState.ACKNOWLEDGED
        assert status.venue_order_id == "77"

    async def test_a_full_fill_is_reported_filled(self) -> None:
        venue = Venue(
            meta=META,
            exchange={
                "status": "ok",
                "response": {
                    "type": "order",
                    "data": {
                        "statuses": [
                            {"filled": {"oid": 78, "totalSz": "0.001", "avgPx": "60000.5"}}
                        ]
                    },
                },
            },
        )
        status = await venue.adapter().place_order(request())
        assert status.state is OrderState.FILLED
        assert status.filled_quantity == Decimal("0.001")
        assert status.average_fill_price == Decimal("60000.5")

    async def test_a_short_fill_is_partial_not_filled(self) -> None:
        venue = Venue(
            meta=META,
            exchange={
                "status": "ok",
                "response": {
                    "type": "order",
                    "data": {
                        "statuses": [{"filled": {"oid": 79, "totalSz": "0.0005", "avgPx": "60000"}}]
                    },
                },
            },
        )
        status = await venue.adapter().place_order(request())
        assert status.state is OrderState.PARTIALLY_FILLED

    async def test_a_venue_error_is_a_rejection_carrying_its_reason(self) -> None:
        venue = Venue(
            meta=META,
            exchange={
                "status": "ok",
                "response": {
                    "type": "order",
                    "data": {"statuses": [{"error": "Order price cannot be more than 80% away"}]},
                },
            },
        )
        status = await venue.adapter().place_order(request())
        assert status.state is OrderState.REJECTED
        assert status.reject_reason is not None
        assert "80%" in status.reject_reason

    @pytest.mark.parametrize(
        "failure",
        [
            httpx.ReadTimeout("timed out"),
            httpx.ConnectError("connection reset"),
        ],
    )
    async def test_an_ambiguous_submission_is_unknown_and_never_raises(
        self, failure: Exception
    ) -> None:
        """The venue may have the order. Raising here is how a timeout doubles a position."""
        venue = Venue(meta=META)
        venue.raise_on_exchange = failure
        status = await venue.adapter().place_order(request())
        assert status.state is OrderState.UNKNOWN
        assert not status.state.is_terminal

    async def test_a_market_order_is_priced_off_the_book(self) -> None:
        venue = Venue(
            meta=META,
            l2Book={"levels": [[{"px": "59990", "sz": "1"}], [{"px": "60010", "sz": "1"}]]},
            metaAndAssetCtxs=[META, [{"markPx": "60000", "oraclePx": "60001"}]],
            exchange={
                "status": "ok",
                "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 80}}]}},
            },
        )
        await venue.adapter().place_order(request(order_type=OrderType.MARKET, limit_price=None))
        order = next(r for r in venue.requests if r.get("action", {}).get("type") == "order")
        # Crossed above the ask, so it can fill, but still a limit.
        assert Decimal(order["action"]["orders"][0]["p"]) > Decimal("60010")

    async def test_the_same_request_submits_the_same_client_id_every_time(self) -> None:
        """A retry must present the id the venue may already have seen."""
        venue = Venue(
            meta=META,
            exchange={
                "status": "ok",
                "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 81}}]}},
            },
        )
        adapter = venue.adapter()
        await adapter.place_order(request())
        await adapter.place_order(request())
        sent = [r for r in venue.requests if r.get("action", {}).get("type") == "order"]
        assert sent[0]["action"]["orders"][0]["c"] == sent[1]["action"]["orders"][0]["c"]
        # The nonce is not part of idempotency and must not be reused as if it were.
        assert len(sent) == 2

    async def test_nothing_in_the_submitted_payload_carries_the_key(self) -> None:
        venue = Venue(
            meta=META,
            exchange={
                "status": "ok",
                "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 82}}]}},
            },
        )
        await venue.adapter().place_order(request())
        assert KEY.removeprefix("0x") not in str(venue.requests)


class TestReads:
    async def test_account_state_reports_equity_and_open_positions(self) -> None:
        venue = Venue(
            meta=META,
            clearinghouseState={
                "marginSummary": {"accountValue": "1000.5"},
                "withdrawable": "900.25",
                "assetPositions": [
                    {
                        "position": {
                            "coin": "BTC",
                            "szi": "-0.002",
                            "entryPx": "60000",
                            "unrealizedPnl": "-1.5",
                            "liquidationPx": "70000",
                            "marginUsed": "12",
                            "leverage": {"type": "cross", "value": "10"},
                        }
                    },
                    {"position": {"coin": "ETH", "szi": "0"}},
                ],
            },
        )
        state = await venue.adapter().get_account_state()
        assert state.equity == Decimal("1000.5")
        assert state.available_margin == Decimal("900.25")
        # The flat position is not a position.
        assert len(state.positions) == 1
        assert state.positions[0].side is Side.SELL

    async def test_fills_keep_the_venue_s_own_timestamp(self) -> None:
        """Restamping a fill on arrival makes every latency figure measure us."""
        venue = Venue(
            meta=META,
            userFills=[
                {
                    "tid": 12345,
                    "oid": 99,
                    "coin": "BTC",
                    "side": "B",
                    "px": "60000",
                    "sz": "0.001",
                    "fee": "0.03",
                    "crossed": True,
                    "time": 1789000000000,
                    "cloid": "0x0f8c1e2a3b4d4e5f8a9b0c1d2e3f4a5b",
                }
            ],
        )
        fills = await venue.adapter().get_fills()
        assert fills[0].filled_at == datetime.fromtimestamp(1789000000, tz=UTC)
        assert fills[0].is_maker is False
        assert fills[0].fee == Decimal("0.03")

    async def test_cancelling_something_the_venue_does_not_hold_is_not_an_error(self) -> None:
        venue = Venue(meta=META, openOrders=[])
        status = await venue.adapter().cancel_order("abc")
        assert status.state is OrderState.CANCELLED
        assert not any(r.get("action", {}).get("type") == "cancelByCloid" for r in venue.requests)

    async def test_cancelling_an_open_order_sends_a_cancel_for_its_asset(self) -> None:
        venue = Venue(
            meta=META,
            openOrders=[{"oid": 91, "coin": "BTC", "cloid": cloid_for("abc")}],
            exchange={
                "status": "ok",
                "response": {"type": "cancel", "data": {"statuses": ["success"]}},
            },
        )
        status = await venue.adapter().cancel_order("abc")
        assert status.state is OrderState.CANCELLED
        assert status.venue_order_id == "91"
        cancel = next(
            r for r in venue.requests if r.get("action", {}).get("type") == "cancelByCloid"
        )
        assert cancel["action"]["cancels"][0]["asset"] == 0

    async def test_the_asset_catalogue_is_fetched_once(self) -> None:
        venue = Venue(
            meta=META,
            exchange={
                "status": "ok",
                "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 92}}]}},
            },
        )
        adapter = venue.adapter()
        await adapter.place_order(request())
        await adapter.place_order(request())
        assert sum(1 for r in venue.requests if r.get("type") == "meta") == 1
