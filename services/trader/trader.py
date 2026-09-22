"""Open, adjust and close one position, with its stop loss always attached.

The rules here are the ones a disciplined trader follows by hand, and they hold
on every venue:

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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal

from libs.exchange.errors import VenueError
from services.trader.planner import RiskLimits, TradePlan, plan_trade
from services.trader.venue import Direction, PositionView, Venue

FILL_CONFIRM_ATTEMPTS = 10
FILL_CONFIRM_INTERVAL_SECONDS = 0.5
EMERGENCY_CLOSE_SLIPPAGE_PERCENT = Decimal(1)


class TradeRefusedError(RuntimeError):
    """The action was not taken. The message says why."""


@dataclass(frozen=True)
class OpenResult:
    plan: TradePlan
    executed: bool
    position: PositionView | None = None
    stop_confirmed: bool = False


async def position_for(venue: Venue, symbol: str) -> PositionView | None:
    return next((p for p in await venue.positions() if p.symbol == symbol), None)


async def build_plan(  # noqa: PLR0913 — keyword-only trade parameters
    venue: Venue,
    *,
    symbol: str,
    direction: Direction,
    stop_loss: Decimal,
    take_profit: Decimal | None,
    limits: RiskLimits,
) -> TradePlan:
    market = await venue.market(symbol)
    price = await venue.price(symbol)
    account = await venue.account()
    return plan_trade(
        market=market,
        direction=direction,
        entry_price=price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        equity=account.equity,
        available=account.available,
        limits=limits,
    )


async def current_tpsl(
    venue: Venue, position: PositionView, reference: Decimal
) -> tuple[Decimal | None, Decimal | None]:
    """Trigger prices of the stop loss and take profit protecting `position`.

    A trigger below `reference` protects a long from loss; above it, it takes a
    long's profit — and the reverse for a short. Classifying against the price
    rather than the entry keeps a stop moved to break-even or beyond a stop.
    """
    stop: Decimal | None = None
    target: Decimal | None = None
    for trigger in await venue.triggers(position.symbol):
        if trigger.closes_long != position.is_long:
            continue
        if (trigger.trigger_price < reference) == position.is_long:
            stop = trigger.trigger_price
        else:
            target = trigger.trigger_price
    return stop, target


async def has_stop_loss(venue: Venue, position: PositionView) -> bool:
    stop, _ = await current_tpsl(venue, position, position.entry_price)
    return stop is not None


async def _await_position(
    venue: Venue, symbol: str, sleep: Callable[[float], Awaitable[None]]
) -> PositionView | None:
    for _ in range(FILL_CONFIRM_ATTEMPTS):
        position = await position_for(venue, symbol)
        if position is not None:
            return position
        await sleep(FILL_CONFIRM_INTERVAL_SECONDS)
    return None


async def open_position(  # noqa: PLR0913 — keyword-only trade parameters
    venue: Venue,
    *,
    symbol: str,
    direction: Direction,
    stop_loss: Decimal,
    take_profit: Decimal | None,
    limits: RiskLimits,
    execute: bool,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> OpenResult:
    if await position_for(venue, symbol) is not None:
        raise TradeRefusedError(
            f"a {symbol} position is already open. Close it or adjust its TP/SL first."
        )

    plan = await build_plan(
        venue,
        symbol=symbol,
        direction=direction,
        stop_loss=stop_loss,
        take_profit=take_profit,
        limits=limits,
    )
    if not execute:
        return OpenResult(plan=plan, executed=False)

    market = await venue.market(symbol)
    await venue.set_leverage(symbol, plan.leverage)
    await venue.open_protected(
        market=market,
        direction=direction,
        amount=plan.amount,
        slippage_percent=limits.slippage_percent,
        stop_loss=plan.stop_loss,
        take_profit=plan.take_profit,
    )

    position = await _await_position(venue, symbol, sleep)
    if position is None:
        raise TradeRefusedError(
            "the order was accepted but no position appeared. It may not have filled within "
            "the slippage limit. Check the exchange before trying again."
        )

    stop_confirmed = await has_stop_loss(venue, position)
    if not stop_confirmed:
        stop_confirmed = await _reattach_or_flatten(venue, position, plan)
    return OpenResult(plan=plan, executed=True, position=position, stop_confirmed=stop_confirmed)


async def _reattach_or_flatten(venue: Venue, position: PositionView, plan: TradePlan) -> bool:
    try:
        await venue.set_protection(position, stop_loss=plan.stop_loss, take_profit=plan.take_profit)
    except VenueError as exc:
        try:
            await venue.close(position, slippage_percent=EMERGENCY_CLOSE_SLIPPAGE_PERCENT)
        except VenueError as close_exc:
            raise TradeRefusedError(
                f"DANGER: the {position.symbol} position is open WITHOUT a stop loss. Setting "
                f"the stop failed ({exc}) and so did closing it ({close_exc}). Close it on "
                "the exchange now."
            ) from close_exc
        raise TradeRefusedError(
            f"the stop loss could not be attached ({exc}); the position was closed at "
            "market so it is not left unprotected."
        ) from exc
    return await has_stop_loss(venue, position)


async def close_position(
    venue: Venue, *, symbol: str, slippage_percent: Decimal, execute: bool
) -> PositionView:
    position = await position_for(venue, symbol)
    if position is None:
        raise TradeRefusedError(f"no open {symbol} position")
    if execute:
        await venue.close(position, slippage_percent=slippage_percent)
    return position


async def update_tpsl(
    venue: Venue,
    *,
    symbol: str,
    stop_loss: Decimal | None,
    take_profit: Decimal | None,
    execute: bool,
) -> PositionView:
    position = await position_for(venue, symbol)
    if position is None:
        raise TradeRefusedError(f"no open {symbol} position")
    market = await venue.market(symbol)
    price = await venue.price(symbol)
    if stop_loss is not None:
        stop_loss = market.round_price(stop_loss)
        if stop_loss >= price if position.is_long else stop_loss <= price:
            raise TradeRefusedError(
                f"a stop at {stop_loss} would trigger immediately at the current price {price}"
            )
    if take_profit is not None:
        take_profit = market.round_price(take_profit)
        if take_profit <= price if position.is_long else take_profit >= price:
            raise TradeRefusedError(
                f"a take profit at {take_profit} is on the wrong side of the current price {price}"
            )
    if execute:
        # Resend the leg that is not changing, so moving the target can never
        # silently drop the stop.
        current_stop, current_target = await current_tpsl(venue, position, price)
        stop_loss = stop_loss if stop_loss is not None else current_stop
        take_profit = take_profit if take_profit is not None else current_target
        await venue.set_protection(position, stop_loss=stop_loss, take_profit=take_profit)
    return position
