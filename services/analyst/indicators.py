"""Technical indicators, as plain functions over closed candles.

Each returns a list aligned with its input, with `None` until enough history
exists — never a value computed from a partial window, which would make early
signals look more certain than they are.
"""

from __future__ import annotations

from collections.abc import Sequence

from services.analyst.candles import Candle


def sma(values: Sequence[float], length: int) -> list[float | None]:
    if length < 1:
        raise ValueError("length must be at least 1")
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for i, value in enumerate(values):
        running += value
        if i >= length:
            running -= values[i - length]
        if i >= length - 1:
            out[i] = running / length
    return out


def ema(values: Sequence[float], length: int) -> list[float | None]:
    """Exponential moving average, seeded with the SMA of the first `length` values."""
    if length < 1:
        raise ValueError("length must be at least 1")
    out: list[float | None] = [None] * len(values)
    if len(values) < length:
        return out
    alpha = 2 / (length + 1)
    current = sum(values[:length]) / length
    out[length - 1] = current
    for i in range(length, len(values)):
        current = alpha * values[i] + (1 - alpha) * current
        out[i] = current
    return out


def true_range(candles: Sequence[Candle]) -> list[float]:
    ranges = []
    for i, candle in enumerate(candles):
        if i == 0:
            ranges.append(candle.high - candle.low)
            continue
        previous_close = candles[i - 1].close
        ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    return ranges


def atr(candles: Sequence[Candle], length: int = 14) -> list[float | None]:
    """Average True Range with Wilder's smoothing (Wilder, 1978).

    Seeded with the simple mean of the first `length` true ranges, then
    ATR_t = (ATR_{t-1} * (n - 1) + TR_t) / n.
    """
    if length < 1:
        raise ValueError("length must be at least 1")
    ranges = true_range(candles)
    out: list[float | None] = [None] * len(candles)
    if len(candles) < length:
        return out
    current = sum(ranges[:length]) / length
    out[length - 1] = current
    for i in range(length, len(candles)):
        current = (current * (length - 1) + ranges[i]) / length
        out[i] = current
    return out


def trailing_return(closes: Sequence[float], lookback: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    for i in range(lookback, len(closes)):
        out[i] = closes[i] / closes[i - lookback] - 1
    return out
