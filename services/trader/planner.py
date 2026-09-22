"""Turn a trade idea into an exact, risk-bounded order.

A human trader decides direction, stop loss and take profit; position size
should follow from those, never the other way round. The planner sizes the
position so that being stopped out loses a fixed fraction of equity — fees
included — and refuses the trade when the numbers do not work, instead of
quietly bending them.

Pure and synchronous: no network, no clock. Everything it needs is passed in,
so every rule below is covered by a unit test.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Final

from services.trader.venue import Direction, MarketRules

HARD_MAX_RISK_PERCENT: Final = Decimal(5)
"""No configuration may risk more than this per trade. Five losses in a row —
common for any strategy — would already cost about 23% of the account."""

HUNDRED: Final = Decimal(100)


class PlanRejectedError(ValueError):
    """The trade cannot be placed within the rules. The message says why."""


@dataclass(frozen=True)
class RiskLimits:
    risk_percent: Decimal
    max_leverage: int
    taker_fee_rate: Decimal
    """Per side, as a fraction: 0.0005 is 0.05%."""
    slippage_percent: Decimal


@dataclass(frozen=True)
class TradePlan:
    symbol: str
    direction: Direction
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal | None
    amount: Decimal
    notional: Decimal
    leverage: int
    risk_usd: Decimal
    loss_at_stop: Decimal
    """Estimated, with entry and exit fees and slippage at the stop."""
    profit_at_target: Decimal | None
    """Estimated, net of entry and exit fees."""
    capped_by_leverage: bool

    @property
    def reward_to_risk(self) -> Decimal | None:
        if self.profit_at_target is None or self.loss_at_stop == 0:
            return None
        return self.profit_at_target / self.loss_at_stop


def plan_trade(  # noqa: PLR0912, PLR0913 — flat rule checks; each argument is one input
    *,
    market: MarketRules,
    direction: Direction,
    entry_price: Decimal,
    stop_loss: Decimal,
    take_profit: Decimal | None,
    equity: Decimal,
    available: Decimal,
    limits: RiskLimits,
) -> TradePlan:
    if not Decimal(0) < limits.risk_percent <= HARD_MAX_RISK_PERCENT:
        raise PlanRejectedError(
            f"risk per trade must be above 0% and at most {HARD_MAX_RISK_PERCENT}%, "
            f"got {limits.risk_percent}%"
        )
    if entry_price <= 0 or stop_loss <= 0:
        raise PlanRejectedError("prices must be positive")
    if equity <= 0 or available <= 0:
        raise PlanRejectedError("the account has no available margin; deposit funds first")

    stop_loss = market.round_price(stop_loss)
    if take_profit is not None:
        take_profit = market.round_price(take_profit)

    if direction is Direction.LONG:
        if stop_loss >= entry_price:
            raise PlanRejectedError(f"a long's stop loss must be below the price ({entry_price})")
        if take_profit is not None and take_profit <= entry_price:
            raise PlanRejectedError(f"a long's take profit must be above the price ({entry_price})")
    else:
        if stop_loss <= entry_price:
            raise PlanRejectedError(f"a short's stop loss must be above the price ({entry_price})")
        if take_profit is not None and take_profit >= entry_price:
            raise PlanRejectedError(
                f"a short's take profit must be below the price ({entry_price})"
            )

    # Loss per unit if stopped out: the distance, plus a taker fee on entry and
    # exit, plus slippage on the exit — a stop fills as a market order.
    stop_distance = abs(entry_price - stop_loss)
    fee_per_unit = (entry_price + stop_loss) * limits.taker_fee_rate
    slippage_per_unit = stop_loss * limits.slippage_percent / HUNDRED
    loss_per_unit = stop_distance + fee_per_unit + slippage_per_unit

    risk_usd = equity * limits.risk_percent / HUNDRED
    amount = market.round_size(risk_usd / loss_per_unit)

    leverage_cap = min(limits.max_leverage, market.max_leverage)
    max_notional = available * leverage_cap
    capped = False
    if amount * entry_price > max_notional:
        amount = market.round_size(max_notional / entry_price)
        capped = True

    notional = amount * entry_price
    if amount <= 0 or notional < market.min_order_usd:
        reason = (
            f"{leverage_cap}x leverage on ${available:.2f} available margin cannot reach it: "
            "add funds."
            if capped
            else f"the stop is too far for {limits.risk_percent}% risk on this account: "
            "move the stop closer, or add funds."
        )
        raise PlanRejectedError(
            f"position would be ${notional:.2f}, below the venue's ${market.min_order_usd} "
            f"minimum for {market.symbol}; {reason}"
        )
    if market.max_order_usd is not None and notional > market.max_order_usd:
        raise PlanRejectedError(f"position ${notional:.2f} exceeds the venue maximum")

    leverage = max(1, int((notional / available).to_integral_value(rounding=ROUND_CEILING)))

    profit = None
    if take_profit is not None:
        gross = abs(take_profit - entry_price) * amount
        profit = gross - (entry_price + take_profit) * limits.taker_fee_rate * amount

    return TradePlan(
        symbol=market.symbol,
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        amount=amount,
        notional=notional,
        leverage=leverage,
        risk_usd=risk_usd,
        loss_at_stop=loss_per_unit * amount,
        profit_at_target=profit,
        capped_by_leverage=capped,
    )
