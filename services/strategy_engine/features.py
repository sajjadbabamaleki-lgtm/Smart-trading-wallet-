"""Reading a chart, as Phase 5 §20 defines it.

The Feature Engine's job is to turn a price series into the things a trader
actually looks at — where the trend is, how fast price is moving, how much it
is moving, whether volume is unusual, which regime the market is in, and where
the nearest level sits. Phase 5 §20 names the families: Price, Trend, Momentum,
Volatility, Volume, Regime. This computes them.

**Lookahead is structurally impossible here, not merely avoided.** Phase 5 §23
requires `Feature Timestamp ≤ Decision Timestamp` and explicitly rejects
centered windows, future normalization, future regime labels and future
extrema. So `compute` is handed a window of candles ending at the current one
and is given no way to reach anything later: there is no series to index into,
no length to look past, and no `iloc[i+1]` to write by accident. The caller
that builds the windows is `feature_series`, twelve lines below, and it is the
only place the boundary is decided.

That design costs something and the cost is worth naming: recomputing each
window is slower than one vectorised pass over a dataframe. On two years of 4h
candles it is a few thousand windows and takes under a second, and it buys the
one guarantee that makes the backtest mean anything. Phase 5 §23's list of
rejected practices is a list of things a vectorised pass does by default.

**Every output is scale-free.** Prices are in dollars and a threshold tuned on
BTC at 60,000 is meaningless on SOL at 200. Features are therefore in basis
points of the current price, or ratios, so the same rule can be applied to both
assets — which is the out-of-sample check ADR-011 §5 is built around, and it
does not work if the rule has a dollar amount in it.

**Nothing here is a signal.** These are descriptions. Turning them into LONG,
SHORT or nothing is a separate decision, in a separate module, so that the
description can be tested for correctness and the decision for profitability.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final

from libs.exchange.hyperliquid.candles import Candle

BPS: Final = Decimal(10000)


class TrendRegime(StrEnum):
    """Which way the market is leaning, or that it is not leaning.

    RANGE is a first-class answer rather than a gap between UP and DOWN. A
    trend-following rule applied in a range is the classic way to lose money
    slowly, and the only defence is for "no trend" to be something the engine
    can say.
    """

    UP = "UP"
    DOWN = "DOWN"
    RANGE = "RANGE"


class VolatilityRegime(StrEnum):
    """How much the market is moving now, relative to its own recent normal.

    Relative to itself, never to a fixed number. BTC's quiet week and SOL's
    quiet week are different absolute figures, and a constant here would encode
    one asset's past as the other's definition of calm.
    """

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


MINIMUM_LOOKBACK: Final = 2
"""A lookback of one candle is not a lookback; it is the candle itself."""


@dataclass(frozen=True, slots=True)
class FeatureConfig:
    """Lookback lengths, in candles.

    Defaults are the conventional ones — 20/50 for trend, 14 for momentum and
    ATR — chosen because they are conventional and therefore not chosen to fit
    this data. Phase 4's overfitting gates exist for the moment these start
    being tuned, and a value that was searched for is a value that has to be
    declared as searched for.
    """

    fast: int = 20
    slow: int = 50
    momentum: int = 14
    atr: int = 14
    volatility: int = 20
    volatility_reference: int = 100
    volume: int = 20
    swing: int = 20

    def __post_init__(self) -> None:
        for name in ("fast", "slow", "momentum", "atr", "volatility", "volume", "swing"):
            if getattr(self, name) < MINIMUM_LOOKBACK:
                raise ValueError(f"{name} must span at least two candles")
        if self.fast >= self.slow:
            raise ValueError("the fast lookback must be shorter than the slow one")
        if self.volatility_reference <= self.volatility:
            raise ValueError("the volatility reference window must be the longer one")

    @property
    def warmup(self) -> int:
        """Candles needed before the first complete feature set exists.

        Stated rather than discovered. A feature computed on a half-filled
        window is a different feature, and silently emitting a few of those at
        the start of a backtest biases exactly the period a strategy is
        calibrated on.
        """
        return max(
            # The trend slope compares the slow average with the slow average
            # one fast-lookback ago, so it needs both windows behind it.
            self.slow + self.fast,
            self.momentum + 1,
            self.atr + 1,
            self.volatility_reference + 1,
            self.volume,
            self.swing,
        )


@dataclass(frozen=True, slots=True)
class FeatureSet:
    """What the chart says at one moment, in scale-free terms.

    `moment` is the close time of the last candle used, which is the earliest
    time this information existed. A decision taken on it executes no earlier
    than the next candle's open, and `feature_series` is what guarantees that.
    """

    moment: datetime
    close: Decimal

    # Trend
    trend_bps: Decimal
    """Fast average above (+) or below (-) the slow one, in bps of price."""
    trend_slope_bps: Decimal
    """Change in the slow average over the fast lookback, in bps. Direction."""
    distance_from_trend_bps: Decimal
    """Price above (+) or below (-) the slow average. How stretched it is."""

    # Momentum
    momentum_bps: Decimal
    """Return over the momentum lookback, signed."""
    momentum_acceleration_bps: Decimal
    """Recent half of the lookback minus the earlier half. Is it building."""

    # Volatility
    atr_bps: Decimal
    """Average true range, in bps of price. Gap-aware, unlike high minus low."""
    realized_volatility_bps: Decimal
    """Root mean square candle return over the volatility window."""
    volatility_ratio: Decimal
    """Recent volatility over its longer-run reference. 1.0 is normal."""

    # Volume
    relative_volume: Decimal
    """This candle's volume over the window mean. Participation, not price."""

    # Levels
    swing_high_bps: Decimal
    """Distance up to the highest high in the swing window, in bps. Resistance."""
    swing_low_bps: Decimal
    """Distance down to the lowest low in the swing window, in bps. Support."""

    # Regime
    trend_regime: TrendRegime
    volatility_regime: VolatilityRegime

    def describe(self) -> dict[str, object]:
        """A form a research note or a log line can carry without re-deriving."""
        return {
            "moment": self.moment.isoformat(),
            "close": str(self.close),
            "trend_bps": str(self.trend_bps),
            "trend_slope_bps": str(self.trend_slope_bps),
            "distance_from_trend_bps": str(self.distance_from_trend_bps),
            "momentum_bps": str(self.momentum_bps),
            "momentum_acceleration_bps": str(self.momentum_acceleration_bps),
            "atr_bps": str(self.atr_bps),
            "realized_volatility_bps": str(self.realized_volatility_bps),
            "volatility_ratio": str(self.volatility_ratio),
            "relative_volume": str(self.relative_volume),
            "swing_high_bps": str(self.swing_high_bps),
            "swing_low_bps": str(self.swing_low_bps),
            "trend_regime": self.trend_regime.value,
            "volatility_regime": self.volatility_regime.value,
        }


HIGH_VOLATILITY_RATIO: Final = Decimal("1.25")
LOW_VOLATILITY_RATIO: Final = Decimal("0.75")
"""Where "unusually busy" and "unusually quiet" begin, as ratios to the
reference window. Wide enough that ordinary variation does not flip the label
every candle, which would make the regime a source of noise rather than a
description of one.
"""

TREND_REGIME_THRESHOLD_BPS: Final = Decimal(10)
"""How far apart the averages must be before a trend is claimed.

Zero would make RANGE unreachable: two moving averages are never exactly
equal, so every candle would be UP or DOWN and the regime would carry no
information at all.
"""


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / len(values)


def _relative_bps(value: Decimal, *, reference: Decimal) -> Decimal:
    """`value` as basis points of `reference`, guarding a zero reference."""
    if reference <= 0:
        return Decimal(0)
    return value / reference * BPS


def _true_range(candle: Candle, previous_close: Decimal) -> Decimal:
    """The candle's range, counting the gap from the previous close.

    High minus low alone understates a candle that opened away from where the
    last one closed, and an ATR that understates gaps understates risk exactly
    where risk lives.
    """
    return max(
        candle.high - candle.low,
        abs(candle.high - previous_close),
        abs(candle.low - previous_close),
    )


def _trend(window: Sequence[Candle], config: FeatureConfig) -> tuple[Decimal, Decimal, Decimal]:
    closes = [candle.close for candle in window]
    price = closes[-1]
    fast = _mean(closes[-config.fast :])
    slow = _mean(closes[-config.slow :])
    earlier_slow = _mean(closes[-config.slow - config.fast : -config.fast])
    return (
        _relative_bps(fast - slow, reference=price),
        _relative_bps(slow - earlier_slow, reference=price),
        _relative_bps(price - slow, reference=price),
    )


def _momentum(window: Sequence[Candle], config: FeatureConfig) -> tuple[Decimal, Decimal]:
    closes = [candle.close for candle in window]
    price = closes[-1]
    past = closes[-config.momentum - 1]
    total = _relative_bps(price - past, reference=past)
    half = config.momentum // 2
    midpoint = closes[-half - 1]
    recent = _relative_bps(price - midpoint, reference=midpoint)
    earlier = _relative_bps(midpoint - past, reference=past)
    return total, recent - earlier


def _volatility(
    window: Sequence[Candle], config: FeatureConfig
) -> tuple[Decimal, Decimal, Decimal]:
    price = window[-1].close
    ranges = [
        _true_range(window[index], window[index - 1].close)
        for index in range(len(window) - config.atr, len(window))
    ]
    atr = _relative_bps(_mean(ranges), reference=price)
    recent = _rms_return(window, config.volatility)
    reference = _rms_return(window, config.volatility_reference)
    ratio = recent / reference if reference > 0 else Decimal(1)
    return atr, recent, ratio


def _rms_return(window: Sequence[Candle], length: int) -> Decimal:
    """Root mean square candle return over the last `length` candles, in bps.

    Root mean square rather than standard deviation of returns: the mean return
    over a short window is noise, and subtracting it makes the measure of
    movement depend on the direction of that noise. What is wanted here is the
    typical size of a move, which is what this is.
    """
    squares: list[Decimal] = []
    for index in range(len(window) - length, len(window)):
        previous = window[index - 1].close
        moved = _relative_bps(window[index].close - previous, reference=previous)
        squares.append(moved * moved)
    return _mean(squares).sqrt()


def _levels(window: Sequence[Candle], config: FeatureConfig) -> tuple[Decimal, Decimal]:
    """Distance to the nearest swing high and low, both reported positive.

    Past extrema only. Phase 5 §23 names future extrema among the practices
    that must be rejected, and they are the easiest lookahead to introduce by
    accident: a "recent high" computed over a window that includes what came
    next is a level nobody could have drawn at the time.
    """
    recent = window[-config.swing :]
    price = window[-1].close
    highest = max(candle.high for candle in recent)
    lowest = min(candle.low for candle in recent)
    return (
        _relative_bps(highest - price, reference=price),
        _relative_bps(price - lowest, reference=price),
    )


def _regimes(
    *, trend_bps: Decimal, trend_slope_bps: Decimal, volatility_ratio: Decimal
) -> tuple[TrendRegime, VolatilityRegime]:
    """Label the regime from what is already known, with no new lookback.

    Both labels come from features computed on the same window, so neither can
    reach past it. Phase 5 §23 rejects future regime labels specifically, and
    the way one gets written is by labelling a period from how it turned out.
    """
    if trend_bps > TREND_REGIME_THRESHOLD_BPS and trend_slope_bps > 0:
        trend = TrendRegime.UP
    elif trend_bps < -TREND_REGIME_THRESHOLD_BPS and trend_slope_bps < 0:
        trend = TrendRegime.DOWN
    else:
        trend = TrendRegime.RANGE

    if volatility_ratio >= HIGH_VOLATILITY_RATIO:
        volatility = VolatilityRegime.HIGH
    elif volatility_ratio <= LOW_VOLATILITY_RATIO:
        volatility = VolatilityRegime.LOW
    else:
        volatility = VolatilityRegime.NORMAL
    return trend, volatility


def compute(window: Sequence[Candle], config: FeatureConfig | None = None) -> FeatureSet:
    """Read the chart as of the last candle in `window`.

    The window is history: it ends at the candle being decided on and contains
    nothing after it. That is the whole lookahead guarantee, and it is enforced
    by this function having no access to anything else.
    """
    resolved = config or FeatureConfig()
    if len(window) < resolved.warmup:
        raise ValueError(
            f"need at least {resolved.warmup} candles to compute features, got {len(window)}; "
            f"a feature over a half-filled window is a different feature"
        )

    current = window[-1]
    trend_bps, trend_slope_bps, distance_bps = _trend(window, resolved)
    momentum_bps, acceleration_bps = _momentum(window, resolved)
    atr_bps, realized_bps, ratio = _volatility(window, resolved)
    high_bps, low_bps = _levels(window, resolved)
    volumes = [candle.volume for candle in window[-resolved.volume :]]
    mean_volume = _mean(volumes)
    trend_regime, volatility_regime = _regimes(
        trend_bps=trend_bps, trend_slope_bps=trend_slope_bps, volatility_ratio=ratio
    )

    return FeatureSet(
        moment=current.close_time,
        close=current.close,
        trend_bps=trend_bps,
        trend_slope_bps=trend_slope_bps,
        distance_from_trend_bps=distance_bps,
        momentum_bps=momentum_bps,
        momentum_acceleration_bps=acceleration_bps,
        atr_bps=atr_bps,
        realized_volatility_bps=realized_bps,
        volatility_ratio=ratio,
        relative_volume=(current.volume / mean_volume if mean_volume > 0 else Decimal(1)),
        swing_high_bps=high_bps,
        swing_low_bps=low_bps,
        trend_regime=trend_regime,
        volatility_regime=volatility_regime,
    )


def feature_series(
    candles: Sequence[Candle], config: FeatureConfig | None = None
) -> Iterator[FeatureSet]:
    """Features for every candle that has enough history behind it.

    The only place the window boundary is decided, and therefore the only place
    a lookahead bug could live. `candles[: index + 1]` includes the candle being
    decided on and nothing after it; `compute` cannot widen that, because it is
    not given the series.
    """
    resolved = config or FeatureConfig()
    for index in range(resolved.warmup - 1, len(candles)):
        yield compute(candles[: index + 1], resolved)
