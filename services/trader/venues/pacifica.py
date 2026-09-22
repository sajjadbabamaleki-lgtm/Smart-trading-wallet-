"""Pacifica (Solana) behind the trader's `Venue` interface."""

from __future__ import annotations

import uuid
from decimal import Decimal

from libs.exchange.pacifica.client import MarketSpec, PacificaClient, PacificaNetwork, StopLeg
from services.trader.venue import (
    AccountView,
    Direction,
    MarketRules,
    PositionView,
    TriggerView,
)


def _rules(spec: MarketSpec) -> MarketRules:
    return MarketRules(
        symbol=spec.symbol,
        lot_size=spec.lot_size,
        max_leverage=int(spec.max_leverage),
        min_order_usd=spec.min_order_usd,
        max_order_usd=spec.max_order_usd,
        tick_size=spec.tick_size,
    )


def _closing_side(is_long: bool) -> str:
    return "ask" if is_long else "bid"


class PacificaVenue:
    def __init__(self, client: PacificaClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "PACIFICA"

    @property
    def is_mainnet(self) -> bool:
        return self._client.network is PacificaNetwork.MAINNET

    @property
    def account_address(self) -> str:
        return self._client.account

    async def market(self, symbol: str) -> MarketRules:
        return _rules(await self._client.market(symbol))

    async def price(self, symbol: str) -> Decimal:
        return (await self._client.price(symbol)).mark

    async def account(self) -> AccountView:
        state = await self._client.account_state()
        return AccountView(equity=state.equity, available=state.available)

    async def positions(self) -> tuple[PositionView, ...]:
        return tuple(
            PositionView(
                symbol=p.symbol, is_long=p.is_long, amount=p.amount, entry_price=p.entry_price
            )
            for p in await self._client.positions()
        )

    async def triggers(self, symbol: str) -> tuple[TriggerView, ...]:
        return tuple(
            TriggerView(symbol=o.symbol, trigger_price=o.stop_price, closes_long=o.side == "ask")
            for o in await self._client.open_orders()
            if o.symbol == symbol and o.stop_price is not None
        )

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        await self._client.set_leverage(symbol, leverage)

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
        await self._client.market_order(
            symbol=market.symbol,
            side="bid" if direction is Direction.LONG else "ask",
            amount=amount,
            slippage_percent=slippage_percent,
            client_order_id=str(uuid.uuid4()),
            take_profit=StopLeg(take_profit) if take_profit is not None else None,
            stop_loss=StopLeg(stop_loss),
        )

    async def set_protection(
        self,
        position: PositionView,
        *,
        stop_loss: Decimal | None,
        take_profit: Decimal | None,
    ) -> None:
        await self._client.set_position_tpsl(
            symbol=position.symbol,
            closing_side=_closing_side(position.is_long),
            take_profit=StopLeg(take_profit) if take_profit is not None else None,
            stop_loss=StopLeg(stop_loss) if stop_loss is not None else None,
        )

    async def close(self, position: PositionView, *, slippage_percent: Decimal) -> None:
        await self._client.market_order(
            symbol=position.symbol,
            side=_closing_side(position.is_long),
            amount=position.amount,
            slippage_percent=slippage_percent,
            client_order_id=str(uuid.uuid4()),
            reduce_only=True,
        )
        # Leftover TP/SL orders are reduce-only and cannot open a new position,
        # but they are removed so the book is clean.
        await self._client.cancel_all_orders(position.symbol)

    async def aclose(self) -> None:
        await self._client.aclose()
