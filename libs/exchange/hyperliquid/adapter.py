"""The Hyperliquid implementation of `ExchangeAdapter`.

This is the first component in the project that can change an account balance,
so its refusals are as much a part of it as its capabilities.

**It cannot be constructed against mainnet.** Not "should not" - the
constructor raises. Build 0.1 Rev.2 §42 blocks mainnet execution structurally,
and a structural block that lives only in configuration is one environment
variable away from not existing. Settings already refuse a mainnet execution
environment; this refuses again, because a component that assumes an upstream
check happened is a component that stops enforcing it the day the upstream
changes.

**An ambiguous outcome is reported, never guessed.** A timeout or a dropped
connection on submission returns `OrderState.UNKNOWN`. It does not raise, and
it does not report failure: the venue may well have the order, and an exception
that hides a possibly-live order is how a timeout becomes a double position
(Build 0.1 Rev.1 §53, Phase 6 §41). Everything else this class does may raise;
`place_order` may not.

**Idempotency is carried by the client order id.** The venue id is derived from
the intent id by a pure function, so a retry presents the id the venue may
already have seen and the venue - not this code - decides it is a duplicate.

Reads go to `/info` unsigned, writes to `/exchange` signed. They are separate
methods on separate paths on purpose: nothing in the read path can be made to
sign anything.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

import httpx

from libs.config import Settings
from libs.domain.clock import Clock, SystemClock
from libs.exchange.hyperliquid.signing import sign_l1_action, signer_address
from libs.exchange.hyperliquid.wire import (
    cancel_action,
    cloid_for,
    market_limit_price,
    order_action,
)
from libs.exchange.models import (
    AccountState,
    Fill,
    MarketState,
    OrderRequest,
    OrderState,
    OrderStatus,
    Position,
)
from libs.observability.logging import get_logger
from libs.schemas.enums import ExecutionEnvironment, Side

logger = get_logger(__name__)

VENUE: Final = "hyperliquid"

# Crossed by this much, an immediate-or-cancel order stands in for a market
# order. Wide enough to fill against a normal book, bounded enough that a
# vanished book cannot fill it at any price.
DEFAULT_SLIPPAGE: Final = Decimal("0.005")

# A submission that has not answered by now is ambiguous, not failed.
SUBMIT_TIMEOUT_SECONDS: Final = 10.0
READ_TIMEOUT_SECONDS: Final = 10.0


class VenueRefusedError(RuntimeError):
    """The venue rejected a request outright, with a reason it stated."""


class UnsupportedEnvironmentError(RuntimeError):
    """Construction was attempted somewhere this adapter must not run."""


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _required(value: object, field: str) -> Decimal:
    parsed = _decimal(value)
    if parsed is None:
        raise VenueRefusedError(f"venue response is missing {field}")
    return parsed


class HyperliquidAdapter:
    """Order placement, cancellation and account reads against Hyperliquid testnet."""

    def __init__(
        self,
        settings: Settings,
        *,
        clock: Clock | None = None,
        client: httpx.AsyncClient | None = None,
        slippage: Decimal = DEFAULT_SLIPPAGE,
    ) -> None:
        if settings.execution_environment is not ExecutionEnvironment.TESTNET:
            raise UnsupportedEnvironmentError(
                f"execution_environment is {settings.execution_environment.value}; this "
                "adapter runs only on TESTNET. Mainnet execution is blocked for the "
                "whole of Build 0.1."
            )
        endpoint = settings.venue_endpoint
        if endpoint is None:  # pragma: no cover - TESTNET always has one
            raise UnsupportedEnvironmentError("no venue endpoint for this environment")
        if not settings.testnet_api_wallet_private_key:
            raise UnsupportedEnvironmentError("no testnet API wallet key is configured")

        self._settings = settings
        self._endpoint = endpoint.rstrip("/")
        self._clock = clock or SystemClock()
        self._slippage = slippage
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=READ_TIMEOUT_SECONDS)
        self._key = settings.testnet_api_wallet_private_key
        self._meta: dict[str, tuple[int, int]] = {}

    @property
    def venue(self) -> str:
        return VENUE

    @property
    def address(self) -> str:
        """The account orders are placed for.

        The configured address when there is one, otherwise the signing key's
        own. An API wallet signs on behalf of a different account, so the two
        are not interchangeable and the configured one wins.
        """
        return self._settings.testnet_api_wallet_address or signer_address(self._key)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ---- reads -----------------------------------------------------------

    async def _info(self, body: dict[str, Any]) -> Any:
        response = await self._client.post(f"{self._endpoint}/info", json=body)
        response.raise_for_status()
        return response.json()

    async def _asset(self, asset: str) -> tuple[int, int]:
        """The venue's index and size precision for an asset, fetched once.

        Cached because it is the venue's own catalogue and does not change
        within a run, and because an order that has to fetch it first is an
        order that is slower for no reason.
        """
        if not self._meta:
            meta = await self._info({"type": "meta"})
            self._meta = {
                entry["name"].upper(): (index, int(entry["szDecimals"]))
                for index, entry in enumerate(meta["universe"])
            }
        key = asset.upper()
        if key not in self._meta:
            raise VenueRefusedError(f"the venue does not list {asset}")
        return self._meta[key]

    async def get_market_state(self, asset: str) -> MarketState:
        index, _ = await self._asset(asset)
        book, contexts = await asyncio.gather(
            self._info({"type": "l2Book", "coin": asset.upper()}),
            self._info({"type": "metaAndAssetCtxs"}),
        )
        bids, asks = book["levels"][0], book["levels"][1]
        context = contexts[1][index]
        return MarketState(
            asset=asset.upper(),
            instrument=f"{asset.upper()}-PERP",
            bid_price=_decimal(bids[0]["px"]) if bids else None,
            ask_price=_decimal(asks[0]["px"]) if asks else None,
            mark_price=_decimal(context.get("markPx")),
            oracle_price=_decimal(context.get("oraclePx")),
            funding_rate=_decimal(context.get("funding")),
            open_interest=_decimal(context.get("openInterest")),
            observed_at=self._clock.now(),
            local_receive_monotonic_ns=time.monotonic_ns(),
        )

    async def get_account_state(self) -> AccountState:
        state = await self._info({"type": "clearinghouseState", "user": self.address})
        summary = state["marginSummary"]
        return AccountState(
            equity=_required(summary.get("accountValue"), "accountValue"),
            available_margin=_required(state.get("withdrawable"), "withdrawable"),
            positions=tuple(self._positions(state)),
            observed_at=self._clock.now(),
        )

    @staticmethod
    def _positions(state: dict[str, Any]) -> list[Position]:
        positions: list[Position] = []
        for entry in state.get("assetPositions", ()):
            held = entry["position"]
            size = _decimal(held.get("szi")) or Decimal(0)
            if size == 0:
                continue
            leverage = held.get("leverage") or {}
            positions.append(
                Position(
                    asset=str(held["coin"]).upper(),
                    size=size,
                    entry_price=_decimal(held.get("entryPx")),
                    unrealized_pnl=_decimal(held.get("unrealizedPnl")),
                    liquidation_price=_decimal(held.get("liquidationPx")),
                    leverage=_decimal(leverage.get("value")),
                    margin_used=_decimal(held.get("marginUsed")),
                )
            )
        return positions

    async def get_positions(self) -> tuple[Position, ...]:
        return (await self.get_account_state()).positions

    async def get_orders(self) -> tuple[OrderStatus, ...]:
        orders = await self._info({"type": "openOrders", "user": self.address})
        observed = self._clock.now()
        return tuple(
            OrderStatus(
                client_order_id=str(order.get("cloid") or ""),
                venue_order_id=str(order["oid"]),
                state=OrderState.ACKNOWLEDGED,
                observed_at=observed,
            )
            for order in orders
        )

    async def get_fills(self, *, since: str | None = None) -> tuple[Fill, ...]:
        body: dict[str, Any] = {"type": "userFills", "user": self.address}
        if since is not None:
            body = {"type": "userFillsByTime", "user": self.address, "startTime": int(since)}
        fills = await self._info(body)
        return tuple(
            Fill(
                fill_id=str(fill["tid"]),
                client_order_id=str(fill["cloid"]) if fill.get("cloid") else None,
                venue_order_id=str(fill.get("oid")) if fill.get("oid") is not None else None,
                asset=str(fill["coin"]).upper(),
                # The venue reports the side of our own fill, so it is read
                # directly rather than inferred from a position change.
                side=Side.BUY if str(fill["side"]).upper() in {"B", "BUY"} else Side.SELL,
                price=_required(fill.get("px"), "px"),
                quantity=_required(fill.get("sz"), "sz"),
                fee=_decimal(fill.get("fee")),
                is_maker=(not fill["crossed"]) if "crossed" in fill else None,
                # The venue's own millisecond stamp for the fill, not ours. A
                # fill is a fact about when the venue matched, and restamping
                # it on arrival would make every latency figure derived from it
                # measure this process instead.
                filled_at=datetime.fromtimestamp(int(fill["time"]) / 1000, tz=UTC),
            )
            for fill in fills
        )

    # ---- writes ----------------------------------------------------------

    async def _exchange(self, action: dict[str, Any], *, timeout: float) -> Any:
        nonce = int(self._clock.now().timestamp() * 1000)
        signature = sign_l1_action(
            action,
            private_key=self._key,
            nonce=nonce,
            # Constant, not derived from settings: the constructor has already
            # refused every environment except TESTNET, so there is no path
            # here that should be able to produce a mainnet signature.
            is_mainnet=False,
        )
        response = await self._client.post(
            f"{self._endpoint}/exchange",
            json={"action": action, "nonce": nonce, "signature": signature, "vaultAddress": None},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    async def place_order(self, request: OrderRequest) -> OrderStatus:
        """Submit one order, and never hide one that might be live."""
        index, sz_decimals = await self._asset(request.asset)
        limit_price = request.limit_price
        if limit_price is None:
            book = await self.get_market_state(request.asset)
            reference = book.ask_price if request.side is Side.BUY else book.bid_price
            if reference is None:
                raise VenueRefusedError(
                    f"{request.asset} has no {'ask' if request.side is Side.BUY else 'bid'} "
                    "to price a market order against"
                )
            limit_price = market_limit_price(
                reference=reference,
                side=request.side,
                slippage=self._slippage,
                sz_decimals=sz_decimals,
            )

        action = order_action(
            request, asset_index=index, sz_decimals=sz_decimals, limit_price=limit_price
        )
        try:
            payload = await self._exchange(action, timeout=SUBMIT_TIMEOUT_SECONDS)
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            # Deliberately not re-raised. We do not know whether the venue has
            # this order, and UNKNOWN is the only honest answer; reconciliation
            # asks the venue, which is the only thing that can know.
            logger.warning(
                "order_outcome_unknown",
                extra={
                    "client_order_id": request.client_order_id,
                    "intent_id": request.intent_id,
                    "correlation_id": request.correlation_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return OrderStatus(
                client_order_id=request.client_order_id,
                state=OrderState.UNKNOWN,
                reject_reason=f"submission outcome unknown: {type(exc).__name__}",
                observed_at=self._clock.now(),
            )
        return self._read_order_result(payload, request)

    def _read_order_result(self, payload: Any, request: OrderRequest) -> OrderStatus:
        observed = self._clock.now()
        base = {"client_order_id": request.client_order_id, "observed_at": observed}

        if payload.get("status") != "ok":
            return OrderStatus(
                **base, state=OrderState.REJECTED, reject_reason=str(payload.get("response"))
            )

        statuses = payload["response"]["data"]["statuses"]
        if not statuses:  # pragma: no cover - the venue answers one per order
            return OrderStatus(**base, state=OrderState.UNKNOWN, reject_reason="no status returned")
        status = statuses[0]

        if "error" in status:
            return OrderStatus(
                **base, state=OrderState.REJECTED, reject_reason=str(status["error"])
            )
        if "resting" in status:
            return OrderStatus(
                **base,
                state=OrderState.ACKNOWLEDGED,
                venue_order_id=str(status["resting"]["oid"]),
            )
        if "filled" in status:
            filled = status["filled"]
            quantity = _required(filled.get("totalSz"), "totalSz")
            return OrderStatus(
                **base,
                state=(
                    OrderState.FILLED
                    if quantity >= request.quantity
                    else OrderState.PARTIALLY_FILLED
                ),
                venue_order_id=str(filled["oid"]),
                filled_quantity=quantity,
                average_fill_price=_decimal(filled.get("avgPx")),
            )
        return OrderStatus(**base, state=OrderState.UNKNOWN, reject_reason=str(status))

    async def cancel_order(self, client_order_id: str) -> OrderStatus:
        """Cancel by our own id. Cancelling something unknown is not an error.

        The asset is read back from the open orders rather than passed in: a
        caller that has to supply it can supply the wrong one, and the venue
        already knows which asset the order it is holding belongs to.
        """
        open_orders = await self._info({"type": "openOrders", "user": self.address})
        wanted = cloid_for(client_order_id)
        match = next((o for o in open_orders if str(o.get("cloid", "")).lower() == wanted), None)
        observed = self._clock.now()
        if match is None:
            return OrderStatus(
                client_order_id=client_order_id,
                state=OrderState.CANCELLED,
                reject_reason="not open at the venue",
                observed_at=observed,
            )
        index, _ = await self._asset(str(match["coin"]))
        payload = await self._exchange(
            cancel_action(asset_index=index, client_order_id=client_order_id),
            timeout=SUBMIT_TIMEOUT_SECONDS,
        )
        if payload.get("status") != "ok":
            return OrderStatus(
                client_order_id=client_order_id,
                state=OrderState.CANCEL_PENDING,
                reject_reason=str(payload.get("response")),
                observed_at=self._clock.now(),
            )
        return OrderStatus(
            client_order_id=client_order_id,
            venue_order_id=str(match["oid"]),
            state=OrderState.CANCELLED,
            observed_at=self._clock.now(),
        )

    def subscribe_events(self, assets: tuple[str, ...]) -> AsyncIterator[object]:
        """Not this class's job.

        The recorder owns the market-data socket (ADR-009), and giving the
        execution adapter a second one would put two components on the same
        feed with no agreement about which is authoritative.
        """
        raise NotImplementedError("market data is the recorder's socket; use services.market_data")
