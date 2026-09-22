"""Open, adjust and close one position, with its stop loss always attached.

The rules here are the ones a disciplined trader follows by hand:

- Every position is opened with its stop loss in the same order request.
- After the fill, the stop is confirmed on the venue. If it is missing it is
  set again; if that also fails, the position is closed at market. A position
  is never left open without a stop.
- One position per market. Adding to an open position is refused rather than
  silently changing its size and risk.
- Nothing is sent unless `execute=True`. Without it, every command only prints
  what it would do.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal

from libs.exchange.pacifica.client import (
    PacificaClient,
    PacificaError,
    PositionSnapshot,
    StopLeg,
)
from services.trader.planner import Direction, RiskLimits, TradePlan, plan_trade

FILL_CONFIRM_ATTEMPTS = 10
FILL_CONFIRM_INTERVAL_SECONDS = 0.5


class TradeRefusedError(RuntimeError):
    """The action was not taken. The message says why."""


@dataclass(frozen=True)
class OpenResult:
    plan: TradePlan
    executed: bool
    position: PositionSnapshot | None = None
    stop_confirmed: bool = False


async def build_plan(  # noqa: PLR0913 — keyword-only trade parameters
    client: PacificaClient,
    *,
    symbol: str,
    direction: Direction,
    stop_loss: Decimal,
    take_profit: Decimal | None,
    limits: RiskLimits,
) -> TradePlan:
    market = await client.market(symbol)
    price = await client.price(symbol)
    account = await client.account_state()
    return plan_trade(
        market=market,
        direction=direction,
        entry_price=price.mark,
        stop_loss=stop_loss,
        take_profit=take_profit,
        equity=account.equity,
        available=account.available,
        limits=limits,
    )


async def has_stop_loss(client: PacificaClient, position: PositionSnapshot) -> bool:
    """Whether the venue holds a stop order that would close `position` at a loss."""
    closing_side = "ask" if position.is_long else "bid"
    for order in await client.open_orders():
        if order.symbol != position.symbol or order.side != closing_side:
            continue
        if order.stop_price is None:
            continue
        below_entry = order.stop_price < position.entry_price
        if below_entry == position.is_long:
            return True
    return False


async def _await_position(
    client: PacificaClient, symbol: str, sleep: Callable[[float], Awaitable[None]]
) -> PositionSnapshot | None:
    for _ in range(FILL_CONFIRM_ATTEMPTS):
        position = await client.position(symbol)
        if position is not None:
            return position
        await sleep(FILL_CONFIRM_INTERVAL_SECONDS)
    return None


async def open_position(  # noqa: PLR0913 — keyword-only trade parameters
    client: PacificaClient,
    *,
    symbol: str,
    direction: Direction,
    stop_loss: Decimal,
    take_profit: Decimal | None,
    limits: RiskLimits,
    execute: bool,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> OpenResult:
    if await client.position(symbol) is not None:
        raise TradeRefusedError(
            f"a {symbol} position is already open. Close it or adjust its TP/SL first."
        )

    plan = await build_plan(
        client,
        symbol=symbol,
        direction=direction,
        stop_loss=stop_loss,
        take_profit=take_profit,
        limits=limits,
    )
    if not execute:
        return OpenResult(plan=plan, executed=False)

    stop = StopLeg(plan.stop_loss)
    target = StopLeg(plan.take_profit) if plan.take_profit is not None else None

    await client.set_leverage(symbol, plan.leverage)
    await client.market_order(
        symbol=symbol,
        side=direction.entry_side,
        amount=plan.amount,
        slippage_percent=limits.slippage_percent,
        client_order_id=str(uuid.uuid4()),
        take_profit=target,
        stop_loss=stop,
    )

    position = await _await_position(client, symbol, sleep)
    if position is None:
        raise TradeRefusedError(
            "the order was accepted but no position appeared. It may have been rejected "
            "for slippage. Check the Pacifica app before trying again."
        )

    stop_confirmed = await has_stop_loss(client, position)
    if not stop_confirmed:
        stop_confirmed = await _reattach_or_flatten(client, position, stop, target)
    return OpenResult(plan=plan, executed=True, position=position, stop_confirmed=stop_confirmed)


async def _reattach_or_flatten(
    client: PacificaClient,
    position: PositionSnapshot,
    stop: StopLeg,
    target: StopLeg | None,
) -> bool:
    closing_side = "ask" if position.is_long else "bid"
    try:
        await client.set_position_tpsl(
            symbol=position.symbol, closing_side=closing_side, take_profit=target, stop_loss=stop
        )
    except PacificaError as exc:
        try:
            await client.market_order(
                symbol=position.symbol,
                side=closing_side,
                amount=position.amount,
                slippage_percent=Decimal(1),
                client_order_id=str(uuid.uuid4()),
                reduce_only=True,
            )
        except PacificaError as close_exc:
            raise TradeRefusedError(
                f"DANGER: the {position.symbol} position is open WITHOUT a stop loss. Setting "
                f"the stop failed ({exc}) and so did closing it ({close_exc}). Close it in "
                "the Pacifica app now."
            ) from close_exc
        raise TradeRefusedError(
            f"the stop loss could not be attached ({exc}); the position was closed at "
            "market so it is not left unprotected."
        ) from exc
    return await has_stop_loss(client, position)


async def close_position(
    client: PacificaClient, *, symbol: str, slippage_percent: Decimal, execute: bool
) -> PositionSnapshot:
    position = await client.position(symbol)
    if position is None:
        raise TradeRefusedError(f"no open {symbol} position")
    if execute:
        await client.market_order(
            symbol=symbol,
            side="ask" if position.is_long else "bid",
            amount=position.amount,
            slippage_percent=slippage_percent,
            client_order_id=str(uuid.uuid4()),
            reduce_only=True,
        )
        # Leftover TP/SL orders are reduce-only and cannot open a new position,
        # but they are removed so the book is clean.
        await client.cancel_all_orders(symbol)
    return position


async def update_tpsl(
    client: PacificaClient,
    *,
    symbol: str,
    stop_loss: Decimal | None,
    take_profit: Decimal | None,
    execute: bool,
) -> PositionSnapshot:
    position = await client.position(symbol)
    if position is None:
        raise TradeRefusedError(f"no open {symbol} position")
    mark = (await client.price(symbol)).mark
    if stop_loss is not None and (stop_loss >= mark if position.is_long else stop_loss <= mark):
        raise TradeRefusedError(
            f"a stop at {stop_loss} would trigger immediately at the current price {mark}"
        )
    if take_profit is not None and (
        take_profit <= mark if position.is_long else take_profit >= mark
    ):
        raise TradeRefusedError(
            f"a take profit at {take_profit} is on the wrong side of the current price {mark}"
        )
    if execute:
        # The API reference does not say whether omitting one leg removes it.
        # Resend the leg that is not changing, so moving the target can never
        # silently drop the stop.
        current_stop, current_target = await current_tpsl(client, position, mark)
        stop_loss = stop_loss if stop_loss is not None else current_stop
        take_profit = take_profit if take_profit is not None else current_target
        await client.set_position_tpsl(
            symbol=symbol,
            closing_side="ask" if position.is_long else "bid",
            take_profit=StopLeg(take_profit) if take_profit is not None else None,
            stop_loss=StopLeg(stop_loss) if stop_loss is not None else None,
        )
    return position


async def current_tpsl(
    client: PacificaClient, position: PositionSnapshot, mark: Decimal
) -> tuple[Decimal | None, Decimal | None]:
    """The trigger prices of the stop loss and take profit protecting `position`.

    Classified against the current price rather than the entry: a stop moved to
    break-even or beyond is still a stop.
    """
    closing_side = "ask" if position.is_long else "bid"
    stop: Decimal | None = None
    target: Decimal | None = None
    for order in await client.open_orders():
        if order.symbol != position.symbol or order.side != closing_side:
            continue
        if order.stop_price is None:
            continue
        is_stop = (order.stop_price < mark) == position.is_long
        if is_stop:
            stop = order.stop_price
        else:
            target = order.stop_price
    return stop, target
