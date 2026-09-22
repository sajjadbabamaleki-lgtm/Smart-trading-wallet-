"""The Hyperliquid adapter: trade flow against a simulated SDK, wire format against the real one."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
import requests
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.utils.constants import TESTNET_API_URL

from libs.exchange.errors import OrderOutcomeUnknownError, VenueError
from services.trader.planner import RiskLimits
from services.trader.trader import (
    TradeRefusedError,
    close_position,
    open_position,
    position_for,
    update_tpsl,
)
from services.trader.venue import Direction, MarketRules
from services.trader.venues.hyperliquid import (
    EMPTY_SPOT_META,
    HyperliquidVenue,
    check_account,
    load_api_wallet,
)

MAIN = Account.from_key("0x" + "11" * 32)
API_WALLET = Account.from_key("0x" + "22" * 32)
ACCOUNT = MAIN.address
META = {
    "universe": [
        {"name": "BTC", "szDecimals": 5, "maxLeverage": 40},
        {"name": "SOL", "szDecimals": 2, "maxLeverage": 20},
    ]
}
LIMITS = RiskLimits(
    risk_percent=Decimal(1),
    max_leverage=3,
    taker_fee_rate=Decimal(0),
    slippage_percent=Decimal("0.5"),
)


def _ok(statuses: list[Any]) -> dict[str, Any]:
    return {"status": "ok", "response": {"type": "order", "data": {"statuses": statuses}}}


class FakeHyperliquid:
    """Info and Exchange in one: just enough state to exercise the adapter."""

    def __init__(self) -> None:
        self.mid = "150"
        self.wallet = API_WALLET
        self.positions: dict[str, Decimal] = {}
        self.entries: dict[str, str] = {}
        self.triggers: list[dict[str, Any]] = []
        self.next_oid = 1
        self.calls: list[tuple[str, Any]] = []
        self.reject_entry: str | None = None
        self.reject_triggers = False
        self.drop_grouped_triggers = False
        self.timeout = False

    # Info -------------------------------------------------------------
    def meta(self) -> Any:
        return META

    def all_mids(self) -> Any:
        return {"SOL": self.mid, "BTC": "60000"}

    def user_state(self, address: str) -> Any:
        assert address == ACCOUNT
        return {
            "marginSummary": {"accountValue": "1000.0", "totalMarginUsed": "0.0"},
            "assetPositions": [
                {"position": {"coin": c, "szi": str(s), "entryPx": self.entries[c]}}
                for c, s in self.positions.items()
            ],
        }

    def frontend_open_orders(self, address: str) -> Any:
        assert address == ACCOUNT
        return list(self.triggers)

    # Exchange ---------------------------------------------------------
    def update_leverage(self, leverage: int, name: str, is_cross: bool) -> Any:
        self.calls.append(("leverage", (leverage, name, is_cross)))
        return {"status": "ok", "response": {"type": "default"}}

    def bulk_orders(self, orders: list[dict[str, Any]], grouping: str = "na") -> Any:
        if self.timeout:
            raise requests.Timeout("timed out")
        self.calls.append(("orders", (orders, grouping)))
        statuses: list[Any] = []
        for order in orders:
            coin = order["coin"]
            if "trigger" in order["order_type"]:
                if self.reject_triggers:
                    statuses.append({"error": "Invalid TP/SL price."})
                    continue
                if not (self.drop_grouped_triggers and grouping == "normalTpsl"):
                    self._add_trigger(order)
                statuses.append("waitingForTrigger")
                continue
            if self.reject_entry and not order["reduce_only"]:
                statuses.append({"error": self.reject_entry})
                continue
            size = Decimal(str(order["sz"])) * (1 if order["is_buy"] else -1)
            new = self.positions.get(coin, Decimal(0)) + size
            if new == 0:
                self.positions.pop(coin, None)
            else:
                self.positions[coin] = new
                self.entries[coin] = self.mid
            statuses.append({"filled": {"totalSz": str(order["sz"]), "avgPx": self.mid}})
        return _ok(statuses)

    def bulk_cancel(self, requests_: list[dict[str, Any]]) -> Any:
        self.calls.append(("cancel", requests_))
        oids = {r["oid"] for r in requests_}
        self.triggers = [t for t in self.triggers if t["oid"] not in oids]
        return {"status": "ok", "response": {"type": "cancel", "data": {"statuses": ["success"]}}}

    def _add_trigger(self, order: dict[str, Any]) -> None:
        self.triggers.append(
            {
                "coin": order["coin"],
                "oid": self.next_oid,
                "side": "B" if order["is_buy"] else "A",
                "isTrigger": True,
                "reduceOnly": True,
                "triggerPx": str(order["order_type"]["trigger"]["triggerPx"]),
                "orderType": "Stop Market",
            }
        )
        self.next_oid += 1

    def orders_sent(self) -> list[tuple[list[dict[str, Any]], str]]:
        return [args for kind, args in self.calls if kind == "orders"]


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def hl() -> FakeHyperliquid:
    return FakeHyperliquid()


@pytest.fixture
def venue(hl: FakeHyperliquid) -> HyperliquidVenue:
    return HyperliquidVenue(info=hl, exchange=hl, account_address=ACCOUNT, mainnet=False)


async def _open(venue: HyperliquidVenue, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "symbol": "SOL",
        "direction": Direction.LONG,
        "stop_loss": Decimal(145),
        "take_profit": Decimal(160),
        "limits": LIMITS,
        "execute": True,
        "sleep": _no_sleep,
    }
    arguments.update(overrides)
    return await open_position(venue, **arguments)


class TestPriceRules:
    @pytest.fixture
    def sol(self) -> MarketRules:
        return MarketRules(
            symbol="SOL",
            lot_size=Decimal("0.01"),
            max_leverage=20,
            min_order_usd=Decimal(10),
            significant_figures=5,
            max_price_decimals=4,
        )

    @pytest.mark.parametrize(
        ("raw", "rounded"),
        [
            ("150.126", "150.13"),  # five significant figures
            ("12.34567", "12.346"),
            ("0.123456", "0.1235"),  # capped at 6 - szDecimals = 4 decimals
            ("123456", "123456"),  # integers are always valid
            ("145", "145"),
        ],
    )
    def test_prices_follow_hyperliquid_rules(
        self, sol: MarketRules, raw: str, rounded: str
    ) -> None:
        assert sol.round_price(Decimal(raw)) == Decimal(rounded)

    def test_sizes_round_down_to_size_decimals(self, sol: MarketRules) -> None:
        assert sol.round_size(Decimal("1.239")) == Decimal("1.23")

    def test_exactly_one_price_convention_is_required(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            MarketRules(symbol="X", lot_size=Decimal(1), max_leverage=1, min_order_usd=Decimal(10))


async def test_market_rules_come_from_the_universe(venue: HyperliquidVenue) -> None:
    rules = await venue.market("SOL")
    assert rules.lot_size == Decimal("0.01")
    assert rules.max_leverage == 20
    assert rules.max_price_decimals == 4
    with pytest.raises(VenueError, match="not a listed"):
        await venue.market("NOPE")


async def test_long_goes_out_as_one_entry_plus_tpsl_request(
    venue: HyperliquidVenue, hl: FakeHyperliquid
) -> None:
    result = await _open(venue)

    assert result.stop_confirmed
    assert hl.calls[0] == ("leverage", (result.plan.leverage, "SOL", True))
    [(orders, grouping)] = hl.orders_sent()
    assert grouping == "normalTpsl"
    entry, stop, target = orders
    assert entry["is_buy"] is True
    assert entry["order_type"] == {"limit": {"tif": "Ioc"}}
    assert entry["limit_px"] == pytest.approx(150.75)  # mid + 0.5% slippage
    assert stop["order_type"]["trigger"] == {"triggerPx": 145.0, "isMarket": True, "tpsl": "sl"}
    assert stop["is_buy"] is False
    assert stop["reduce_only"] is True
    assert stop["limit_px"] == pytest.approx(130.5)  # fills up to 10% past the trigger
    assert target["order_type"]["trigger"]["tpsl"] == "tp"
    assert stop["sz"] == entry["sz"] == float(result.plan.amount)


async def test_short_mirrors_the_long(venue: HyperliquidVenue, hl: FakeHyperliquid) -> None:
    await _open(venue, direction=Direction.SHORT, stop_loss=Decimal(155), take_profit=Decimal(140))
    [(orders, _)] = hl.orders_sent()
    entry, stop, _ = orders
    assert entry["is_buy"] is False
    assert entry["limit_px"] == pytest.approx(149.25)
    assert stop["is_buy"] is True
    assert stop["limit_px"] == pytest.approx(170.5)
    position = await position_for(venue, "SOL")
    assert position is not None
    assert not position.is_long


async def test_rejected_entry_is_reported(venue: HyperliquidVenue, hl: FakeHyperliquid) -> None:
    hl.reject_entry = "Order could not immediately match against any resting orders."
    with pytest.raises(VenueError, match="immediately match"):
        await _open(venue)
    assert hl.positions == {}


async def test_dropped_stop_is_reattached(venue: HyperliquidVenue, hl: FakeHyperliquid) -> None:
    hl.drop_grouped_triggers = True
    result = await _open(venue)
    # The trader saw no stop after the fill, so it was sent again on its own.
    assert result.stop_confirmed
    (_, grouping) = hl.orders_sent()[-1]
    assert grouping == "na"
    assert any(t["triggerPx"] == "145.0" for t in hl.triggers)


async def test_position_is_closed_when_no_stop_can_be_attached(
    venue: HyperliquidVenue, hl: FakeHyperliquid
) -> None:
    hl.reject_triggers = True
    with pytest.raises(TradeRefusedError, match="closed at market"):
        await _open(venue)
    assert hl.positions == {}


async def test_timeout_on_an_order_is_unknown(venue: HyperliquidVenue, hl: FakeHyperliquid) -> None:
    hl.timeout = True
    with pytest.raises(OrderOutcomeUnknownError, match="Check open positions"):
        await _open(venue)


async def test_moving_the_stop_places_new_then_cancels_old(
    venue: HyperliquidVenue, hl: FakeHyperliquid
) -> None:
    await _open(venue)
    old = {t["oid"] for t in hl.triggers}
    await update_tpsl(venue, symbol="SOL", stop_loss=Decimal(148), take_profit=None, execute=True)

    kinds = [kind for kind, _ in hl.calls]
    assert kinds[-2:] == ["orders", "cancel"]
    (orders, _) = hl.orders_sent()[-1]
    assert {o["order_type"]["trigger"]["tpsl"] for o in orders} == {"sl", "tp"}
    assert not old & {t["oid"] for t in hl.triggers}
    prices = sorted(t["triggerPx"] for t in hl.triggers)
    assert prices == ["148.0", "160.0"]


async def test_close_is_reduce_only_and_clears_triggers(
    venue: HyperliquidVenue, hl: FakeHyperliquid
) -> None:
    await _open(venue)
    await close_position(venue, symbol="SOL", slippage_percent=Decimal("0.5"), execute=True)
    (orders, _) = hl.orders_sent()[-1]
    assert orders[0]["reduce_only"] is True
    assert orders[0]["is_buy"] is False
    assert hl.positions == {}
    assert hl.triggers == []


async def test_read_only_connection_cannot_trade(hl: FakeHyperliquid) -> None:
    venue = HyperliquidVenue(info=hl, exchange=None, account_address=ACCOUNT, mainnet=False)
    with pytest.raises(VenueError, match="read-only"):
        await venue.set_leverage("SOL", 2)


def test_main_wallet_key_is_detected(hl: FakeHyperliquid) -> None:
    api = HyperliquidVenue(info=hl, exchange=hl, account_address=ACCOUNT, mainnet=False)
    assert api.signs_as_api_wallet
    hl.wallet = MAIN
    assert not api.signs_as_api_wallet


class TestKeysAndAddresses:
    def test_account_address_is_validated(self) -> None:
        assert check_account(f" {ACCOUNT} ") == ACCOUNT
        for bad in ("", "0x123", "not-an-address", "0x" + "zz" * 20):
            with pytest.raises(VenueError):
                check_account(bad)

    def test_key_errors_never_echo_the_key(self) -> None:
        secret = "0x" + "zz" * 32
        with pytest.raises(VenueError) as excinfo:
            load_api_wallet(secret)
        assert secret not in str(excinfo.value)
        with pytest.raises(VenueError, match="no private key"):
            load_api_wallet("  ")


async def test_orders_pass_through_the_real_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """The official SDK accepts our prices and sizes, and signs the request.

    Everything up to the HTTP POST is real: the SDK converts floats to wire
    strings (raising if a value needs rounding), builds the order action and
    signs it with the API wallet. Only the POST itself is captured.
    """
    sent: list[dict[str, Any]] = []
    exchange = Exchange(
        API_WALLET,
        TESTNET_API_URL,
        meta=META,
        spot_meta=EMPTY_SPOT_META,
        account_address=ACCOUNT,
    )

    def capture(path: str, payload: Any = None) -> Any:
        sent.append({"path": path, **payload})
        return _ok([{"filled": {"totalSz": "0.66", "avgPx": "150.5"}}, "waitingForTrigger"])

    monkeypatch.setattr(exchange, "post", capture)
    hl = FakeHyperliquid()
    venue = HyperliquidVenue(info=hl, exchange=exchange, account_address=ACCOUNT, mainnet=False)
    market = await venue.market("SOL")

    await venue.open_protected(
        market=market,
        direction=Direction.LONG,
        amount=Decimal("0.66"),
        slippage_percent=Decimal("0.5"),
        stop_loss=Decimal("145.123"),
        take_profit=Decimal("160.987"),
    )

    [request] = sent
    assert request["path"] == "/exchange"
    action = request["action"]
    assert action["type"] == "order"
    assert action["grouping"] == "normalTpsl"
    entry, stop, target = action["orders"]
    sol_asset = 1
    assert entry == {
        "a": sol_asset,
        "b": True,
        "p": "150.75",
        "s": "0.66",
        "r": False,
        "t": {"limit": {"tif": "Ioc"}},
    }
    assert stop["t"] == {"trigger": {"isMarket": True, "triggerPx": "145.12", "tpsl": "sl"}}
    assert stop["r"] is True
    assert stop["b"] is False
    assert target["t"]["trigger"]["triggerPx"] == "160.99"
    assert set(request["signature"]) == {"r", "s", "v"}
