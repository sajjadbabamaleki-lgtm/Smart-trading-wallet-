"""Hyperliquid behind the trader's `Venue` interface.

Built on the official `hyperliquid-python-sdk`, which does the signing; this
module only decides what to send. It is the same exchange Phantom's in-wallet
perps route to, reached directly.

**Entry and protection are one request.** The entry and its stop loss and take
profit go out together with `grouping="normalTpsl"`, as Hyperliquid's own app
sends them, so the stop exists on the exchange from the moment the position
does. Stops are trigger orders that fill at market, so a fast move cannot skip
past them the way it can skip a limit.

**The bot never holds the main wallet's key.** It signs with an API wallet
approved from the Hyperliquid app. Per Hyperliquid's documentation an API
wallet can trade for the account but cannot withdraw from it.

The SDK is synchronous; calls run in a worker thread so the trader stays async.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Final, TypeVar

import requests
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils.constants import MAINNET_API_URL, TESTNET_API_URL
from hyperliquid.utils.error import Error as SdkError

from libs.exchange.errors import OrderOutcomeUnknownError, VenueError
from services.trader.venue import (
    AccountView,
    Direction,
    MarketRules,
    PositionView,
    TriggerView,
)

REQUEST_TIMEOUT_SECONDS: Final = 10.0
MIN_ORDER_USD: Final = Decimal(10)
"""Hyperliquid rejects orders below $10 of notional."""
PRICE_SIGNIFICANT_FIGURES: Final = 5
PERP_MAX_PRICE_DECIMALS: Final = 6
"""A perp price may have at most `6 - szDecimals` decimals."""
STOP_FILL_SLIPPAGE: Final = Decimal("0.10")
"""How far past its trigger a stop may fill. Wide on purpose: a stop that does
not fill is worse than one that fills badly. Hyperliquid's app uses the same."""

EMPTY_SPOT_META: Final[Any] = {"universe": [], "tokens": []}
"""The trader only uses perps, so spot metadata is not fetched."""

T = TypeVar("T")


def _decimal(value: Any, field: str) -> Decimal:
    if value is None:
        raise VenueError(f"Hyperliquid response is missing {field}")
    return Decimal(str(value))


def _float(value: Decimal) -> float:
    """The SDK takes floats and re-serialises them with at most 8 decimals."""
    return float(value)


def base_url(mainnet: bool) -> str:
    return str(MAINNET_API_URL if mainnet else TESTNET_API_URL)


def check_account(address: str) -> str:
    text = address.strip()
    if not (text.startswith("0x") and len(text) == 42):  # noqa: PLR2004
        raise VenueError(
            f"not a Hyperliquid account address: {text!r} (expected 0x followed by 40 hex digits)"
        )
    try:
        int(text[2:], 16)
    except ValueError as exc:
        raise VenueError(f"not a Hyperliquid account address: {text!r}") from exc
    return text


def load_api_wallet(secret: str) -> Any:
    text = secret.strip()
    if not text:
        raise VenueError("no private key configured")
    try:
        return Account.from_key(text)
    except Exception as exc:  # eth_account raises several unrelated types
        # The key material itself is never included in the message.
        raise VenueError(f"private key is not a valid EVM key ({type(exc).__name__})") from exc


class HyperliquidVenue:
    def __init__(
        self,
        *,
        info: Any,
        exchange: Any | None,
        account_address: str,
        mainnet: bool,
    ) -> None:
        self._info = info
        self._exchange = exchange
        self._account = account_address
        self._mainnet = mainnet
        self._meta: dict[str, dict[str, Any]] | None = None

    @classmethod
    def connect(
        cls, *, mainnet: bool, account_address: str, api_wallet_key: str | None
    ) -> HyperliquidVenue:
        url = base_url(mainnet)
        account = check_account(account_address)
        try:
            info = Info(
                url, skip_ws=True, spot_meta=EMPTY_SPOT_META, timeout=REQUEST_TIMEOUT_SECONDS
            )
            exchange = None
            if api_wallet_key:
                wallet = load_api_wallet(api_wallet_key)
                exchange = Exchange(
                    wallet,
                    url,
                    meta=info.meta(),
                    spot_meta=EMPTY_SPOT_META,
                    account_address=account,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
        except (SdkError, requests.RequestException) as exc:
            raise VenueError(f"could not reach Hyperliquid: {type(exc).__name__}: {exc}") from exc
        return cls(info=info, exchange=exchange, account_address=account, mainnet=mainnet)

    @property
    def name(self) -> str:
        return "HYPERLIQUID"

    @property
    def is_mainnet(self) -> bool:
        return self._mainnet

    @property
    def account_address(self) -> str:
        return self._account

    @property
    def signs_as_api_wallet(self) -> bool:
        """False when the configured key is the main wallet's own key."""
        if self._exchange is None:
            return True
        return str(self._exchange.wallet.address).lower() != self._account.lower()

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    async def _read(self, call: Callable[[], T]) -> T:
        try:
            return await asyncio.to_thread(call)
        except (SdkError, requests.RequestException) as exc:
            raise VenueError(f"Hyperliquid request failed: {type(exc).__name__}: {exc}") from exc

    async def _write(self, call: Callable[[Any], Any], *, places_order: bool) -> Any:
        if self._exchange is None:
            raise VenueError("no API wallet key configured; this connection is read-only")
        exchange = self._exchange
        try:
            response = await asyncio.to_thread(call, exchange)
        except (requests.Timeout, requests.ConnectionError) as exc:
            if places_order:
                raise OrderOutcomeUnknownError(
                    f"the order request did not complete ({type(exc).__name__}); it may or may "
                    "not have reached Hyperliquid. Check open positions before retrying."
                ) from exc
            raise VenueError(f"Hyperliquid request failed: {type(exc).__name__}") from exc
        except (SdkError, requests.RequestException) as exc:
            raise VenueError(f"Hyperliquid rejected the request: {exc}") from exc
        if not isinstance(response, dict) or response.get("status") != "ok":
            detail = response.get("response") if isinstance(response, dict) else response
            raise VenueError(f"Hyperliquid rejected the request: {detail}")
        return response

    @staticmethod
    def _statuses(response: dict[str, Any]) -> list[Any]:
        data = response.get("response", {}).get("data", {})
        statuses = data.get("statuses", []) if isinstance(data, dict) else []
        return list(statuses)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def _universe(self) -> dict[str, dict[str, Any]]:
        if self._meta is None:
            meta = await self._read(self._info.meta)
            self._meta = {asset["name"]: asset for asset in meta["universe"]}
        return self._meta

    async def market(self, symbol: str) -> MarketRules:
        universe = await self._universe()
        asset = universe.get(symbol)
        if asset is None or asset.get("isDelisted"):
            raise VenueError(f"{symbol} is not a listed Hyperliquid perp")
        sz_decimals = int(asset["szDecimals"])
        return MarketRules(
            symbol=symbol,
            lot_size=Decimal(1).scaleb(-sz_decimals),
            max_leverage=int(asset.get("maxLeverage", 1)),
            min_order_usd=MIN_ORDER_USD,
            significant_figures=PRICE_SIGNIFICANT_FIGURES,
            max_price_decimals=PERP_MAX_PRICE_DECIMALS - sz_decimals,
        )

    async def price(self, symbol: str) -> Decimal:
        mids = await self._read(self._info.all_mids)
        if symbol not in mids:
            raise VenueError(f"no Hyperliquid price for {symbol}")
        return _decimal(mids[symbol], f"price of {symbol}")

    async def _user_state(self) -> dict[str, Any]:
        state: dict[str, Any] = await self._read(lambda: self._info.user_state(self._account))
        return state

    async def account(self) -> AccountView:
        summary = (await self._user_state()).get("marginSummary", {})
        equity = _decimal(summary.get("accountValue"), "accountValue")
        used = _decimal(summary.get("totalMarginUsed"), "totalMarginUsed")
        return AccountView(equity=equity, available=equity - used)

    async def positions(self) -> tuple[PositionView, ...]:
        views = []
        for entry in (await self._user_state()).get("assetPositions", []):
            position = entry.get("position", {})
            signed = _decimal(position.get("szi"), "szi")
            if signed == 0:
                continue
            views.append(
                PositionView(
                    symbol=str(position["coin"]),
                    is_long=signed > 0,
                    amount=abs(signed),
                    entry_price=_decimal(position.get("entryPx"), "entryPx"),
                )
            )
        return tuple(views)

    async def _trigger_orders(self, symbol: str) -> list[dict[str, Any]]:
        orders = await self._read(lambda: self._info.frontend_open_orders(self._account))
        return [
            order
            for order in orders
            if order.get("coin") == symbol and order.get("isTrigger") and order.get("reduceOnly")
        ]

    async def triggers(self, symbol: str) -> tuple[TriggerView, ...]:
        return tuple(
            TriggerView(
                symbol=symbol,
                trigger_price=_decimal(order.get("triggerPx"), "triggerPx"),
                closes_long=order.get("side") == "A",
            )
            for order in await self._trigger_orders(symbol)
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        await self._write(lambda ex: ex.update_leverage(leverage, symbol, True), places_order=False)

    @staticmethod
    def _trigger_leg(
        market: MarketRules, *, closes_long: bool, amount: Decimal, trigger: Decimal, kind: str
    ) -> dict[str, Any]:
        trigger = market.round_price(trigger)
        # The worst price the triggered market order may fill at.
        bound = trigger * (1 - STOP_FILL_SLIPPAGE if closes_long else 1 + STOP_FILL_SLIPPAGE)
        return {
            "coin": market.symbol,
            "is_buy": not closes_long,
            "sz": _float(amount),
            "limit_px": _float(market.round_price(bound)),
            "order_type": {
                "trigger": {"triggerPx": _float(trigger), "isMarket": True, "tpsl": kind}
            },
            "reduce_only": True,
        }

    def _protection_legs(
        self,
        market: MarketRules,
        *,
        closes_long: bool,
        amount: Decimal,
        stop_loss: Decimal | None,
        take_profit: Decimal | None,
    ) -> list[dict[str, Any]]:
        legs = []
        if stop_loss is not None:
            legs.append(
                self._trigger_leg(
                    market, closes_long=closes_long, amount=amount, trigger=stop_loss, kind="sl"
                )
            )
        if take_profit is not None:
            legs.append(
                self._trigger_leg(
                    market, closes_long=closes_long, amount=amount, trigger=take_profit, kind="tp"
                )
            )
        return legs

    async def _aggressive_price(
        self, market: MarketRules, *, is_buy: bool, slippage_percent: Decimal
    ) -> Decimal:
        """A marketable limit: Hyperliquid market orders are IOC limits at a slippage bound."""
        reference = await self.price(market.symbol)
        factor = slippage_percent / 100
        return market.round_price(reference * (1 + factor if is_buy else 1 - factor))

    async def open_protected(  # noqa: PLR0913 — one argument per order field
        self,
        *,
        market: MarketRules,
        direction: Direction,
        amount: Decimal,
        slippage_percent: Decimal,
        stop_loss: Decimal,
        take_profit: Decimal | None,
    ) -> None:
        is_buy = direction is Direction.LONG
        entry = {
            "coin": market.symbol,
            "is_buy": is_buy,
            "sz": _float(amount),
            "limit_px": _float(
                await self._aggressive_price(
                    market, is_buy=is_buy, slippage_percent=slippage_percent
                )
            ),
            "order_type": {"limit": {"tif": "Ioc"}},
            "reduce_only": False,
        }
        legs = self._protection_legs(
            market,
            closes_long=is_buy,
            amount=amount,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        response = await self._write(
            lambda ex: ex.bulk_orders([entry, *legs], grouping="normalTpsl"), places_order=True
        )
        statuses = self._statuses(response)
        first = statuses[0] if statuses else None
        if isinstance(first, dict) and "error" in first:
            raise VenueError(f"entry rejected: {first['error']}")
        # A rejected stop leg is not raised here: the trader verifies the stop
        # on the exchange after the fill and re-attaches it or closes.

    async def set_protection(
        self,
        position: PositionView,
        *,
        stop_loss: Decimal | None,
        take_profit: Decimal | None,
    ) -> None:
        market = await self.market(position.symbol)
        old = [
            order
            for order in await self._trigger_orders(position.symbol)
            if (order.get("side") == "A") == position.is_long
        ]
        legs = self._protection_legs(
            market,
            closes_long=position.is_long,
            amount=position.amount,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        # New protection first, then remove the old: the position is never
        # without a stop in between. Overlap is harmless — triggers are
        # reduce-only and cannot close more than the position.
        if legs:
            response = await self._write(lambda ex: ex.bulk_orders(legs), places_order=False)
            errors = [
                s["error"] for s in self._statuses(response) if isinstance(s, dict) and "error" in s
            ]
            if errors:
                raise VenueError(f"TP/SL rejected: {'; '.join(map(str, errors))}")
        await self._cancel(position.symbol, old)

    async def _cancel(self, symbol: str, orders: list[dict[str, Any]]) -> None:
        if not orders:
            return
        requests_ = [{"coin": symbol, "oid": int(order["oid"])} for order in orders]
        await self._write(lambda ex: ex.bulk_cancel(requests_), places_order=False)

    async def close(self, position: PositionView, *, slippage_percent: Decimal) -> None:
        market = await self.market(position.symbol)
        is_buy = not position.is_long
        order = {
            "coin": position.symbol,
            "is_buy": is_buy,
            "sz": _float(position.amount),
            "limit_px": _float(
                await self._aggressive_price(
                    market, is_buy=is_buy, slippage_percent=slippage_percent
                )
            ),
            "order_type": {"limit": {"tif": "Ioc"}},
            "reduce_only": True,
        }
        response = await self._write(lambda ex: ex.bulk_orders([order]), places_order=True)
        statuses = self._statuses(response)
        if statuses and isinstance(statuses[0], dict) and "error" in statuses[0]:
            raise VenueError(f"close rejected: {statuses[0]['error']}")
        # Remaining triggers are reduce-only and cannot open anything, but they
        # are removed so the book is clean.
        await self._cancel(position.symbol, await self._trigger_orders(position.symbol))

    async def aclose(self) -> None:
        return None
