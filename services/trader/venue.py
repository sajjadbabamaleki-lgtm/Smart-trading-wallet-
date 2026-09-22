"""What the trader needs from an exchange.

The trading rules — size from the stop, stop always attached, one position per
market — live in `trader.py` and do not know which exchange they run on. Each
exchange implements `Venue` in `services/trader/venues/`. Adding an exchange
means writing one adapter; the rules and their tests stay as they are.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Protocol


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"


def round_to_step(value: Decimal, step: Decimal, rounding: str = ROUND_HALF_UP) -> Decimal:
    return (value / step).quantize(Decimal(1), rounding=rounding) * step


@dataclass(frozen=True)
class MarketRules:
    """Order constraints of one market.

    Prices follow one of two conventions: a fixed `tick_size` (Pacifica), or at
    most `significant_figures` significant figures and `max_price_decimals`
    decimals (Hyperliquid). Exactly one of the two must be set.
    """

    symbol: str
    lot_size: Decimal
    max_leverage: int
    min_order_usd: Decimal
    max_order_usd: Decimal | None = None
    tick_size: Decimal | None = None
    significant_figures: int | None = None
    max_price_decimals: int | None = None

    def __post_init__(self) -> None:
        if (self.tick_size is None) == (self.significant_figures is None):
            raise ValueError("set exactly one of tick_size or significant_figures")

    def round_price(self, price: Decimal) -> Decimal:
        if self.tick_size is not None:
            return round_to_step(price, self.tick_size)
        if price == price.to_integral_value():
            # Integer prices are always valid, whatever their digit count.
            return price.quantize(Decimal(1))
        assert self.significant_figures is not None  # noqa: S101 — guaranteed by __post_init__
        exponent = price.adjusted() - self.significant_figures + 1
        rounded = price.quantize(Decimal(1).scaleb(exponent), rounding=ROUND_HALF_UP)
        if self.max_price_decimals is not None:
            rounded = rounded.quantize(
                Decimal(1).scaleb(-self.max_price_decimals), rounding=ROUND_HALF_UP
            )
        return rounded.normalize()

    def round_size(self, amount: Decimal) -> Decimal:
        return round_to_step(amount, self.lot_size, ROUND_DOWN)


@dataclass(frozen=True)
class AccountView:
    equity: Decimal
    available: Decimal
    """Margin free for new positions."""


@dataclass(frozen=True)
class PositionView:
    symbol: str
    is_long: bool
    amount: Decimal
    """Absolute size, in the base asset."""
    entry_price: Decimal


@dataclass(frozen=True)
class TriggerView:
    """A resting reduce-only trigger (stop loss or take profit) on a position."""

    symbol: str
    trigger_price: Decimal
    closes_long: bool
    """True if it sells, i.e. it protects a long."""


class Venue(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def is_mainnet(self) -> bool: ...

    @property
    def account_address(self) -> str: ...

    async def market(self, symbol: str) -> MarketRules: ...

    async def price(self, symbol: str) -> Decimal:
        """Current reference price used for planning."""
        ...

    async def account(self) -> AccountView: ...

    async def positions(self) -> tuple[PositionView, ...]: ...

    async def triggers(self, symbol: str) -> tuple[TriggerView, ...]: ...

    async def set_leverage(self, symbol: str, leverage: int) -> None: ...

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
        """Enter at market with the stop loss (and target) in the same request."""
        ...

    async def set_protection(
        self,
        position: PositionView,
        *,
        stop_loss: Decimal | None,
        take_profit: Decimal | None,
    ) -> None:
        """Replace the position's triggers with exactly the legs given."""
        ...

    async def close(self, position: PositionView, *, slippage_percent: Decimal) -> None:
        """Close at market and remove the position's remaining triggers."""
        ...

    async def aclose(self) -> None: ...
