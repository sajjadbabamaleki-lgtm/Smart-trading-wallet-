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
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Final

from services.analyst.candles import INTERVALS, Candle
from services.analyst.simulator import BacktestConfig, Simulator, Trade
from services.analyst.strategy import TrendIndicators
from services.trader.venue import Direction

__all__ = ["BacktestConfig", "BacktestResult", "Metrics", "Trade", "run_backtest"]

MIN_TRADES_FOR_CONFIDENCE: Final = 30


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


def _funding_for_bar(
    start: datetime, step: timedelta, rates: dict[datetime, float] | None, default: float
) -> float:
    hours = int(step.total_seconds() // 3600)
    if rates is None:
        return default * hours
    return sum(rates.get(start + timedelta(hours=h), 0.0) for h in range(hours))


def run_backtest(
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
    sim = Simulator(config)
    equity_curve: list[tuple[datetime, float, bool]] = []

    for i in range(start, len(candles)):
        bar = candles[i]
        sim.open_candle(bar)
        exposed = sim.position is not None
        sim.accrue_funding(
            _funding_for_bar(bar.open_time, step, funding_rates, config.funding_hourly), bar.close
        )
        if i < len(candles) - 1:
            if sim.position is not None:
                if indicators.should_exit(i, sim.position.direction):
                    sim.schedule_exit()
            else:
                signal = indicators.signal(i)
                if signal.direction is not None and signal.stop_loss is not None:
                    sim.schedule_entry(signal.direction, signal.stop_loss, signal.take_profit)
        equity_curve.append((bar.open_time, sim.equity(bar.close), exposed))

    last = candles[-1]
    if sim.close_at(last.open_time, last.close, "end of data") is not None:
        equity_curve[-1] = (last.open_time, sim.cash, True)
    trades = sim.trades
    skipped = sim.skipped

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
