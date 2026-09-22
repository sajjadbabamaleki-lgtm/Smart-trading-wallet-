"""Funding carry: long spot, short the perpetual, collect funding.

The two legs cancel each other's price exposure, so the position earns only
what the perpetual's funding pays the short side — positive most of the time,
because leveraged demand is usually long. It is a payment the market makes
for structural reasons, not a forecast, which is why it is tested separately
from the directional strategy.

What the simulation charges, so the result is not flattering:

- **Capital for both legs.** The spot leg needs its full value and the short
  needs margin (`1 / perp_leverage` of it), so with 2x only two thirds of the
  capital is working: notional = equity x L / (L + 1).
- **Taker fees and slippage on both legs** at every entry, exit and rebalance.
- **Rebalancing.** As price moves, the short leg's margin drifts toward
  liquidation. When price has moved `rebalance_move` since the last rebalance,
  that fraction of the notional is moved between legs, paying fees again.
- **Negative funding** is paid, not skipped, whenever the position is open.

Two rule sets, both fixed before any result was seen:

- **Always on** — hold throughout.
- **Conditional** — enter when the average funding of the *previous* seven
  days annualises above 10%, exit when it falls to zero or below. Funding is
  persistent, so recent funding is informative about the next hours; the
  decision at hour t uses only rates paid before t.

Not modelled: basis between spot and perp prices at entry and exit (covered
roughly by the slippage charge), and intra-candle price jumps larger than the
rebalance threshold — a live bot rebalancing continuously would react sooner
than a 4h check; one that does not could be liquidated in a violent move.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Final

from services.analyst.backtest import probabilistic_sharpe
from services.analyst.candles import Candle

HOURS_PER_YEAR: Final = 24 * 365


@dataclass(frozen=True)
class CarryConfig:
    initial_equity: float = 10_000.0
    perp_leverage: float = 2.0
    perp_fee: float = 0.00045
    """Hyperliquid perp base-tier taker fee."""
    spot_fee: float = 0.0007
    """Assumed spot taker fee; check the venue the spot leg actually uses."""
    slippage: float = 0.0005
    """Per leg, per fill."""
    lookback_hours: int = 7 * 24
    entry_apr: float = 0.10
    exit_apr: float = 0.0
    rebalance_move: float = 0.25
    always_on: bool = False

    @property
    def round_trip_cost(self) -> float:
        """Cost of opening or closing both legs, as a fraction of notional."""
        return self.spot_fee + self.perp_fee + 2 * self.slippage

    @property
    def working_fraction(self) -> float:
        return self.perp_leverage / (self.perp_leverage + 1)


@dataclass(frozen=True)
class CarryResult:
    start: datetime
    end: datetime
    total_return: float
    apr: float
    max_drawdown: float
    worst_30_days: float
    sharpe: float
    probabilistic_sharpe: float
    time_invested: float
    funding_earned: float
    costs: float
    entries: int
    rebalances: int
    first_half_return: float
    second_half_return: float
    equity_curve: list[tuple[datetime, float]]


def _price_by_hour(candles: Sequence[Candle]) -> dict[datetime, float]:
    """The close of the candle each hour falls in — the price funding is paid on."""
    if len(candles) < 2:  # noqa: PLR2004
        return {}
    step = candles[1].open_time - candles[0].open_time
    hours_per_candle = int(step / timedelta(hours=1))
    return {
        candle.open_time + timedelta(hours=h): candle.close
        for candle in candles
        for h in range(hours_per_candle)
    }


def run_carry(
    candles: Sequence[Candle], funding: dict[datetime, float], config: CarryConfig
) -> CarryResult:
    prices = _price_by_hour(candles)
    hours = sorted(h for h in funding if h in prices)
    if len(hours) <= config.lookback_hours + 24:
        raise ValueError("not enough funding history for the lookback plus a test period")

    equity = config.initial_equity
    quantity = 0.0
    anchor = 0.0
    earned = costs = 0.0
    entries = rebalances = invested_hours = 0
    curve: list[tuple[datetime, float]] = []
    window = [funding[h] for h in hours[: config.lookback_hours]]

    for hour in hours[config.lookback_hours :]:
        price = prices[hour]
        trailing_apr = statistics.fmean(window) * HOURS_PER_YEAR

        # Decide with rates paid before this hour only.
        if quantity == 0 and (config.always_on or trailing_apr >= config.entry_apr):
            notional = equity * config.working_fraction
            cost = notional * config.round_trip_cost
            equity -= cost
            costs += cost
            quantity = notional / price
            anchor = price
            entries += 1
        elif quantity > 0 and not config.always_on and trailing_apr <= config.exit_apr:
            cost = quantity * price * config.round_trip_cost
            equity -= cost
            costs += cost
            quantity = 0.0

        if quantity > 0:
            move = abs(price / anchor - 1)
            if move >= config.rebalance_move:
                cost = quantity * price * move * config.round_trip_cost
                equity -= cost
                costs += cost
                anchor = price
                rebalances += 1
            # The short receives a positive rate and pays a negative one.
            payment = quantity * price * funding[hour]
            equity += payment
            earned += payment
            invested_hours += 1

        curve.append((hour, equity))
        window.append(funding[hour])
        window.pop(0)

    if quantity > 0:
        cost = quantity * prices[hours[-1]] * config.round_trip_cost
        equity -= cost
        costs += cost
        curve[-1] = (curve[-1][0], equity)

    return _summarise(
        curve,
        config,
        earned=earned,
        costs=costs,
        entries=entries,
        rebalances=rebalances,
        invested_hours=invested_hours,
    )


def _summarise(  # noqa: PLR0913 — accumulated totals from one run
    curve: list[tuple[datetime, float]],
    config: CarryConfig,
    *,
    earned: float,
    costs: float,
    entries: int,
    rebalances: int,
    invested_hours: int,
) -> CarryResult:
    values = [v for _, v in curve]
    daily = values[::24] + ([values[-1]] if (len(values) - 1) % 24 else [])
    returns = [b / a - 1 for a, b in pairwise(daily) if a > 0]
    sd = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    years = (curve[-1][0] - curve[0][0]) / timedelta(days=365)
    total = values[-1] / config.initial_equity - 1
    peak = -math.inf
    drawdown = 0.0
    for v in values:
        peak = max(peak, v)
        drawdown = min(drawdown, v / peak - 1)
    month = 30 * 24
    worst = min(
        (values[i + month] / values[i] - 1 for i in range(0, len(values) - month, 24)),
        default=total,
    )
    mid = len(values) // 2
    return CarryResult(
        start=curve[0][0],
        end=curve[-1][0],
        total_return=total,
        apr=(1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0,
        max_drawdown=drawdown,
        worst_30_days=worst,
        sharpe=statistics.fmean(returns) / sd * math.sqrt(365) if sd else 0.0,
        probabilistic_sharpe=probabilistic_sharpe(returns),
        time_invested=invested_hours / len(curve),
        funding_earned=earned,
        costs=costs,
        entries=entries,
        rebalances=rebalances,
        first_half_return=values[mid] / config.initial_equity - 1,
        second_half_return=values[-1] / values[mid] - 1,
        equity_curve=curve,
    )


@dataclass(frozen=True)
class CarryPortfolio:
    per_asset: dict[str, CarryResult]
    total: CarryResult


def run_carry_portfolio(
    data: dict[str, tuple[Sequence[Candle], dict[datetime, float]]], config: CarryConfig
) -> CarryPortfolio:
    """Equal capital per asset; each runs the same rules independently."""
    if not data:
        raise ValueError("no assets given")
    share = replace(config, initial_equity=config.initial_equity / len(data))
    results = {s: run_carry(c, f, share) for s, (c, f) in data.items()}

    hours = sorted({h for r in results.values() for h, _ in r.equity_curve})
    by_hour = {s: dict(r.equity_curve) for s, r in results.items()}
    last = dict.fromkeys(results, share.initial_equity)
    curve = []
    for hour in hours:
        for s in results:
            if hour in by_hour[s]:
                last[s] = by_hour[s][hour]
        curve.append((hour, sum(last.values())))
    invested = sum(r.time_invested for r in results.values()) / len(results)
    total = _summarise(
        curve,
        config,
        earned=sum(r.funding_earned for r in results.values()),
        costs=sum(r.costs for r in results.values()),
        entries=sum(r.entries for r in results.values()),
        rebalances=sum(r.rebalances for r in results.values()),
        invested_hours=round(invested * len(curve)),
    )
    return CarryPortfolio(per_asset=results, total=total)
