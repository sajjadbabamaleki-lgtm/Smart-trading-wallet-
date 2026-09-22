"""Run one strategy over one window of the dataset.

Each asset gets an equal share of capital and its own simulator — the one
the backtest and paper account use — so fills, costs, sizing and stops are
identical for every strategy. A strategy may read history before the window
(for its indicators) but trades only inside it; positions still open when
the window ends are closed at the last close.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from itertools import pairwise

from services.analyst.backtest import Metrics, _funding_for_bar, _metrics
from services.analyst.simulator import BacktestConfig, Simulator, Trade
from services.lab.data import INTERVAL, Dataset
from services.lab.strategies import Enter, Exit, Held, MoveStop, Strategy

STEP = timedelta(hours=4)


@dataclass(frozen=True)
class LabResult:
    strategy: str
    full: Metrics
    first_half: Metrics
    second_half: Metrics
    trades: list[Trade]
    trades_by_asset: dict[str, int]
    sharpe_per_bar: float
    observations: int
    skew: float
    kurtosis: float


def run(
    strategy: Strategy,
    dataset: Dataset,
    *,
    start: datetime,
    end: datetime,
    config: BacktestConfig | None = None,
) -> LabResult:
    config = config or BacktestConfig(interval=INTERVAL)
    symbols = sorted(dataset.candles)
    share = replace(config, initial_equity=config.initial_equity / len(symbols))
    sims = {s: Simulator(share) for s in symbols}
    index = {s: {c.open_time: i for i, c in enumerate(dataset.candles[s])} for s in symbols}
    strategy.funding = dataset.funding
    strategy.prepare(dataset.candles)

    times = sorted({t for s in symbols for t in index[s] if start <= t < end})
    if len(times) < 2:  # noqa: PLR2004
        raise ValueError("the window holds no candles")
    last_equity = dict.fromkeys(symbols, share.initial_equity)
    last_close: dict[str, tuple[datetime, float]] = {}
    first_close: dict[str, float] = {}
    curve: list[tuple[datetime, float, bool]] = []
    basket: list[tuple[datetime, float]] = []

    for time in times:
        closing: dict[str, int] = {}
        for symbol in symbols:
            i = index[symbol].get(time)
            if i is None:
                continue
            bar = dataset.candles[symbol][i]
            sim = sims[symbol]
            sim.open_candle(bar)
            rate = _funding_for_bar(bar.open_time, STEP, dataset.funding.get(symbol), 0.0)
            sim.accrue_funding(rate, bar.close)
            closing[symbol] = i
            last_close[symbol] = (time, bar.close)
            first_close.setdefault(symbol, bar.close)

        if time + STEP < end:
            held = {s: _held(sims[s], index[s]) for s in closing}
            for symbol, action in strategy.decide(time, closing, held):
                sim = sims[symbol]
                if isinstance(action, Exit):
                    sim.schedule_exit()
                elif isinstance(action, Enter):
                    sim.schedule_entry(action.direction, action.stop, action.target)
                elif isinstance(action, MoveStop):
                    sim.move_stop(action.stop)

        for symbol in closing:
            last_equity[symbol] = sims[symbol].equity(last_close[symbol][1])
        exposed = any(sims[s].position is not None for s in symbols)
        curve.append((time, sum(last_equity.values()), exposed))
        basket.append(
            (time, sum(last_close[s][1] / first_close[s] for s in last_close) / len(last_close))
        )

    for symbol, sim in sims.items():
        if symbol in last_close and sim.close_at(*last_close[symbol], "end of window"):
            last_equity[symbol] = sim.cash
    curve[-1] = (curve[-1][0], sum(last_equity.values()), True)

    trades = sorted((t for sim in sims.values() for t in sim.trades), key=lambda t: t.entry_time)
    midpoint = curve[len(curve) // 2][0]
    values = [v for _, v, _ in curve]
    returns = [b / a - 1 for a, b in pairwise(values) if a > 0]
    mean = statistics.fmean(returns)
    sd = statistics.pstdev(returns)
    return LabResult(
        strategy=strategy.name,
        full=_metrics(curve, trades, basket, STEP),
        first_half=_metrics(
            [p for p in curve if p[0] < midpoint],
            [t for t in trades if t.entry_time < midpoint],
            basket,
            STEP,
        ),
        second_half=_metrics(
            [p for p in curve if p[0] >= midpoint],
            [t for t in trades if t.entry_time >= midpoint],
            basket,
            STEP,
        ),
        trades=trades,
        trades_by_asset={s: len(sims[s].trades) for s in symbols},
        sharpe_per_bar=mean / sd if sd else 0.0,
        observations=len(returns),
        skew=sum(((r - mean) / sd) ** 3 for r in returns) / len(returns) if sd else 0.0,
        kurtosis=sum(((r - mean) / sd) ** 4 for r in returns) / len(returns) if sd else 3.0,
    )


def _held(sim: Simulator, index: dict[datetime, int]) -> Held | None:
    position = sim.position
    if position is None:
        return None
    return Held(position.direction, index[position.entry_time], position.stop)


def annualised(sharpe_per_bar: float) -> float:
    return sharpe_per_bar * math.sqrt(timedelta(days=365) / STEP)
