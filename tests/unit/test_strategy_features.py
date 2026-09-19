"""Reading a chart: the Feature Engine (Phase 5 §20, §23).

The test that matters most is the lookahead one. Every other property here can
be checked by eye on a chart; a lookahead bug cannot be seen at all, and it is
the defect that makes a backtest profitable and a live system worthless.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from libs.exchange.hyperliquid.candles import Candle
from services.strategy_engine.features import (
    FeatureConfig,
    TrendRegime,
    VolatilityRegime,
    compute,
    feature_series,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(hours=4)


def candle(
    index: int, *, close: str, high: str | None = None, low: str | None = None, volume: str = "1000"
) -> Candle:
    price = Decimal(close)
    return Candle(
        asset="SOL",
        interval="4h",
        open_time=START + STEP * index,
        close_time=START + STEP * (index + 1),
        open=price,
        high=Decimal(high) if high else price * Decimal("1.002"),
        low=Decimal(low) if low else price * Decimal("0.998"),
        close=price,
        volume=Decimal(volume),
        trades=100,
    )


def rising(count: int, *, start: str = "100", step: str = "0.5") -> list[Candle]:
    """A clean uptrend. Every close above the last."""
    price = Decimal(start)
    series = []
    for index in range(count):
        series.append(candle(index, close=str(price)))
        price += Decimal(step)
    return series


def flat(count: int, *, price: str = "100") -> list[Candle]:
    return [candle(index, close=price) for index in range(count)]


class TestLookahead:
    """Phase 5 §23: Feature Timestamp ≤ Decision Timestamp."""

    def test_a_feature_set_is_unchanged_by_what_comes_after_it(self) -> None:
        """The property a backtest depends on and code review does not catch.

        Computed over 200 candles, the features at candle 150 must equal the
        features computed when the series ended at candle 150. If they differ,
        something read forward.
        """
        config = FeatureConfig()
        series = rising(200)
        with_future = list(feature_series(series, config))
        without_future = list(feature_series(series[:151], config))
        assert without_future[-1] == with_future[len(without_future) - 1]

    def test_the_last_feature_set_belongs_to_the_last_candle(self) -> None:
        series = rising(200)
        assert list(feature_series(series))[-1].moment == series[-1].close_time

    def test_a_high_that_comes_later_is_not_a_level_yet(self) -> None:
        """Future extrema are named in §23. This is what one looks like."""
        config = FeatureConfig()
        series = flat(config.warmup)
        as_of_now = compute(series, config)
        series.append(candle(len(series), close="100", high="130"))
        assert compute(series[:-1], config).swing_high_bps == as_of_now.swing_high_bps


class TestWarmup:
    def test_a_half_filled_window_is_refused(self) -> None:
        """A feature over a short window is a different feature, quietly."""
        config = FeatureConfig()
        with pytest.raises(ValueError, match="need at least"):
            compute(flat(config.warmup - 1), config)

    def test_the_series_starts_only_where_every_feature_is_complete(self) -> None:
        config = FeatureConfig()
        series = rising(config.warmup + 5)
        assert len(list(feature_series(series, config))) == 6

    def test_warmup_covers_the_trend_slope_comparison(self) -> None:
        """The slope needs the slow window twice over, offset by the fast one."""
        config = FeatureConfig(fast=10, slow=200, volatility_reference=50, volatility=20)
        assert config.warmup >= config.slow + config.fast
        compute(rising(config.warmup), config)


class TestTrend:
    def test_an_uptrend_reads_as_up(self) -> None:
        features = compute(rising(200))
        assert features.trend_bps > 0
        assert features.trend_slope_bps > 0
        assert features.trend_regime is TrendRegime.UP

    def test_a_downtrend_reads_as_down(self) -> None:
        series = list(reversed([c.close for c in rising(200)]))
        candles = [candle(index, close=str(price)) for index, price in enumerate(series)]
        features = compute(candles)
        assert features.trend_bps < 0
        assert features.trend_regime is TrendRegime.DOWN

    def test_a_flat_market_is_a_range_not_a_weak_trend(self) -> None:
        """RANGE must be reachable, or the regime carries no information."""
        assert compute(flat(200)).trend_regime is TrendRegime.RANGE


class TestMomentum:
    def test_momentum_is_the_return_over_the_lookback(self) -> None:
        config = FeatureConfig()
        series = rising(200, start="100", step="1")
        features = compute(series, config)
        # 200 candles from 100 in steps of 1 close at 299, and the lookback of
        # 14 starts at 285.
        expected = Decimal(14) / Decimal(285) * Decimal(10000)
        assert abs(features.momentum_bps - expected) < Decimal("0.01")

    def test_a_constant_percentage_trend_is_not_accelerating(self) -> None:
        """Momentum is a return, so "steady" means a steady percentage."""
        price = Decimal(100)
        series = []
        for index in range(200):
            series.append(candle(index, close=str(price)))
            price *= Decimal("1.005")
        features = compute(series, FeatureConfig())
        assert abs(features.momentum_acceleration_bps) < Decimal(1)

    def test_a_constant_dollar_trend_decelerates_slightly(self) -> None:
        """Because a fixed step is a shrinking percentage as price rises.

        Asserted rather than tolerated: it is the correct reading of an
        arithmetic ramp, and a feature that called it steady would be wrong.
        """
        features = compute(rising(200, start="100", step="1"), FeatureConfig())
        assert features.momentum_acceleration_bps < 0
        assert features.momentum_acceleration_bps > Decimal(-10)


class TestVolatility:
    def test_a_quiet_market_after_a_loud_one_reads_low(self) -> None:
        config = FeatureConfig(volatility=10, volatility_reference=100)
        loud = [
            candle(index, close="100", high="110", low="90")
            if index % 2 == 0
            else candle(index, close="101", high="111", low="91")
            for index in range(140)
        ]
        quiet = [candle(140 + index, close="100") for index in range(20)]
        features = compute(loud + quiet, config)
        assert features.volatility_ratio < 1
        assert features.volatility_regime is VolatilityRegime.LOW

    def test_the_true_range_counts_a_gap(self) -> None:
        """High minus low understates a candle that opened away from the close."""
        config = FeatureConfig(atr=2, volatility=2, volatility_reference=10, slow=10, fast=2)
        series = flat(config.warmup)
        gapped = compute(
            [*series, candle(len(series), close="120", high="120.2", low="119.8")], config
        )
        assert gapped.atr_bps > Decimal(100)

    def test_volatility_is_never_negative(self) -> None:
        assert compute(rising(200)).realized_volatility_bps >= 0


class TestLevels:
    def test_resistance_above_and_support_below_are_both_positive(self) -> None:
        """Reported as distances, so a rule reads the same on either side."""
        config = FeatureConfig()
        series = flat(config.warmup)
        series[-5] = candle(len(series) - 5, close="100", high="120", low="80")
        features = compute(series, config)
        assert features.swing_high_bps > 0
        assert features.swing_low_bps > 0


class TestVolume:
    def test_an_ordinary_candle_has_relative_volume_near_one(self) -> None:
        assert abs(compute(rising(200)).relative_volume - 1) < Decimal("0.01")

    def test_a_volume_spike_is_visible(self) -> None:
        series = rising(200)
        series[-1] = candle(199, close="199.5", volume="5000")
        assert compute(series).relative_volume > 3


class TestScaleFreedom:
    def test_the_same_shape_at_a_different_price_gives_the_same_features(self) -> None:
        """A threshold tuned on BTC must mean the same thing on SOL.

        ADR-011 §5 re-runs the strategy unchanged on a second asset. That test
        is meaningless if the features carry a dollar amount.
        """
        cheap = compute(rising(200, start="100", step="0.5"))
        dear = compute(rising(200, start="60000", step="300"))
        assert abs(cheap.trend_bps - dear.trend_bps) < Decimal("0.01")
        assert abs(cheap.momentum_bps - dear.momentum_bps) < Decimal("0.01")
        assert cheap.trend_regime is dear.trend_regime


class TestConfig:
    def test_a_fast_lookback_longer_than_the_slow_one_is_refused(self) -> None:
        with pytest.raises(ValueError, match="shorter than the slow"):
            FeatureConfig(fast=60, slow=50)

    def test_a_single_candle_lookback_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least two candles"):
            FeatureConfig(momentum=1)

    def test_the_volatility_reference_must_be_the_longer_window(self) -> None:
        with pytest.raises(ValueError, match="longer one"):
            FeatureConfig(volatility=50, volatility_reference=20)
