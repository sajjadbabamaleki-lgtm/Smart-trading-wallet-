"""Cross-sectional strategies on the broad Binance universe, rebalanced weekly.

The trend factor of Han, Zhou & Zhu (2016, JFE) for stocks, carried to
cryptocurrencies as CTREND by Fieberg, Liedtke, Poddig, Walker & Zaremba
(2025, JFQA): combine moving-average signals of price and volume over many
horizons into one expected return, using the average of past weekly
cross-sectional regressions as the weights; long the coins it ranks highest,
short the lowest.

This is a simplified replication, stated as such: the paper combines 28
technical indicators with machine learning; here thirteen moving-average
signals (seven of price, six of volume) are combined by the rolling average
of weekly OLS slopes, the Han-Zhou-Zhu method. Every choice is fixed below,
before any result.

Portfolio mechanics, identical for every strategy in this module:
- universe each week: the 50 most traded perpetuals over the past 30 days
  (point-in-time, delisted coins included), with 200 days of history;
- signals at the Sunday close, positions held from Monday 00:00 UTC for a week;
- long the top fifth, short the bottom fifth, equal weights, half the capital
  per side (dollar neutral, 1x gross);
- costs: 0.045% taker fee + 0.10% slippage per unit of turnover; daily funding
  (longs pay a positive rate); a coin that stops trading exits at its last close.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Final

from services.analyst.backtest import probabilistic_sharpe
from services.lab.binance import Day, Market

DAY: Final = timedelta(days=1)
UNIVERSE_SIZE: Final = 50
VOLUME_DAYS: Final = 30
MIN_HISTORY_DAYS: Final = 200
QUANTILE: Final = 0.2
GROSS_PER_SIDE: Final = 0.5
COST_PER_TURNOVER: Final = 0.00045 + 0.0010
PRICE_LAGS: Final = (3, 5, 10, 20, 50, 100, 200)
VOLUME_LAGS: Final = (3, 5, 10, 20, 50, 100)
COEFFICIENT_WEEKS: Final = 52
MIN_COEFFICIENT_WEEKS: Final = 26
DAYS_PER_YEAR: Final = 365


@dataclass(frozen=True)
class XResult:
    strategy: str
    days: list[datetime]
    returns: list[float]
    basket: list[float]
    """Equal-weight long-only return of the same universe, for comparison."""
    turnover: float
    costs: float
    funding: float

    def window(self, start: datetime, end: datetime) -> XResult:
        keep = [i for i, d in enumerate(self.days) if start <= d < end]
        return XResult(
            self.strategy,
            [self.days[i] for i in keep],
            [self.returns[i] for i in keep],
            [self.basket[i] for i in keep],
            self.turnover,
            self.costs,
            self.funding,
        )


@dataclass(frozen=True)
class XMetrics:
    start: datetime
    end: datetime
    total_return: float
    annual_return: float
    annual_volatility: float
    sharpe: float
    max_drawdown: float
    profit_factor: float
    probabilistic_sharpe: float
    basket_return: float
    basket_max_drawdown: float


def compound(returns: Sequence[float]) -> list[float]:
    curve, value = [], 1.0
    for r in returns:
        value *= 1 + r
        curve.append(value)
    return curve


def max_drawdown(curve: Sequence[float]) -> float:
    peak, worst = 1.0, 0.0
    for value in curve:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


def metrics(result: XResult) -> XMetrics:
    r = result.returns
    if len(r) < 2:  # noqa: PLR2004
        raise ValueError("the window holds fewer than two days")
    curve, basket = compound(r), compound(result.basket)
    mean, sd = statistics.fmean(r), statistics.pstdev(r)
    gains, losses = sum(x for x in r if x > 0), -sum(x for x in r if x < 0)
    years = len(r) / DAYS_PER_YEAR
    return XMetrics(
        start=result.days[0],
        end=result.days[-1],
        total_return=curve[-1] - 1,
        annual_return=curve[-1] ** (1 / years) - 1 if curve[-1] > 0 else -1.0,
        annual_volatility=sd * math.sqrt(DAYS_PER_YEAR),
        sharpe=mean / sd * math.sqrt(DAYS_PER_YEAR) if sd else 0.0,
        max_drawdown=max_drawdown(curve),
        profit_factor=gains / losses if losses else math.inf,
        probabilistic_sharpe=probabilistic_sharpe(r),
        basket_return=basket[-1] - 1,
        basket_max_drawdown=max_drawdown(basket),
    )


def moments(returns: Sequence[float]) -> tuple[float, int, float, float]:
    """Sharpe per day, observations, skew and kurtosis — what the registry needs."""
    mean, sd = statistics.fmean(returns), statistics.pstdev(returns)
    if not sd:
        return 0.0, len(returns), 0.0, 3.0
    n = len(returns)
    skew = sum(((x - mean) / sd) ** 3 for x in returns) / n
    kurt = sum(((x - mean) / sd) ** 4 for x in returns) / n
    return mean / sd, n, skew, kurt


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


class Panel:
    """Aligned daily closes and traded value per symbol, with prefix sums so
    a moving average costs O(1)."""

    def __init__(self, market: Market) -> None:
        self.market = market
        self.times: dict[str, list[datetime]] = {}
        self.close: dict[str, list[float]] = {}
        self.value_sum: dict[str, list[float]] = {}
        self.close_sum: dict[str, list[float]] = {}
        for symbol, days in market.days.items():
            self.times[symbol] = [d.time for d in days]
            self.close[symbol] = [d.close for d in days]
            self.close_sum[symbol] = _prefix(d.close for d in days)
            self.value_sum[symbol] = _prefix(d.quote_volume for d in days)

    def index(self, symbol: str, day: datetime) -> int | None:
        times = self.times[symbol]
        i = bisect.bisect_left(times, day)
        return i if i < len(times) and times[i] == day else None

    def mean_close(self, symbol: str, i: int, lag: int) -> float:
        s = self.close_sum[symbol]
        return (s[i + 1] - s[i + 1 - lag]) / lag

    def mean_value(self, symbol: str, i: int, lag: int) -> float:
        s = self.value_sum[symbol]
        return (s[i + 1] - s[i + 1 - lag]) / lag

    def universe(self, day: datetime) -> list[str]:
        """The most traded symbols over the past 30 days, among those with
        enough history — using only data up to `day`."""
        ranked = []
        for symbol in self.times:
            i = self.index(symbol, day)
            if i is None or i + 1 < MIN_HISTORY_DAYS:
                continue
            ranked.append((self.mean_value(symbol, i, VOLUME_DAYS), symbol))
        ranked.sort(reverse=True)
        return [s for _, s in ranked[:UNIVERSE_SIZE]]

    def close_on_or_before(self, symbol: str, day: datetime) -> float | None:
        times = self.times[symbol]
        i = bisect.bisect_right(times, day) - 1
        return self.close[symbol][i] if i >= 0 else None


def _prefix(values: Iterable[float]) -> list[float]:
    out = [0.0]
    for v in values:
        out.append(out[-1] + v)
    return out


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


def trend_features(panel: Panel, symbol: str, day: datetime) -> list[float] | None:
    i = panel.index(symbol, day)
    if i is None or i + 1 < MIN_HISTORY_DAYS:
        return None
    close = panel.close[symbol][i]
    long_value = panel.mean_value(symbol, i, MIN_HISTORY_DAYS)
    if close <= 0 or long_value <= 0:
        return None
    price = [panel.mean_close(symbol, i, lag) / close for lag in PRICE_LAGS]
    volume = [panel.mean_value(symbol, i, lag) / long_value for lag in VOLUME_LAGS]
    return price + volume


def rank_scale(rows: list[list[float]]) -> list[list[float]]:
    """Each column replaced by its cross-sectional rank, scaled to [-0.5, 0.5],
    so an outlier coin cannot dominate a regression."""
    n, k = len(rows), len(rows[0])
    out = [[0.0] * k for _ in range(n)]
    for j in range(k):
        order = sorted(range(n), key=lambda i: rows[i][j])
        for rank, i in enumerate(order):
            out[i][j] = rank / (n - 1) - 0.5 if n > 1 else 0.0
    return out


RIDGE: Final = 1e-4
"""A negligible ridge penalty (relative to the sample size) on the slopes, so
exactly collinear signals — two horizons ranking the coins identically — still
give a stable solution instead of a singular system."""


def ols(x: list[list[float]], y: list[float]) -> list[float]:
    """Least squares with an intercept, by the normal equations (small k).
    Returns the slopes."""
    rows = [[1.0, *r] for r in x]
    k = len(rows[0])
    a = [[sum(r[i] * r[j] for r in rows) for j in range(k)] for i in range(k)]
    for i in range(1, k):
        a[i][i] += RIDGE * len(rows)
    b = [sum(r[i] * v for r, v in zip(rows, y, strict=True)) for i in range(k)]
    for col in range(k):
        pivot = max(range(col, k), key=lambda i: abs(a[i][col]))
        a[col], a[pivot] = a[pivot], a[col]
        b[col], b[pivot] = b[pivot], b[col]
        for i in range(k):
            if i != col:
                f = a[i][col] / a[col][col]
                a[i] = [v - f * w for v, w in zip(a[i], a[col], strict=True)]
                b[i] -= f * b[col]
    return [b[i] / a[i][i] for i in range(1, k)]


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


def _sundays(first: datetime, last: datetime) -> list[datetime]:
    day = first + timedelta(days=(6 - first.weekday()) % 7)
    out = []
    while day <= last:
        out.append(day)
        day += timedelta(weeks=1)
    return out


def _period_return(panel: Panel, symbol: str, start: datetime, end: datetime) -> float | None:
    a = panel.close_on_or_before(symbol, start)
    b = panel.close_on_or_before(symbol, end)
    return b / a - 1 if a and b is not None else None


def run_ctrend(market: Market) -> XResult:
    panel = Panel(market)
    first = min(t[0] for t in panel.times.values())
    last = max(t[-1] for t in panel.times.values())
    sundays = _sundays(first + DAY * MIN_HISTORY_DAYS, last)

    slopes: list[tuple[datetime, list[float]]] = []  # (week realised at, coefficients)
    snapshots: dict[datetime, tuple[list[str], list[list[float]]]] = {}
    targets: dict[datetime, dict[str, float]] = {}
    for sunday in sundays:
        universe = panel.universe(sunday)
        feats = [(s, f) for s in universe if (f := trend_features(panel, s, sunday)) is not None]
        if len(feats) >= UNIVERSE_SIZE // 2:
            snapshots[sunday] = ([s for s, _ in feats], rank_scale([f for _, f in feats]))
        previous = sunday - timedelta(weeks=1)
        if previous in snapshots:  # last week's cross-section has just been realised
            symbols, x = snapshots[previous]
            y = [_period_return(panel, s, previous, sunday) for s in symbols]
            pairs = [(xi, yi) for xi, yi in zip(x, y, strict=True) if yi is not None]
            if len(pairs) > len(x[0]) + 5:
                slopes.append((sunday, ols([p[0] for p in pairs], [p[1] for p in pairs])))
        usable = [c for t, c in slopes if t <= sunday][-COEFFICIENT_WEEKS:]
        if sunday not in snapshots or len(usable) < MIN_COEFFICIENT_WEEKS:
            continue
        weights = [statistics.fmean(c[j] for c in usable) for j in range(len(usable[0]))]
        symbols, x = snapshots[sunday]
        forecast = {
            s: sum(w * v for w, v in zip(weights, row, strict=True))
            for s, row in zip(symbols, x, strict=True)
        }
        targets[sunday] = _long_short(forecast)
    return _simulate(panel, "ctrend-lite", targets, last)


def _long_short(forecast: dict[str, float]) -> dict[str, float]:
    ranked = sorted(forecast, key=forecast.__getitem__)
    k = max(1, int(len(ranked) * QUANTILE))
    weights = dict.fromkeys(ranked[-k:], GROSS_PER_SIDE / k)
    weights |= dict.fromkeys(ranked[:k], -GROSS_PER_SIDE / k)
    return weights


def _simulate(
    panel: Panel, name: str, targets: dict[datetime, dict[str, float]], last: datetime
) -> XResult:
    """Daily returns: weights set at each Sunday close drift with prices until
    the next; turnover pays costs, positions pay or receive funding."""
    rebalances = sorted(targets)
    if not rebalances:
        raise ValueError("no week had enough history to trade")
    weights: dict[str, float] = {}
    days, returns, basket = [], [], []
    turnover_total = costs_total = funding_total = 0.0
    day = rebalances[0]
    while day + DAY <= last:
        cost = 0.0
        if day in targets:
            target = targets[day]
            turnover = sum(
                abs(target.get(s, 0.0) - weights.get(s, 0.0)) for s in set(target) | set(weights)
            )
            cost = turnover * COST_PER_TURNOVER
            turnover_total += turnover
            weights = dict(target)
            universe = panel.universe(day)
        tomorrow = day + DAY
        moves = {s: _period_return(panel, s, day, tomorrow) or 0.0 for s in weights}
        pnl = sum(w * moves[s] for s, w in weights.items())
        funding = sum(
            w * panel.market.funding.get(s, {}).get(tomorrow, 0.0) for s, w in weights.items()
        )
        daily = pnl - funding - cost
        gross_after = 1 + daily
        weights = {s: w * (1 + moves[s]) / gross_after for s, w in weights.items()}
        basket_moves = [
            m for s in universe if (m := _period_return(panel, s, day, tomorrow)) is not None
        ]
        days.append(tomorrow)
        returns.append(daily)
        basket.append(statistics.fmean(basket_moves) if basket_moves else 0.0)
        costs_total += cost
        funding_total += funding
        day = tomorrow
    return XResult(name, days, returns, basket, turnover_total, costs_total, funding_total)


def annual_turnover(result: XResult) -> float:
    years = (result.days[-1] - result.days[0]) / DAY / DAYS_PER_YEAR
    return result.turnover / years if years > 0 else 0.0


def weekly(returns: Sequence[float]) -> list[float]:
    return [c / p - 1 for p, c in pairwise([1.0, *compound(returns)[6::7]])]


XCATALOGUE: Final = {"ctrend-lite": run_ctrend}
XSOURCES: Final = {
    "ctrend-lite": (
        "Fieberg, Liedtke, Poddig, Walker & Zaremba (2025, JFQA), 'A Trend Factor for the "
        "Cross Section of Cryptocurrency Returns'; method of Han, Zhou & Zhu (2016, JFE). "
        "Simplified: 13 moving-average signals, rolling-OLS weights."
    )
}


__all__ = ["Day", "XMetrics", "XResult", "metrics", "moments", "run_ctrend"]
