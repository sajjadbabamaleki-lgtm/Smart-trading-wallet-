"""Pacifica REST client.

Endpoints and field names follow Pacifica's API reference and the official
Python SDK (`pacifica-fi/python-sdk`). Response parsing is tolerant, like the
Hyperliquid layer: unknown fields are ignored, and a missing field fails
loudly instead of turning into a zero.

**Ambiguous outcomes are not failures.** If an order request times out, the
venue may still have received it. `OrderOutcomeUnknownError` is raised instead of a
generic error so the caller checks positions before trying again, rather than
opening the same trade twice (Phase 6 §41).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Final

import httpx

from libs.exchange.pacifica.signing import Signer

REQUEST_TIMEOUT_SECONDS: Final = 10.0


class PacificaNetwork(StrEnum):
    TESTNET = "TESTNET"
    MAINNET = "MAINNET"

    @property
    def rest_url(self) -> str:
        return _REST_URLS[self]


_REST_URLS: Final = {
    PacificaNetwork.TESTNET: "https://test-api.pacifica.fi/api/v1",
    PacificaNetwork.MAINNET: "https://api.pacifica.fi/api/v1",
}


class PacificaError(RuntimeError):
    """The venue rejected a request, or answered with something unparseable."""


class OrderOutcomeUnknownError(PacificaError):
    """An order request may or may not have reached the venue."""


def _decimal(record: dict[str, Any], key: str) -> Decimal:
    value = record.get(key)
    if value is None:
        raise PacificaError(f"response is missing {key!r}")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise PacificaError(f"{key!r} is not a number: {value!r}") from exc


def format_decimal(value: Decimal) -> str:
    """Plain decimal string, as the API expects: no exponent, no trailing zeros."""
    text = format(value.normalize(), "f")
    return text if text != "-0" else "0"


@dataclass(frozen=True)
class MarketSpec:
    symbol: str
    tick_size: Decimal
    lot_size: Decimal
    max_leverage: Decimal
    min_order_usd: Decimal
    max_order_usd: Decimal | None

    @classmethod
    def parse(cls, record: dict[str, Any]) -> MarketSpec:
        max_order = record.get("max_order_size")
        return cls(
            symbol=str(record["symbol"]),
            tick_size=_decimal(record, "tick_size"),
            lot_size=_decimal(record, "lot_size"),
            max_leverage=_decimal(record, "max_leverage"),
            min_order_usd=_decimal(record, "min_order_size"),
            max_order_usd=Decimal(str(max_order)) if max_order is not None else None,
        )


@dataclass(frozen=True)
class PriceSnapshot:
    symbol: str
    mark: Decimal
    mid: Decimal
    funding: Decimal | None

    @classmethod
    def parse(cls, record: dict[str, Any]) -> PriceSnapshot:
        funding = record.get("funding")
        return cls(
            symbol=str(record["symbol"]),
            mark=_decimal(record, "mark"),
            mid=_decimal(record, "mid"),
            funding=Decimal(str(funding)) if funding is not None else None,
        )


@dataclass(frozen=True)
class AccountSnapshot:
    equity: Decimal
    available: Decimal
    margin_used: Decimal

    @classmethod
    def parse(cls, record: dict[str, Any]) -> AccountSnapshot:
        return cls(
            equity=_decimal(record, "account_equity"),
            available=_decimal(record, "available_to_spend"),
            margin_used=_decimal(record, "total_margin_used"),
        )


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    side: str
    """`bid` is long, `ask` is short — Pacifica's own vocabulary."""
    amount: Decimal
    entry_price: Decimal

    @property
    def is_long(self) -> bool:
        return self.side == "bid"

    @classmethod
    def parse(cls, record: dict[str, Any]) -> PositionSnapshot:
        side = str(record["side"])
        if side not in ("bid", "ask"):
            raise PacificaError(f"unknown position side {side!r}")
        return cls(
            symbol=str(record["symbol"]),
            side=side,
            amount=_decimal(record, "amount"),
            entry_price=_decimal(record, "entry_price"),
        )


@dataclass(frozen=True)
class OrderSnapshot:
    symbol: str
    side: str
    stop_price: Decimal | None
    reduce_only: bool
    order_type: str

    @classmethod
    def parse(cls, record: dict[str, Any]) -> OrderSnapshot:
        stop = record.get("stop_price")
        return cls(
            symbol=str(record["symbol"]),
            side=str(record["side"]),
            stop_price=Decimal(str(stop)) if stop is not None else None,
            reduce_only=bool(record.get("reduce_only", False)),
            order_type=str(record.get("order_type", "")),
        )


@dataclass(frozen=True)
class StopLeg:
    """One take-profit or stop-loss leg attached to a position.

    Without `limit_price` the leg fills as a market order when triggered, which
    is what a stop loss should do: a limit stop can be skipped in a fast move
    and leave the position unprotected.
    """

    stop_price: Decimal
    limit_price: Decimal | None = None

    def payload(self) -> dict[str, str]:
        body = {"stop_price": format_decimal(self.stop_price)}
        if self.limit_price is not None:
            body["limit_price"] = format_decimal(self.limit_price)
        return body


def _now_ms() -> int:
    return int(time.time() * 1_000)


class PacificaClient:
    """Thin async client. One instance per account and network."""

    def __init__(
        self,
        network: PacificaNetwork,
        *,
        account: str,
        signer: Signer | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        now_ms: Callable[[], int] = _now_ms,
    ) -> None:
        if signer is not None and signer.account != account:
            raise ValueError("signer is bound to a different account")
        self.network = network
        self.account = account
        self._signer = signer
        self._now_ms = now_ms
        self._http = httpx.AsyncClient(
            base_url=network.rest_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=transport,
            headers={"Content-Type": "application/json"},
        )

    async def __aenter__(self) -> PacificaClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        try:
            response = await self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise PacificaError(f"GET {path} failed: {type(exc).__name__}") from exc
        return self._unwrap(path, response)

    async def _post(
        self, path: str, operation: str, payload: dict[str, Any], *, places_order: bool
    ) -> Any:
        if self._signer is None:
            raise PacificaError("no signing key configured; this client is read-only")
        body = self._signer.sign(operation, payload, timestamp_ms=self._now_ms())
        try:
            response = await self._http.post(path, json=body)
        except httpx.TransportError as exc:
            if places_order:
                raise OrderOutcomeUnknownError(
                    f"POST {path} did not complete ({type(exc).__name__}); the order may "
                    "or may not exist. Check open positions before retrying."
                ) from exc
            raise PacificaError(f"POST {path} failed: {type(exc).__name__}") from exc
        return self._unwrap(path, response)

    @staticmethod
    def _unwrap(path: str, response: httpx.Response) -> Any:
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code >= 400:  # noqa: PLR2004
            detail = body.get("error") if isinstance(body, dict) else response.text[:200]
            raise PacificaError(f"{path} rejected ({response.status_code}): {detail}")
        if isinstance(body, dict):
            if body.get("success") is False:
                raise PacificaError(f"{path} rejected: {body.get('error')}")
            if "data" in body:
                return body["data"]
        return body

    # ------------------------------------------------------------------
    # Reads — no signature needed
    # ------------------------------------------------------------------

    async def markets(self) -> dict[str, MarketSpec]:
        data = await self._get("/info")
        specs = (MarketSpec.parse(record) for record in _records(data))
        return {spec.symbol: spec for spec in specs}

    async def market(self, symbol: str) -> MarketSpec:
        markets = await self.markets()
        if symbol not in markets:
            raise PacificaError(f"{symbol} is not listed on Pacifica {self.network.value}")
        return markets[symbol]

    async def price(self, symbol: str) -> PriceSnapshot:
        for record in _records(await self._get("/info/prices")):
            if record.get("symbol") == symbol:
                return PriceSnapshot.parse(record)
        raise PacificaError(f"no price for {symbol}")

    async def account_state(self) -> AccountSnapshot:
        data = await self._get("/account", {"account": self.account})
        # The reference shows `data` both as an object and as a one-item list.
        records = _records(data)
        if not records:
            raise PacificaError("account not found; has it been funded on this network?")
        return AccountSnapshot.parse(records[0])

    async def positions(self) -> tuple[PositionSnapshot, ...]:
        data = await self._get("/positions", {"account": self.account})
        return tuple(PositionSnapshot.parse(record) for record in _records(data))

    async def position(self, symbol: str) -> PositionSnapshot | None:
        return next((p for p in await self.positions() if p.symbol == symbol), None)

    async def open_orders(self) -> tuple[OrderSnapshot, ...]:
        data = await self._get("/orders", {"account": self.account})
        return tuple(OrderSnapshot.parse(record) for record in _records(data))

    # ------------------------------------------------------------------
    # Writes — signed
    # ------------------------------------------------------------------

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        await self._post(
            "/account/leverage",
            "update_leverage",
            {"symbol": symbol, "leverage": leverage},
            places_order=False,
        )

    async def market_order(  # noqa: PLR0913 — mirrors the venue's order fields
        self,
        *,
        symbol: str,
        side: str,
        amount: Decimal,
        slippage_percent: Decimal,
        client_order_id: str,
        reduce_only: bool = False,
        take_profit: StopLeg | None = None,
        stop_loss: StopLeg | None = None,
    ) -> Any:
        """Market order, optionally opening its TP/SL in the same request.

        Attaching TP and SL here, rather than in a second call, means the
        position is never live without its stop loss.
        """
        payload: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "amount": format_decimal(amount),
            "slippage_percent": format_decimal(slippage_percent),
            "reduce_only": reduce_only,
            "client_order_id": client_order_id,
        }
        if take_profit is not None:
            payload["take_profit"] = take_profit.payload()
        if stop_loss is not None:
            payload["stop_loss"] = stop_loss.payload()
        return await self._post(
            "/orders/create_market", "create_market_order", payload, places_order=True
        )

    async def set_position_tpsl(
        self,
        *,
        symbol: str,
        closing_side: str,
        take_profit: StopLeg | None = None,
        stop_loss: StopLeg | None = None,
    ) -> None:
        """Replace TP/SL on an open position.

        `closing_side` is the side that exits the position — `ask` for a long —
        as in the SDK's `create_position_tpsl.py` example.
        """
        if take_profit is None and stop_loss is None:
            raise ValueError("at least one of take_profit or stop_loss is required")
        payload: dict[str, Any] = {"symbol": symbol, "side": closing_side}
        if take_profit is not None:
            payload["take_profit"] = take_profit.payload()
        if stop_loss is not None:
            payload["stop_loss"] = stop_loss.payload()
        await self._post("/positions/tpsl", "set_position_tpsl", payload, places_order=False)

    async def cancel_all_orders(self, symbol: str) -> Any:
        return await self._post(
            "/orders/cancel_all",
            "cancel_all_orders",
            {"all_symbols": False, "exclude_reduce_only": False, "symbol": symbol},
            places_order=False,
        )


def _records(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [record for record in data if isinstance(record, dict)]
    raise PacificaError(f"unexpected response shape: {type(data).__name__}")
