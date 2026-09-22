"""Open, protect, adjust and close — against an in-memory Pacifica venue."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from solders.keypair import Keypair

from libs.exchange.pacifica.client import (
    OrderOutcomeUnknownError,
    PacificaClient,
    PacificaError,
    PacificaNetwork,
)
from libs.exchange.pacifica.signing import Signer
from services.trader.planner import Direction, RiskLimits
from services.trader.trader import (
    TradeRefusedError,
    close_position,
    has_stop_loss,
    open_position,
    update_tpsl,
)

MAIN = Keypair.from_seed(bytes(range(32)))
AGENT = Keypair.from_seed(bytes(range(32, 64)))
ACCOUNT = str(MAIN.pubkey())
LIMITS = RiskLimits(
    risk_percent=Decimal(1),
    max_leverage=3,
    taker_fee_rate=Decimal(0),
    slippage_percent=Decimal("0.5"),
)


class FakeVenue:
    """Just enough of Pacifica's REST API to exercise the trade flow."""

    def __init__(self, *, mark: str = "150", attach_stops: bool = True) -> None:
        self.mark = mark
        self.attach_stops = attach_stops
        self.fail_tpsl = False
        self.fail_close = False
        self.timeout_orders = False
        self.positions: list[dict[str, Any]] = []
        self.orders: list[dict[str, Any]] = []
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if request.method == "GET":
            return self._get(path)
        body = json.loads(request.content)
        self.posts.append((path, body))
        return self._post(path, body, request)

    def _get(self, path: str) -> httpx.Response:
        if path == "/info":
            data: Any = [
                {
                    "symbol": "SOL",
                    "tick_size": "0.01",
                    "lot_size": "0.01",
                    "max_leverage": 20,
                    "min_order_size": "10",
                    "max_order_size": "1000000",
                }
            ]
        elif path == "/info/prices":
            data = [{"symbol": "SOL", "mark": self.mark, "mid": self.mark, "funding": "0.0001"}]
        elif path == "/account":
            data = {
                "account_equity": "1000",
                "available_to_spend": "1000",
                "total_margin_used": "0",
            }
        elif path == "/positions":
            data = self.positions
        elif path == "/orders":
            data = self.orders
        else:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json={"success": True, "data": data})

    def _post(  # noqa: PLR0912 — one branch per emulated endpoint
        self, path: str, body: dict[str, Any], request: httpx.Request
    ) -> httpx.Response:
        if path == "/orders/create_market":
            if self.timeout_orders:
                raise httpx.ReadTimeout("timed out", request=request)
            if body["reduce_only"]:
                if self.fail_close:
                    return httpx.Response(500, json={"error": "engine busy"})
                self.positions.clear()
                return httpx.Response(200, json={"order_id": 2})
            self.positions.append(
                {
                    "symbol": body["symbol"],
                    "side": body["side"],
                    "amount": body["amount"],
                    "entry_price": self.mark,
                }
            )
            if self.attach_stops:
                for leg in ("stop_loss", "take_profit"):
                    if leg in body:
                        self._add_stop(body["symbol"], body["side"], body[leg]["stop_price"])
            return httpx.Response(200, json={"order_id": 1})
        if path == "/positions/tpsl":
            if self.fail_tpsl:
                return httpx.Response(400, json={"error": "Position not found", "code": 400})
            # Replaces every trigger on the position with the legs sent.
            self.orders = [o for o in self.orders if o["symbol"] != body["symbol"]]
            entry_side = "ask" if body["side"] == "bid" else "bid"
            for leg in ("stop_loss", "take_profit"):
                if leg in body:
                    self._add_stop(body["symbol"], entry_side, body[leg]["stop_price"])
            return httpx.Response(200, json={"success": True})
        if path == "/orders/cancel_all":
            self.orders = [o for o in self.orders if o["symbol"] != body["symbol"]]
            return httpx.Response(200, json={"cancelled_count": 1})
        if path == "/account/leverage":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404, json={"error": "not found"})

    def _add_stop(self, symbol: str, entry_side: str, stop_price: str) -> None:
        self.orders.append(
            {
                "symbol": symbol,
                "side": "ask" if entry_side == "bid" else "bid",
                "stop_price": stop_price,
                "reduce_only": True,
                "order_type": "stop_market",
            }
        )

    def paths(self) -> list[str]:
        return [path for path, _ in self.posts]


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def venue() -> FakeVenue:
    return FakeVenue()


@pytest.fixture
async def client(venue: FakeVenue) -> Any:
    signer = Signer(account=ACCOUNT, keypair=AGENT)
    async with PacificaClient(
        PacificaNetwork.TESTNET,
        account=ACCOUNT,
        signer=signer,
        transport=httpx.MockTransport(venue.handler),
    ) as client:
        yield client


async def _open(client: PacificaClient, *, execute: bool = True, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "symbol": "SOL",
        "direction": Direction.LONG,
        "stop_loss": Decimal(145),
        "take_profit": Decimal(160),
        "limits": LIMITS,
        "execute": execute,
        "sleep": _no_sleep,
    }
    arguments.update(overrides)
    return await open_position(client, **arguments)


async def test_dry_run_sends_nothing(client: PacificaClient, venue: FakeVenue) -> None:
    result = await _open(client, execute=False)
    assert not result.executed
    assert venue.posts == []
    assert result.plan.amount > 0


async def test_long_opens_with_sl_and_tp_in_the_same_request(
    client: PacificaClient, venue: FakeVenue
) -> None:
    result = await _open(client)

    assert result.executed
    assert result.stop_confirmed
    assert venue.paths() == ["/account/leverage", "/orders/create_market"]
    order = venue.posts[1][1]
    assert order["side"] == "bid"
    assert order["stop_loss"] == {"stop_price": "145"}
    assert order["take_profit"] == {"stop_price": "160"}
    assert order["agent_wallet"] == str(AGENT.pubkey())
    assert order["account"] == ACCOUNT
    assert Decimal(order["amount"]) == result.plan.amount


async def test_short_uses_the_ask_side(client: PacificaClient, venue: FakeVenue) -> None:
    await _open(
        client,
        direction=Direction.SHORT,
        stop_loss=Decimal(155),
        take_profit=Decimal(140),
    )
    order = venue.posts[1][1]
    assert order["side"] == "ask"
    position = await client.position("SOL")
    assert position is not None
    assert not position.is_long
    assert await has_stop_loss(client, position)


async def test_missing_stop_is_reattached(client: PacificaClient, venue: FakeVenue) -> None:
    venue.attach_stops = False
    result = await _open(client)
    assert result.stop_confirmed
    assert venue.paths()[-1] == "/positions/tpsl"
    assert venue.posts[-1][1]["side"] == "ask"  # the side that closes a long


async def test_position_is_flattened_when_the_stop_cannot_be_attached(
    client: PacificaClient, venue: FakeVenue
) -> None:
    venue.attach_stops = False
    venue.fail_tpsl = True
    with pytest.raises(TradeRefusedError, match="closed at market"):
        await _open(client)
    assert venue.positions == []
    close = venue.posts[-1][1]
    assert close["reduce_only"] is True
    assert close["side"] == "ask"


async def test_unprotected_position_that_cannot_be_closed_is_reported_loudly(
    client: PacificaClient, venue: FakeVenue
) -> None:
    venue.attach_stops = False
    venue.fail_tpsl = True
    venue.fail_close = True
    with pytest.raises(TradeRefusedError, match="WITHOUT a stop loss"):
        await _open(client)


async def test_second_position_on_the_same_market_is_refused(
    client: PacificaClient, venue: FakeVenue
) -> None:
    await _open(client)
    sent = len(venue.posts)
    with pytest.raises(TradeRefusedError, match="already open"):
        await _open(client)
    assert len(venue.posts) == sent


async def test_timeout_on_an_order_is_reported_as_unknown(
    client: PacificaClient, venue: FakeVenue
) -> None:
    venue.timeout_orders = True
    with pytest.raises(OrderOutcomeUnknownError, match="Check open positions"):
        await _open(client)


async def test_close_is_reduce_only_on_the_opposite_side(
    client: PacificaClient, venue: FakeVenue
) -> None:
    await _open(client)
    await close_position(client, symbol="SOL", slippage_percent=Decimal("0.5"), execute=True)

    close = next(body for path, body in venue.posts if body.get("reduce_only") is True)
    assert close["side"] == "ask"
    assert venue.paths()[-1] == "/orders/cancel_all"
    assert await client.position("SOL") is None


async def test_close_without_a_position_is_refused(client: PacificaClient) -> None:
    with pytest.raises(TradeRefusedError, match="no open SOL position"):
        await close_position(client, symbol="SOL", slippage_percent=Decimal(1), execute=True)


async def test_moving_the_stop_keeps_the_target(client: PacificaClient, venue: FakeVenue) -> None:
    await _open(client)
    await update_tpsl(client, symbol="SOL", stop_loss=Decimal(148), take_profit=None, execute=True)
    assert venue.posts[-1][1]["stop_loss"] == {"stop_price": "148"}
    assert venue.posts[-1][1]["take_profit"] == {"stop_price": "160"}


async def test_moving_only_the_target_resends_the_existing_stop(
    client: PacificaClient, venue: FakeVenue
) -> None:
    await _open(client)
    await update_tpsl(client, symbol="SOL", stop_loss=None, take_profit=Decimal(165), execute=True)
    sent = venue.posts[-1][1]
    assert sent["take_profit"] == {"stop_price": "165"}
    assert sent["stop_loss"] == {"stop_price": "145"}


@pytest.mark.parametrize(
    ("stop", "target", "fragment"),
    [("151", None, "trigger immediately"), (None, "149", "wrong side")],
)
async def test_stop_or_target_on_the_wrong_side_is_refused(
    client: PacificaClient, venue: FakeVenue, stop: str | None, target: str | None, fragment: str
) -> None:
    await _open(client)
    sent = len(venue.posts)
    with pytest.raises(TradeRefusedError, match=fragment):
        await update_tpsl(
            client,
            symbol="SOL",
            stop_loss=Decimal(stop) if stop else None,
            take_profit=Decimal(target) if target else None,
            execute=True,
        )
    assert len(venue.posts) == sent


async def test_read_only_client_cannot_sign(venue: FakeVenue) -> None:
    async with PacificaClient(
        PacificaNetwork.TESTNET, account=ACCOUNT, transport=httpx.MockTransport(venue.handler)
    ) as client:
        with pytest.raises(PacificaError, match="read-only"):
            await client.cancel_all_orders("SOL")


async def test_venue_rejection_surfaces_its_reason(venue: FakeVenue) -> None:
    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "Invalid leverage", "code": 400})

    signer = Signer(account=ACCOUNT, keypair=AGENT)
    async with PacificaClient(
        PacificaNetwork.TESTNET,
        account=ACCOUNT,
        signer=signer,
        transport=httpx.MockTransport(reject),
    ) as client:
        with pytest.raises(PacificaError, match="Invalid leverage"):
            await client.set_leverage("SOL", 3)


async def test_requests_go_to_the_versioned_api_path() -> None:
    seen: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"success": True, "data": []})

    async with PacificaClient(
        PacificaNetwork.MAINNET, account=ACCOUNT, transport=httpx.MockTransport(record)
    ) as client:
        await client.positions()
    assert seen == [f"https://api.pacifica.fi/api/v1/positions?account={ACCOUNT}"]


def test_signer_for_another_account_is_refused() -> None:
    other = str(AGENT.pubkey())
    with pytest.raises(ValueError, match="different account"):
        PacificaClient(
            PacificaNetwork.TESTNET,
            account=ACCOUNT,
            signer=Signer(account=other, keypair=AGENT),
        )
