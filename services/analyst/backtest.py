"""Event-driven backtest of the trend strategy, with conservative fills.

Deliberately pessimistic where a backtest usually flatters itself:

- **No look-ahead.** A signal uses candles up to and including bar i; the
  entry fills at the *open* of bar i+1.
- **Stop before target.** If one candle touches both, the stop is assumed to
  have filled first — the candle does not say which came first.
- **Gaps fill at the gap.** A candle that opens beyond the stop fills at its
  open, not at the stop.
- **Every cost.** Taker fee on entry and exit, slippage on every market fill,
  and funding for every hour the position is held — the venue's actual
  history when available, otherwise an assumed constant rate.
- **Same sizing as live.** Position size comes from the trader's own
  planner: risk per trade, leverage cap, minimum order.

The report also splits the period in two halves. The parameters were not
fitted on either, so a strategy with real edge should not collapse in one of
them; if it does, the full-period number is luck.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Final

from services.analyst.candles import INTERVALS, Candle
from services.analyst.strategy import StrategyParams, TrendIndicators
from services.trader.planner import PlanRejectedError, RiskLimits, plan_trade
from services.trader.venue import Direction, MarketRules

DEFAULT_TAKER_FEE: Final = 0.00045
"""Hyperliquid's base-tier taker fee per side."""
DEFAULT_SLIPPAGE: Final = 0.0005
"""0.05% per market fill, on top of the fee."""
DEFAULT_FUNDING_HOURLY: Final = 0.0000125
"""Hyperliquid's baseline hourly funding (about 11% a year, longs paying
shorts) — used only when no funding history is supplied."""
MIN_TRADES_FOR_CONFIDENCE: Final = 30

BACKTEST_MARKET: Final = MarketRules(
    symbol="BACKTEST",
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


@dataclass(frozen=True)
class Metrics:
    start: datetime
    end: datetime
    trades: int
    win_rate: float
    average_r: float
    profit_factor: float
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe: float
    probabilistic_sharpe: float
    """Probability that the true Sharpe ratio is above zero, given the sample's
    length, skew and fat tails (Bailey & López de Prado, 2012)."""
    exposure: float
    buy_and_hold_return: float
    buy_and_hold_max_drawdown: float
    fees: float
    funding: float


@dataclass(frozen=True)
class TradeStats:
    trades: int
    win_rate: float
    average_r: float
    profit_factor: float
    net_pnl: float


@dataclass(frozen=True)
class BacktestResult:
    full: Metrics
    first_half: Metrics
    second_half: Metrics
    longs: TradeStats
    shorts: TradeStats
    trades: list[Trade]
    skipped_signals: int
    warnings: list[str]


@dataclass
class _Position:
    direction: Direction
    entry_time: datetime
    entry_price: float
    amount: float
    stop: float
    target: float | None
    risk_usd: float
    fees: float
    funding: float = 0.0


def _fill(price: float, *, buy: bool, slippage: float) -> float:
    return price * (1 + slippage) if buy else price * (1 - slippage)


def _funding_for_bar(
    start: datetime, step: timedelta, rates: dict[datetime, float] | None, default: float
) -> float:
    hours = int(step.total_seconds() // 3600)
    if rates is None:
        return default * hours
    total = 0.0
    for h in range(hours):
        total += rates.get(start + timedelta(hours=h), 0.0)
    return total


def run_backtest(  # noqa: PLR0912, PLR0915 — one bar loop; its steps read in order
    candles: Sequence[Candle],
    config: BacktestConfig,
    *,
    funding_rates: dict[datetime, float] | None = None,
) -> BacktestResult:
    params = config.params
    step = INTERVALS[config.interval]
    indicators = TrendIndicators(candles, config.interval, params)
    start = indicators.warmup - 1
    if start >= len(candles) - 2:
        raise ValueError(
            f"not enough candles: {len(candles)} given, the strategy needs "
            f"{indicators.warmup} for warm-up plus a test period"
        )
    limits = RiskLimits(
        risk_percent=Decimal(str(config.risk_percent)),
        max_leverage=config.max_leverage,
        taker_fee_rate=Decimal(str(config.taker_fee)),
        slippage_percent=Decimal(str(config.slippage * 100)),
    )

    cash = config.initial_equity
    position: _Position | None = None
    pending_entry: tuple[Direction, float, float | None] | None = None
    pending_exit = False
    trades: list[Trade] = []
    equity_curve: list[tuple[datetime, float, bool]] = []
    skipped = 0

    def close(pos: _Position, time: datetime, raw_price: float, reason: str) -> float:
        buy = pos.direction is Direction.SHORT
        price = _fill(raw_price, buy=buy, slippage=config.slippage)
        fee = price * pos.amount * config.taker_fee
        sign = 1 if pos.direction is Direction.LONG else -1
        gross = (price - pos.entry_price) * pos.amount * sign
        pnl = gross - pos.fees - fee - pos.funding
        trades.append(
            Trade(
                direction=pos.direction,
                entry_time=pos.entry_time,
                exit_time=time,
                entry_price=pos.entry_price,
                exit_price=price,
                amount=pos.amount,
                risk_usd=pos.risk_usd,
                pnl=pnl,
                fees=pos.fees + fee,
                funding=pos.funding,
                exit_reason=reason,
            )
        )
        # Entry fee and funding were never taken from cash, only accrued on the
        # position, so the realised amount is the trade's full net P&L.
        return pnl

    for i in range(start, len(candles)):
        bar = candles[i]

        # 1. Orders decided at the previous close fill at this open.
        if pending_exit and position is not None:
            cash += close(position, bar.open_time, bar.open, "trend faded")
            position = None
        pending_exit = False
        if pending_entry is not None and position is None:
            direction, stop, target = pending_entry
            buy = direction is Direction.LONG
            entry = _fill(bar.open, buy=buy, slippage=config.slippage)
            stop_valid = stop < entry if buy else stop > entry
            if stop_valid:
                try:
                    plan = plan_trade(
                        market=BACKTEST_MARKET,
                        direction=direction,
                        entry_price=Decimal(str(entry)),
                        stop_loss=Decimal(str(stop)),
                        take_profit=None,
                        equity=Decimal(str(cash)),
                        available=Decimal(str(cash)),
                        limits=limits,
                    )
                except PlanRejectedError:
                    skipped += 1
                else:
                    amount = float(plan.amount)
                    fee = entry * amount * config.taker_fee
                    position = _Position(
                        direction=direction,
                        entry_time=bar.open_time,
                        entry_price=entry,
                        amount=amount,
                        stop=stop,
                        target=target,
                        risk_usd=float(plan.risk_usd),
                        fees=fee,
                    )
            else:
                skipped += 1  # the market opened beyond the stop
        pending_entry = None

        # 2. Stops and targets during this candle; stop first when both touch.
        if position is not None:
            long = position.direction is Direction.LONG
            stop_hit = bar.low <= position.stop if long else bar.high >= position.stop
            target_hit = position.target is not None and (
                bar.high >= position.target if long else bar.low <= position.target
            )
            if stop_hit:
                gapped = bar.open <= position.stop if long else bar.open >= position.stop
                cash += close(
                    position, bar.open_time, bar.open if gapped else position.stop, "stop"
                )
                position = None
            elif target_hit and position.target is not None:
                gapped = bar.open >= position.target if long else bar.open <= position.target
                exit_price = bar.open if gapped else position.target
                cash += close(position, bar.open_time, exit_price, "target")
                position = None

        # 3. Funding for the hours held in this candle.
        exposed = position is not None
        if position is not None:
            rate = _funding_for_bar(bar.open_time, step, funding_rates, config.funding_hourly)
            sign = 1 if position.direction is Direction.LONG else -1
            position.funding += rate * sign * bar.close * position.amount

        # 4. Decide at this close what happens at the next open.
        if i < len(candles) - 1:
            if position is not None:
                pending_exit = indicators.should_exit(i, position.direction)
            else:
                signal = indicators.signal(i)
                if signal.direction is not None and signal.stop_loss is not None:
                    pending_entry = (signal.direction, signal.stop_loss, signal.take_profit)

        mark = cash
        if position is not None:
            sign = 1 if position.direction is Direction.LONG else -1
            mark += (bar.close - position.entry_price) * position.amount * sign
            mark -= position.fees + position.funding
        equity_curve.append((bar.open_time, mark, exposed))

    if position is not None:
        last = candles[-1]
        cash += close(position, last.open_time, last.close, "end of data")
        equity_curve[-1] = (last.open_time, cash, True)

    closes = [(c.open_time, c.close) for c in candles[start:]]
    midpoint = equity_curve[len(equity_curve) // 2][0]
    warnings = []
    if len(trades) < MIN_TRADES_FOR_CONFIDENCE:
        warnings.append(
            f"only {len(trades)} trades: too few to tell skill from luck "
            f"(aim for at least {MIN_TRADES_FOR_CONFIDENCE})"
        )
    if funding_rates is None:
        warnings.append(
            f"funding assumed at {config.funding_hourly * 24 * 365:.0%} a year; no history given"
        )

    first = [p for p in equity_curve if p[0] < midpoint]
    second = [p for p in equity_curve if p[0] >= midpoint]
    return BacktestResult(
        full=_metrics(equity_curve, trades, closes, step),
        first_half=_metrics(first, [t for t in trades if t.entry_time < midpoint], closes, step),
        second_half=_metrics(second, [t for t in trades if t.entry_time >= midpoint], closes, step),
        longs=_trade_stats([t for t in trades if t.direction is Direction.LONG]),
        shorts=_trade_stats([t for t in trades if t.direction is Direction.SHORT]),
        trades=trades,
        skipped_signals=skipped,
        warnings=warnings,
    )


def probabilistic_sharpe(returns: Sequence[float]) -> float:
    """P(true Sharpe > 0) — Bailey & López de Prado (2012), 'The Sharpe Ratio
    Efficient Frontier'. Accounts for sample length, skewness and kurtosis,
    which matter for crypto's fat-tailed returns."""
    n = len(returns)
    if n < 3:  # noqa: PLR2004
        return 0.5
    mean = statistics.fmean(returns)
    sd = statistics.pstdev(returns)
    if sd == 0:
        return 0.5
    sr = mean / sd
    skew = sum(((r - mean) / sd) ** 3 for r in returns) / n
    kurt = sum(((r - mean) / sd) ** 4 for r in returns) / n
    denominator = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    if denominator <= 0:
        return 0.5
    z = sr * math.sqrt(n - 1) / math.sqrt(denominator)
    return statistics.NormalDist().cdf(z)


def _max_drawdown(values: Sequence[float]) -> float:
    peak = -math.inf
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1)
    return worst


def _trade_stats(trades: list[Trade]) -> TradeStats:
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [-t.pnl for t in trades if t.pnl <= 0]
    return TradeStats(
        trades=len(trades),
        win_rate=len(wins) / len(trades) if trades else 0.0,
        average_r=statistics.fmean(t.r_multiple for t in trades) if trades else 0.0,
        profit_factor=sum(wins) / sum(losses) if losses and sum(losses) > 0 else math.inf,
        net_pnl=sum(t.pnl for t in trades),
    )


def _metrics(
    curve: list[tuple[datetime, float, bool]],
    trades: list[Trade],
    closes: list[tuple[datetime, float]],
    step: timedelta,
) -> Metrics:
    if len(curve) < 2:  # noqa: PLR2004
        raise ValueError("period too short to measure")
    values = [v for _, v, _ in curve]
    returns = [b / a - 1 for a, b in pairwise(values) if a > 0]
    bars_per_year = timedelta(days=365) / step
    years = (curve[-1][0] - curve[0][0]) / timedelta(days=365)
    total_return = values[-1] / values[0] - 1
    sd = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    sharpe = statistics.fmean(returns) / sd * math.sqrt(bars_per_year) if sd else 0.0
    stats = _trade_stats(trades)
    period = [price for time, price in closes if curve[0][0] <= time <= curve[-1][0]]
    return Metrics(
        start=curve[0][0],
        end=curve[-1][0],
        trades=stats.trades,
        win_rate=stats.win_rate,
        average_r=stats.average_r,
        profit_factor=stats.profit_factor,
        total_return=total_return,
        cagr=(1 + total_return) ** (1 / years) - 1 if years > 0 and total_return > -1 else -1.0,
        max_drawdown=_max_drawdown(values),
        sharpe=sharpe,
        probabilistic_sharpe=probabilistic_sharpe(returns),
        exposure=sum(1 for _, _, exposed in curve if exposed) / len(curve),
        buy_and_hold_return=period[-1] / period[0] - 1 if len(period) > 1 else 0.0,
        buy_and_hold_max_drawdown=_max_drawdown(period),
        fees=sum(t.fees for t in trades),
        funding=sum(t.funding for t in trades),
    )
