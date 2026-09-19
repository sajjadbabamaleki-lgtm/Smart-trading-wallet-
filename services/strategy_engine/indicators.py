"""The indicators a trader names, computed the conventional way.

`features.py` already measures trend, momentum, volatility and levels, and it
measures them in forms this project chose. That is fine for a rule and wrong
for a person: a trader reads RSI, MACD, Bollinger bands and the 20/50/200
moving averages, and a report that says "trend_bps +43" instead is a report
nobody can check against their own chart.

So these are the standard definitions, not improved ones. Wilder's RSI, MACD
as 12/26 with a 9 signal, Bollinger as 20 with two standard deviations. Where
a choice exists it goes to the convention, because the value of these numbers
is that they mean the same thing here as everywhere else.

**Every function takes a window ending at the candle being judged.** Same
guarantee as the feature engine: there is no series to index past, so nothing
can read forward.

**The exponential averages are computed over a bounded lookback**, seeded with
a simple average. A true EMA depends on every candle since the beginning of
time, which costs a full pass per candle and makes a six-year backtest
quadratic. Seeding `SEED_MULTIPLE` periods back leaves the difference below a
hundredth of a percent — an EMA's weight on a candle `n` periods old decays as
`(1 - 2/(n+1))^n` — and it makes the cost constant per candle. The trade is
named here rather than discovered later in a profiler.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

BPS: Final = Decimal(10000)

RSI_PERIOD: Final = 14
MACD_FAST: Final = 12
MACD_SLOW: Final = 26
MACD_SIGNAL: Final = 9
BOLLINGER_PERIOD: Final = 20
BOLLINGER_SIGMA: Final = Decimal(2)
MOVING_AVERAGES: Final = (20, 50, 200)

SEED_MULTIPLE: Final = 6
"""How many periods of history an exponential average is seeded from.

Six: an EMA's weight on a candle six periods older than its span is under
0.1%, so the bounded result and the unbounded one agree to well within the
precision anything downstream uses.
"""

RSI_OVERBOUGHT: Final = Decimal(70)
RSI_OVERSOLD: Final = Decimal(30)
RSI_MIDPOINT: Final = Decimal(50)
"""The conventional thresholds. Not tuned, and deliberately not: their value
is that a reader already knows what they mean."""


def warmup_needed() -> int:
    """Candles required before every indicator here is complete.

    Stated as one number so a caller cannot satisfy some indicators and
    silently receive a half-formed version of the rest.
    """
    return max(
        *MOVING_AVERAGES,
        RSI_PERIOD + 1,
        (MACD_SLOW + MACD_SIGNAL) * SEED_MULTIPLE,
        BOLLINGER_PERIOD,
    )


def sma(values: Sequence[Decimal], period: int) -> Decimal:
    """Simple average of the last `period` values."""
    if len(values) < period:
        raise ValueError(f"need {period} values for a simple average, got {len(values)}")
    window = values[-period:]
    return sum(window, Decimal(0)) / period


def ema(values: Sequence[Decimal], period: int) -> Decimal:
    """Exponential average of the last values, seeded from a simple one."""
    if len(values) < period:
        raise ValueError(f"need {period} values for an exponential average, got {len(values)}")
    span = min(len(values), period * SEED_MULTIPLE)
    window = values[-span:]
    multiplier = Decimal(2) / Decimal(period + 1)
    current = sma(window[:period], period)
    for value in window[period:]:
        current = (value - current) * multiplier + current
    return current


def rsi(values: Sequence[Decimal], period: int = RSI_PERIOD) -> Decimal:
    """Wilder's relative strength index, 0 to 100.

    Wilder's smoothing rather than a simple average of gains and losses, which
    is what "RSI" means on a chart. A period with no losses at all returns 100
    rather than dividing by zero, which is also what a chart shows.
    """
    if len(values) < period + 1:
        raise ValueError(f"need {period + 1} values for RSI, got {len(values)}")
    span = min(len(values), (period + 1) * SEED_MULTIPLE)
    window = values[-span:]
    changes = [later - earlier for earlier, later in itertools.pairwise(window)]

    gains = [change if change > 0 else Decimal(0) for change in changes]
    losses = [-change if change < 0 else Decimal(0) for change in changes]
    average_gain = sum(gains[:period], Decimal(0)) / period
    average_loss = sum(losses[:period], Decimal(0)) / period
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period

    if average_loss == 0:
        return Decimal(100) if average_gain > 0 else Decimal(50)
    strength = average_gain / average_loss
    return Decimal(100) - Decimal(100) / (1 + strength)


@dataclass(frozen=True, slots=True)
class Macd:
    """Moving average convergence/divergence, in basis points of price.

    In basis points rather than price units so the same reading means the same
    thing on BTC at 60,000 and SOL at 200 — the scale-free requirement ADR-011
    §5's cross-asset test depends on.
    """

    line_bps: Decimal
    signal_bps: Decimal

    @property
    def histogram_bps(self) -> Decimal:
        """Line minus signal. Positive is the bullish side of the cross."""
        return self.line_bps - self.signal_bps


def macd(values: Sequence[Decimal]) -> Macd:
    """MACD 12/26 with a 9-period signal, the conventional settings."""
    needed = (MACD_SLOW + MACD_SIGNAL) * SEED_MULTIPLE
    if len(values) < needed:
        raise ValueError(f"need {needed} values for MACD, got {len(values)}")
    price = values[-1]
    # The signal line is an average of past MACD values, so the MACD itself is
    # recomputed at each of the last `MACD_SIGNAL` candles. Each of those uses
    # only candles at or before it.
    history = [
        ema(values[: len(values) - offset], MACD_FAST)
        - ema(values[: len(values) - offset], MACD_SLOW)
        for offset in reversed(range(MACD_SIGNAL * SEED_MULTIPLE))
    ]
    line = history[-1]
    signal = ema(history, MACD_SIGNAL)
    if price <= 0:
        return Macd(line_bps=Decimal(0), signal_bps=Decimal(0))
    return Macd(line_bps=line / price * BPS, signal_bps=signal / price * BPS)


@dataclass(frozen=True, slots=True)
class Bollinger:
    """The 20-period band, and where price sits inside it."""

    middle: Decimal
    upper: Decimal
    lower: Decimal
    price: Decimal

    @property
    def width_bps(self) -> Decimal:
        """Band width as basis points of the middle. A volatility reading."""
        if self.middle <= 0:
            return Decimal(0)
        return (self.upper - self.lower) / self.middle * BPS

    @property
    def position(self) -> Decimal:
        """Where price sits: 0 at the lower band, 1 at the upper, 0.5 at the middle.

        Outside the bands it goes below 0 or above 1 rather than being clamped,
        because "two standard deviations past the band" is the case a reader
        most wants to see and clamping would hide it.
        """
        span = self.upper - self.lower
        if span <= 0:
            return Decimal("0.5")
        return (self.price - self.lower) / span


def bollinger(values: Sequence[Decimal], period: int = BOLLINGER_PERIOD) -> Bollinger:
    """The band, computed with a population standard deviation."""
    if len(values) < period:
        raise ValueError(f"need {period} values for Bollinger bands, got {len(values)}")
    window = values[-period:]
    middle = sma(window, period)
    variance = sum(((value - middle) ** 2 for value in window), Decimal(0)) / period
    deviation = variance.sqrt()
    return Bollinger(
        middle=middle,
        upper=middle + deviation * BOLLINGER_SIGMA,
        lower=middle - deviation * BOLLINGER_SIGMA,
        price=values[-1],
    )


@dataclass(frozen=True, slots=True)
class Reading:
    """Every named indicator at one moment, ready to print or to reason over."""

    price: Decimal
    rsi: Decimal
    macd: Macd
    bollinger: Bollinger
    averages: dict[int, Decimal]

    def distance_to_average_bps(self, period: int) -> Decimal:
        """Price above (+) or below (-) a moving average, in basis points."""
        average = self.averages[period]
        if average <= 0:
            return Decimal(0)
        return (self.price - average) / average * BPS

    @property
    def averages_stacked_up(self) -> bool:
        """20 above 50 above 200: the textbook shape of an uptrend."""
        ordered = [self.averages[period] for period in sorted(self.averages)]
        return all(earlier > later for earlier, later in itertools.pairwise(ordered))

    @property
    def averages_stacked_down(self) -> bool:
        ordered = [self.averages[period] for period in sorted(self.averages)]
        return all(earlier < later for earlier, later in itertools.pairwise(ordered))


def read(closes: Sequence[Decimal]) -> Reading:
    """Every indicator, from a window ending at the candle being judged."""
    needed = warmup_needed()
    if len(closes) < needed:
        raise ValueError(
            f"need {needed} candles for the full indicator set, got {len(closes)}; "
            f"a half-formed indicator is a different indicator"
        )
    return Reading(
        price=closes[-1],
        rsi=rsi(closes),
        macd=macd(closes),
        bollinger=bollinger(closes),
        averages={period: sma(closes, period) for period in MOVING_AVERAGES},
    )
