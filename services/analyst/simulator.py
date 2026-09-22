"""Simulated execution, shared by the backtest and the paper account.

One implementation of the fill rules, so a paper account run forward in time
behaves exactly as the backtest that justified it — and every test of the
backtest also tests the paper account:

- Orders decided at a candle's close fill at the next candle's open.
- If a candle touches both the stop and the target, the stop filled first.
- A candle that opens beyond a level fills at its open, not at the level.
- Taker fee on entry and exit, slippage on every market fill, funding for
  every hour held.
- Position size comes from the trader's own planner.

State is plain data (`to_dict` / `from_dict`) so the paper account can save it
between candles and survive restarts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from services.analyst.candles import Candle
from services.analyst.strategy import StrategyParams
from services.trader.planner import PlanRejectedError, RiskLimits, plan_trade
from services.trader.venue import Direction, MarketRules

DEFAULT_TAKER_FEE: Final = 0.00045
"""Hyperliquid's base-tier taker fee per side."""
DEFAULT_SLIPPAGE: Final = 0.0005
"""0.05% per market fill, on top of the fee."""
DEFAULT_FUNDING_HOURLY: Final = 0.0000125
"""Hyperliquid's baseline hourly funding (about 11% a year, longs paying
shorts) — used only when no funding history is supplied."""

SIMULATED_MARKET: Final = MarketRules(
    symbol="SIMULATED",
    lot_size=Decimal("0.000001"),
    max_leverage=20,
    min_order_usd=Decimal(10),
    significant_figures=5,
    max_price_decimals=6,
)


@dataclass(frozen=True)
class BacktestConfig:
    interval: str = "4h"
    initial_equity: float = 10_000.0
    risk_percent: float = 1.0
    max_leverage: int = 3
    taker_fee: float = DEFAULT_TAKER_FEE
    slippage: float = DEFAULT_SLIPPAGE
    funding_hourly: float = DEFAULT_FUNDING_HOURLY
    params: StrategyParams = field(default_factory=StrategyParams)


@dataclass(frozen=True)
class Trade:
    direction: Direction
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    amount: float
    risk_usd: float
    pnl: float
    fees: float
    funding: float
    exit_reason: str

    @property
    def r_multiple(self) -> float:
        return self.pnl / self.risk_usd if self.risk_usd else 0.0


@dataclass
class Position:
    direction: Direction
    entry_time: datetime
    entry_price: float
    amount: float
    stop: float
    target: float | None
    risk_usd: float
    fees: float
    funding: float = 0.0

    def unrealised(self, price: float) -> float:
        sign = 1 if self.direction is Direction.LONG else -1
        return (price - self.entry_price) * self.amount * sign - self.fees - self.funding


@dataclass(frozen=True)
class Event:
    """Something the simulator did, for the paper account's journal."""

    kind: str
    """`entry`, `exit` or `skipped`."""
    time: datetime
    price: float | None
    detail: str


def _fill(price: float, *, buy: bool, slippage: float) -> float:
    return price * (1 + slippage) if buy else price * (1 - slippage)


class Simulator:
    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.cash = config.initial_equity
        self.position: Position | None = None
        self.pending_entry: tuple[Direction, float, float | None] | None = None
        self.pending_exit = False
        self.trades: list[Trade] = []
        self.skipped = 0
        self._limits = RiskLimits(
            risk_percent=Decimal(str(config.risk_percent)),
            max_leverage=config.max_leverage,
            taker_fee_rate=Decimal(str(config.taker_fee)),
            slippage_percent=Decimal(str(config.slippage * 100)),
        )

    # ------------------------------------------------------------------
    # One candle, in order
    # ------------------------------------------------------------------

    def open_candle(self, bar: Candle) -> list[Event]:
        """Fill what was decided at the previous close, then check stops and targets."""
        events: list[Event] = []
        if self.pending_exit and self.position is not None:
            events.append(self._close(bar.open_time, bar.open, "trend faded"))
        self.pending_exit = False
        if self.pending_entry is not None and self.position is None:
            events.append(self._enter(bar, *self.pending_entry))
        self.pending_entry = None

        position = self.position
        if position is not None:
            long = position.direction is Direction.LONG
            stop_hit = bar.low <= position.stop if long else bar.high >= position.stop
            target_hit = position.target is not None and (
                bar.high >= position.target if long else bar.low <= position.target
            )
            if stop_hit:
                gapped = bar.open <= position.stop if long else bar.open >= position.stop
                events.append(
                    self._close(bar.open_time, bar.open if gapped else position.stop, "stop")
                )
            elif target_hit and position.target is not None:
                gapped = bar.open >= position.target if long else bar.open <= position.target
                price = bar.open if gapped else position.target
                events.append(self._close(bar.open_time, price, "target"))
        return events

    def accrue_funding(self, rate: float, price: float) -> None:
        """Charge (or credit) funding at `rate` summed over the candle's hours."""
        if self.position is None:
            return
        sign = 1 if self.position.direction is Direction.LONG else -1
        self.position.funding += rate * sign * price * self.position.amount

    def schedule_entry(self, direction: Direction, stop: float, target: float | None) -> None:
        if self.position is None:
            self.pending_entry = (direction, stop, target)

    def schedule_exit(self) -> None:
        if self.position is not None:
            self.pending_exit = True

    def equity(self, price: float) -> float:
        if self.position is None:
            return self.cash
        return self.cash + self.position.unrealised(price)

    def close_at(self, time: datetime, price: float, reason: str) -> Event | None:
        if self.position is None:
            return None
        return self._close(time, price, reason)

    # ------------------------------------------------------------------

    def _enter(self, bar: Candle, direction: Direction, stop: float, target: float | None) -> Event:
        buy = direction is Direction.LONG
        entry = _fill(bar.open, buy=buy, slippage=self.config.slippage)
        if not (stop < entry if buy else stop > entry):
            self.skipped += 1
            return Event("skipped", bar.open_time, bar.open, "the market opened beyond the stop")
        try:
            plan = plan_trade(
                market=SIMULATED_MARKET,
                direction=direction,
                entry_price=Decimal(str(entry)),
                stop_loss=Decimal(str(stop)),
                take_profit=None,
                equity=Decimal(str(self.cash)),
                available=Decimal(str(self.cash)),
                limits=self._limits,
            )
        except PlanRejectedError as exc:
            self.skipped += 1
            return Event("skipped", bar.open_time, bar.open, str(exc))
        amount = float(plan.amount)
        self.position = Position(
            direction=direction,
            entry_time=bar.open_time,
            entry_price=entry,
            amount=amount,
            stop=stop,
            target=target,
            risk_usd=float(plan.risk_usd),
            fees=entry * amount * self.config.taker_fee,
        )
        return Event(
            "entry",
            bar.open_time,
            entry,
            f"{direction.value} {amount:.6g} at {entry:.6g}, stop {stop:.6g}"
            + (f", target {target:.6g}" if target is not None else ""),
        )

    def _close(self, time: datetime, raw_price: float, reason: str) -> Event:
        position = self.position
        assert position is not None  # noqa: S101 — callers check
        buy = position.direction is Direction.SHORT
        price = _fill(raw_price, buy=buy, slippage=self.config.slippage)
        fee = price * position.amount * self.config.taker_fee
        sign = 1 if position.direction is Direction.LONG else -1
        gross = (price - position.entry_price) * position.amount * sign
        pnl = gross - position.fees - fee - position.funding
        self.trades.append(
            Trade(
                direction=position.direction,
                entry_time=position.entry_time,
                exit_time=time,
                entry_price=position.entry_price,
                exit_price=price,
                amount=position.amount,
                risk_usd=position.risk_usd,
                pnl=pnl,
                fees=position.fees + fee,
                funding=position.funding,
                exit_reason=reason,
            )
        )
        # The entry fee and funding were accrued on the position, never taken
        # from cash, so the realised amount is the trade's full net P&L.
        self.cash += pnl
        self.position = None
        return Event("exit", time, price, f"{reason}: {pnl:+.2f} USD")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        def encode(value: Any) -> Any:
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, Direction):
                return value.value
            return value

        position = (
            {k: encode(v) for k, v in asdict(self.position).items()} if self.position else None
        )
        return {
            "cash": self.cash,
            "position": position,
            "pending_entry": (
                [self.pending_entry[0].value, self.pending_entry[1], self.pending_entry[2]]
                if self.pending_entry
                else None
            ),
            "pending_exit": self.pending_exit,
            "skipped": self.skipped,
            "trades": [{k: encode(v) for k, v in asdict(t).items()} for t in self.trades],
        }

    @classmethod
    def from_dict(cls, config: BacktestConfig, data: dict[str, Any]) -> Simulator:
        sim = cls(config)
        sim.cash = float(data["cash"])
        sim.pending_exit = bool(data["pending_exit"])
        sim.skipped = int(data["skipped"])
        if data["pending_entry"]:
            direction, stop, target = data["pending_entry"]
            sim.pending_entry = (Direction(direction), float(stop), target)
        if data["position"]:
            p = dict(data["position"])
            p["direction"] = Direction(p["direction"])
            p["entry_time"] = datetime.fromisoformat(p["entry_time"])
            sim.position = Position(**p)
        for stored in data["trades"]:
            t = dict(stored)
            t["direction"] = Direction(t["direction"])
            t["entry_time"] = datetime.fromisoformat(t["entry_time"])
            t["exit_time"] = datetime.fromisoformat(t["exit_time"])
            sim.trades.append(Trade(**t))
        return sim
