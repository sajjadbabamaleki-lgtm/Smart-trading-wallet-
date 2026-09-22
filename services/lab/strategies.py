"""The strategy catalogue. Every parameter is fixed here, before any lab result.

A strategy sees, at each candle close, only candles up to that close, and
answers with actions for the next open: enter with a stop (and optionally a
target), exit, or trail the stop. Fills, costs and sizing belong to the
shared simulator, identical for every strategy.

Adding a strategy means adding a class here with its source. Changing a
parameter of an existing one is a new trial and must get a new name — the
registry counts trials by name, and a quietly edited strategy would hide a
trial from the Deflated Sharpe Ratio.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, Final

from services.analyst.candles import Candle
from services.analyst.indicators import atr
from services.analyst.strategy import InsufficientHistoryError, StrategyParams, TrendIndicators
from services.trader.venue import Direction

BARS_PER_DAY: Final = 6
"""4h candles."""
CHANDELIER_ATR: Final = 3.0
"""Trailing stop distance for the trend strategies: 3 x ATR(14) from the best
close since entry — the chandelier exit (LeBeau), the usual trend-following
trail. Wide enough that ordinary noise does not end a trend trade."""


@dataclass(frozen=True)
class Enter:
    direction: Direction
    stop: float
    target: float | None = None


@dataclass(frozen=True)
class Exit:
    pass


@dataclass(frozen=True)
class MoveStop:
    stop: float


Action = Enter | Exit | MoveStop


@dataclass(frozen=True)
class Held:
    direction: Direction
    entry_index: int
    stop: float


class Strategy(ABC):
    name: ClassVar[str]
    summary: ClassVar[str]
    source: ClassVar[str]

    def prepare(self, candles: dict[str, list[Candle]]) -> None:
        self.candles = candles
        self.atr = {s: atr(c, 14) for s, c in candles.items()}

    @abstractmethod
    def decide(
        self, time: datetime, index: dict[str, int], held: dict[str, Held | None]
    ) -> list[tuple[str, Action]]:
        """Actions for the next open. `index` holds the assets whose candle
        closed at `time`, and the position of that candle in their history."""

    # ------------------------------------------------------------------

    def _atr(self, symbol: str, i: int) -> float | None:
        value = self.atr[symbol][i]
        return value if value and value > 0 else None

    def _chandelier(self, symbol: str, i: int, held: Held) -> float | None:
        volatility = self._atr(symbol, i)
        if volatility is None:
            return None
        closes = [c.close for c in self.candles[symbol][held.entry_index : i + 1]]
        if held.direction is Direction.LONG:
            return max(closes) - CHANDELIER_ATR * volatility
        return min(closes) + CHANDELIER_ATR * volatility

    def _protective_stop(self, symbol: str, i: int, direction: Direction) -> float | None:
        volatility = self._atr(symbol, i)
        if volatility is None:
            return None
        close = self.candles[symbol][i].close
        distance = CHANDELIER_ATR * volatility
        return close - distance if direction is Direction.LONG else close + distance


# ---------------------------------------------------------------------------
# 1. The original trend strategy, as a control
# ---------------------------------------------------------------------------


class TrendFixedTarget(Strategy):
    name = "trend-2r"
    summary = "six momentum/average votes; stop 2 ATR, fixed target 2R, exit when votes fade"
    source = (
        "Liu & Tsyvinski (2021, RFS); Detzel et al. (2021, Financial Management). "
        "Already tested outside the lab — included as the control."
    )

    def prepare(self, candles: dict[str, list[Candle]]) -> None:
        super().prepare(candles)
        self.trend = {s: TrendIndicators(c, "4h", StrategyParams()) for s, c in candles.items()}

    def decide(
        self,
        time: datetime,  # noqa: ARG002 — part of the interface; this rule ignores it
        index: dict[str, int],
        held: dict[str, Held | None],
    ) -> list[tuple[str, Action]]:
        actions: list[tuple[str, Action]] = []
        for symbol, i in index.items():
            indicators = self.trend[symbol]
            try:
                position = held[symbol]
                if position is not None:
                    if indicators.should_exit(i, position.direction):
                        actions.append((symbol, Exit()))
                    continue
                signal = indicators.signal(i)
            except InsufficientHistoryError:
                continue
            if signal.direction is not None and signal.stop_loss is not None:
                actions.append(
                    (symbol, Enter(signal.direction, signal.stop_loss, signal.take_profit))
                )
        return actions


# ---------------------------------------------------------------------------
# 2. Same entries, trailing exit
# ---------------------------------------------------------------------------


class TrendTrailing(Strategy):
    name = "trend-trailing"
    summary = "same six votes to enter; no target — a 3 ATR chandelier stop trails the trend"
    source = (
        "Trend following earns from a few large trends; a fixed target cuts exactly those "
        "(Hurst, Ooi & Pedersen 2017; Zarattini, Pagani & Barbon 2025 use trailing exits)."
    )

    def prepare(self, candles: dict[str, list[Candle]]) -> None:
        super().prepare(candles)
        self.trend = {s: TrendIndicators(c, "4h", StrategyParams()) for s, c in candles.items()}

    def decide(
        self,
        time: datetime,  # noqa: ARG002 — part of the interface; this rule ignores it
        index: dict[str, int],
        held: dict[str, Held | None],
    ) -> list[tuple[str, Action]]:
        actions: list[tuple[str, Action]] = []
        for symbol, i in index.items():
            position = held[symbol]
            if position is not None:
                stop = self._chandelier(symbol, i, position)
                if stop is not None:
                    actions.append((symbol, MoveStop(stop)))
                continue
            try:
                signal = self.trend[symbol].signal(i)
            except InsufficientHistoryError:
                continue
            if signal.direction is None:
                continue
            stop = self._protective_stop(symbol, i, signal.direction)
            if stop is not None:
                actions.append((symbol, Enter(signal.direction, stop)))
        return actions


# ---------------------------------------------------------------------------
# 3. Donchian breakout ensemble
# ---------------------------------------------------------------------------


def _rolling_extremes(values: Sequence[float], window: int, *, highest: bool) -> list[float | None]:
    """Extreme of the `window` values *before* each index, in O(n).

    Keeps a deque of indices whose values are monotonic, so the front is always
    the extreme of the current window. The current value is added only after
    its own index is answered, which is what makes a breakout a breakout.
    """
    out: list[float | None] = [None] * len(values)
    candidates: deque[int] = deque()
    for i, value in enumerate(values):
        while candidates and candidates[0] < i - window:
            candidates.popleft()
        if i >= window:
            out[i] = values[candidates[0]]
        while candidates and (
            values[candidates[-1]] <= value if highest else values[candidates[-1]] >= value
        ):
            candidates.pop()
        candidates.append(i)
    return out


class DonchianEnsemble(Strategy):
    name = "donchian-ensemble"
    summary = (
        "breakout of the 10/20/40/80-day channel per lookback; enter when 3 of 4 agree; "
        "3 ATR chandelier stop; exit if the ensemble turns against the position"
    )
    source = (
        "Zarattini, Pagani & Barbon (2025): an ensemble of Donchian channels over several "
        "lookbacks; channel breakouts are the Turtle rules' entry (Faith, 2007)."
    )
    lookback_days: ClassVar = (10, 20, 40, 80)
    threshold: ClassVar = 0.5

    def prepare(self, candles: dict[str, list[Candle]]) -> None:
        super().prepare(candles)
        self.score: dict[str, list[float | None]] = {}
        for symbol, series in candles.items():
            highs = [c.high for c in series]
            lows = [c.low for c in series]
            states: list[list[int]] = []
            for days in self.lookback_days:
                window = days * BARS_PER_DAY
                upper = _rolling_extremes(highs, window, highest=True)
                lower = _rolling_extremes(lows, window, highest=False)
                state, current = [], 0
                for candle, high, low in zip(series, upper, lower, strict=True):
                    if high is not None and candle.close > high:
                        current = 1
                    elif low is not None and candle.close < low:
                        current = -1
                    state.append(current)
                states.append(state)
            longest = max(self.lookback_days) * BARS_PER_DAY
            self.score[symbol] = [
                sum(s[i] for s in states) / len(states) if i >= longest else None
                for i in range(len(series))
            ]

    def decide(
        self,
        time: datetime,  # noqa: ARG002 — part of the interface; this rule ignores it
        index: dict[str, int],
        held: dict[str, Held | None],
    ) -> list[tuple[str, Action]]:
        actions: list[tuple[str, Action]] = []
        for symbol, i in index.items():
            score = self.score[symbol][i]
            if score is None:
                continue
            position = held[symbol]
            if position is not None:
                against = score < 0 if position.direction is Direction.LONG else score > 0
                if against:
                    actions.append((symbol, Exit()))
                else:
                    stop = self._chandelier(symbol, i, position)
                    if stop is not None:
                        actions.append((symbol, MoveStop(stop)))
                continue
            direction = (
                Direction.LONG
                if score >= self.threshold
                else Direction.SHORT
                if score <= -self.threshold
                else None
            )
            if direction is not None:
                stop = self._protective_stop(symbol, i, direction)
                if stop is not None:
                    actions.append((symbol, Enter(direction, stop)))
        return actions


# ---------------------------------------------------------------------------
# 4. Cross-sectional momentum
# ---------------------------------------------------------------------------


class CrossSectionalMomentum(Strategy):
    name = "xsec-momentum"
    summary = (
        "every Monday 00:00 UTC: long the 3 assets with the best 21-day return, short the "
        "3 worst; hold a week; 3 ATR protective stop"
    )
    source = (
        "Liu, Tsyvinski & Wu (2022, Journal of Finance): cross-sectional momentum is one of "
        "three factors that explain cryptocurrency returns."
    )
    lookback_days: ClassVar = 21
    bucket: ClassVar = 3

    def decide(
        self, time: datetime, index: dict[str, int], held: dict[str, Held | None]
    ) -> list[tuple[str, Action]]:
        closes_at = time + timedelta(hours=4)
        if closes_at.weekday() != 0 or closes_at.hour != 0:
            return []
        lookback = self.lookback_days * BARS_PER_DAY
        returns = {
            s: self.candles[s][i].close / self.candles[s][i - lookback].close - 1
            for s, i in index.items()
            if i >= lookback
        }
        if len(returns) < 2 * self.bucket:
            return []
        ranked = sorted(returns, key=returns.__getitem__, reverse=True)
        wanted = dict.fromkeys(ranked[: self.bucket], Direction.LONG)
        wanted |= dict.fromkeys(ranked[-self.bucket :], Direction.SHORT)

        actions: list[tuple[str, Action]] = []
        for symbol, i in index.items():
            position = held[symbol]
            target = wanted.get(symbol)
            if position is not None and position.direction is not target:
                actions.append((symbol, Exit()))
            if target is not None and (position is None or position.direction is not target):
                stop = self._protective_stop(symbol, i, target)
                if stop is not None:
                    actions.append((symbol, Enter(target, stop)))
        return actions


CATALOGUE: Final[dict[str, type[Strategy]]] = {
    cls.name: cls
    for cls in (TrendFixedTarget, TrendTrailing, DonchianEnsemble, CrossSectionalMomentum)
}
