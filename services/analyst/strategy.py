"""Trend strategy: an ensemble of momentum and moving-average votes.

Why these rules — each is tied to published evidence (full references in
`services/analyst/README.md`):

- **Time-series momentum.** Liu & Tsyvinski (2021, Review of Financial
  Studies) find strong time-series momentum in cryptocurrency returns at
  one- to four-week horizons. Three votes: the sign of the 7, 14 and 28-day
  return.
- **Price relative to moving averages.** Detzel et al. (2021, Financial
  Management) show that ratios of price to its moving averages forecast
  Bitcoin returns in and out of sample. Three votes: close above or below
  the 20, 50 and 100-day simple moving average.
- **An ensemble, not one lookback.** Zarattini, Pagani & Barbon (2025)
  aggregate many lookbacks into one signal so the result does not hinge on a
  single parameter choice. Six votes, averaged into a score in [-1, 1].
- **Volatility-scaled risk.** The stop is 2 x ATR(14) from entry and the
  position is sized so hitting it loses a fixed share of equity. Wider
  volatility means a smaller position — the volatility management that
  Moreira & Muir (2017, Journal of Finance) show improves risk-adjusted
  returns.

**Parameters are fixed here, not fitted.** Every value is a round number
chosen before looking at results. Searching over them until a backtest
looks good is how overfit strategies are made (Bailey, Borwein, López de
Prado & Zhu, 2014); changing them means re-running the backtest and
treating the result with the same suspicion.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from services.analyst.candles import INTERVALS, Candle
from services.analyst.indicators import atr, sma, trailing_return
from services.trader.venue import Direction

MOMENTUM_LOOKBACK_DAYS: Final = (7, 14, 28)
MOVING_AVERAGE_DAYS: Final = (20, 50, 100)
ENTRY_THRESHOLD: Final = 0.66
"""|score| needed to enter: at least five of the six votes agree."""
EXIT_THRESHOLD: Final = 0.0
"""An open position is exited once the majority no longer supports it."""
ATR_LENGTH: Final = 14
STOP_ATR_MULTIPLE: Final = 2.0
TARGET_R_MULTIPLE: Final = 2.0
MAX_FUNDING_APR: Final = 1.0
"""Skip a long when longs pay more than 100% a year in funding (a short when
they receive more than that). Besides signalling crowded positioning, it is a
direct cost: 100% a year is about 0.27% of the position per day."""
HOURS_PER_YEAR: Final = 24 * 365


@dataclass(frozen=True)
class StrategyParams:
    momentum_lookback_days: tuple[int, ...] = MOMENTUM_LOOKBACK_DAYS
    moving_average_days: tuple[int, ...] = MOVING_AVERAGE_DAYS
    entry_threshold: float = ENTRY_THRESHOLD
    exit_threshold: float = EXIT_THRESHOLD
    atr_length: int = ATR_LENGTH
    stop_atr_multiple: float = STOP_ATR_MULTIPLE
    target_r_multiple: float = TARGET_R_MULTIPLE
    allow_short: bool = True
    max_funding_apr: float = MAX_FUNDING_APR

    def bars(self, days: int, interval: str) -> int:
        per_day = 24 * 3600 / INTERVALS[interval].total_seconds()
        return max(1, round(days * per_day))

    def warmup_bars(self, interval: str) -> int:
        longest = max(*self.momentum_lookback_days, *self.moving_average_days)
        return max(self.bars(longest, interval) + 1, self.atr_length + 1)


@dataclass(frozen=True)
class Signal:
    close: float
    score: float
    votes: dict[str, int]
    atr: float
    direction: Direction | None
    stop_loss: float | None
    take_profit: float | None
    reasons: list[str] = field(default_factory=list)


class InsufficientHistoryError(ValueError):
    pass


class TrendIndicators:
    """All indicator series for one candle history, computed once.

    The backtester evaluates every bar; recomputing each series per bar would
    be quadratic. Values at index i use only candles up to and including i.
    """

    def __init__(self, candles: Sequence[Candle], interval: str, params: StrategyParams) -> None:
        self.candles = candles
        self.params = params
        closes = [c.close for c in candles]
        self.closes = closes
        self.momentum = {
            days: trailing_return(closes, params.bars(days, interval))
            for days in params.momentum_lookback_days
        }
        self.averages = {
            days: sma(closes, params.bars(days, interval)) for days in params.moving_average_days
        }
        self.atr = atr(candles, params.atr_length)
        self.warmup = params.warmup_bars(interval)

    def score(self, i: int) -> tuple[float, dict[str, int]]:
        votes: dict[str, int] = {}
        for days, series in self.momentum.items():
            value = series[i]
            if value is None:
                raise InsufficientHistoryError(f"needs {days} days of history")
            votes[f"{days}d return"] = 1 if value > 0 else -1 if value < 0 else 0
        for days, series in self.averages.items():
            average = series[i]
            if average is None:
                raise InsufficientHistoryError(f"needs {days} days of history")
            close = self.closes[i]
            votes[f"vs {days}d average"] = 1 if close > average else -1 if close < average else 0
        return sum(votes.values()) / len(votes), votes

    def signal(  # noqa: PLR0912 — each branch is one documented rule
        self, i: int, *, funding_hourly: float | None = None
    ) -> Signal:
        if i + 1 < self.warmup:
            raise InsufficientHistoryError(f"needs {self.warmup} candles of history, have {i + 1}")
        score, votes = self.score(i)
        volatility = self.atr[i]
        if volatility is None or volatility <= 0:
            raise InsufficientHistoryError("ATR is not available yet")
        close = self.closes[i]
        params = self.params
        reasons: list[str] = []

        direction: Direction | None = None
        if score >= params.entry_threshold:
            direction = Direction.LONG
        elif score <= -params.entry_threshold:
            if params.allow_short:
                direction = Direction.SHORT
            else:
                reasons.append("downtrend, but shorts are disabled")
        else:
            reasons.append(
                f"no clear trend: score {score:+.2f}, needs at least ±{params.entry_threshold:.2f}"
            )

        if direction is not None and funding_hourly is not None:
            apr = funding_hourly * HOURS_PER_YEAR
            if direction is Direction.LONG and apr > params.max_funding_apr:
                reasons.append(f"longs are crowded: funding {apr:+.0%} a year")
                direction = None
            elif direction is Direction.SHORT and apr < -params.max_funding_apr:
                reasons.append(f"shorts are crowded: funding {apr:+.0%} a year")
                direction = None

        stop = target = None
        if direction is not None:
            distance = params.stop_atr_multiple * volatility
            if direction is Direction.LONG:
                stop, target = close - distance, close + distance * params.target_r_multiple
            else:
                stop, target = close + distance, close - distance * params.target_r_multiple
            agreeing = sum(
                1 for v in votes.values() if v == (1 if direction is Direction.LONG else -1)
            )
            reasons.append(
                f"{direction.value} trend: {agreeing} of {len(votes)} votes agree "
                f"(score {score:+.2f})"
            )
            reasons.append(
                f"stop {params.stop_atr_multiple:g} x ATR({params.atr_length}) = "
                f"{distance:.4g} from price; target {params.target_r_multiple:g}R"
            )
        return Signal(
            close=close,
            score=score,
            votes=votes,
            atr=volatility,
            direction=direction,
            stop_loss=stop,
            take_profit=target,
            reasons=reasons,
        )

    def should_exit(self, i: int, direction: Direction) -> bool:
        score, _ = self.score(i)
        if direction is Direction.LONG:
            return score < self.params.exit_threshold
        return score > -self.params.exit_threshold
