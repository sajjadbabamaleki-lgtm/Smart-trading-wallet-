"""The named indicators, checked against their published definitions.

These exist so a reader can compare the bot's numbers with their own chart.
That only works if the numbers are the standard ones, so the tests here check
them against values computed independently rather than against whatever this
code happens to produce.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.strategy_engine import indicators


def closes(values: list[str]) -> list[Decimal]:
    return [Decimal(value) for value in values]


def ramp(count: int, *, start: str = "100", step: str = "1") -> list[Decimal]:
    price = Decimal(start)
    series = []
    for _ in range(count):
        series.append(price)
        price += Decimal(step)
    return series


class TestSimpleAverage:
    def test_it_averages_the_last_n(self) -> None:
        assert indicators.sma(closes(["1", "2", "3", "4"]), 2) == Decimal("3.5")

    def test_a_short_window_is_refused(self) -> None:
        with pytest.raises(ValueError, match="need 5 values"):
            indicators.sma(closes(["1", "2"]), 5)


class TestExponentialAverage:
    def test_a_flat_series_averages_to_its_level(self) -> None:
        assert indicators.ema([Decimal(100)] * 60, 12) == Decimal(100)

    def test_it_tracks_a_rising_series_below_the_last_price(self) -> None:
        """An average of the past cannot be above a series that only rose."""
        series = ramp(120)
        value = indicators.ema(series, 12)
        assert value < series[-1]
        assert value > series[-13]

    def test_the_bounded_seed_matches_a_full_pass(self) -> None:
        """The optimisation this module documents must not change the answer.

        A true EMA depends on every candle ever; this seeds six spans back. If
        the two disagree materially the optimisation is a bug, so it is
        compared against the unbounded computation directly.
        """
        series = ramp(2000, step="0.7")
        period = 26
        multiplier = Decimal(2) / Decimal(period + 1)
        full = indicators.sma(series[:period], period)
        for value in series[period:]:
            full = (value - full) * multiplier + full
        bounded = indicators.ema(series, period)
        assert abs(bounded - full) / full < Decimal("0.0001")


class TestRsi:
    def test_a_series_that_only_rises_is_pinned_at_a_hundred(self) -> None:
        """No losses at all. A chart shows 100 here rather than dividing by zero."""
        assert indicators.rsi(ramp(120)) == Decimal(100)

    def test_a_series_that_only_falls_is_pinned_at_zero(self) -> None:
        assert indicators.rsi(ramp(120, start="1000", step="-1")) == Decimal(0)

    def test_a_flat_series_is_neutral_rather_than_undefined(self) -> None:
        """No gains and no losses: neither overbought nor oversold."""
        assert indicators.rsi([Decimal(100)] * 120) == Decimal(50)

    def test_equal_gains_and_losses_sit_near_fifty(self) -> None:
        """Near, not at: Wilder smoothing still carries the last change.

        The two phases come out at 51.86 and 48.14 — symmetric about 50 and
        displaced by whichever change happened most recently, which is what
        Wilder's recursion does and what a chart shows.
        """
        up_last = [Decimal(100) + (Decimal(1) if i % 2 else Decimal(0)) for i in range(200)]
        down_last = [Decimal(100) + (Decimal(1) if i % 2 == 0 else Decimal(0)) for i in range(200)]
        rising, falling = indicators.rsi(up_last), indicators.rsi(down_last)
        assert Decimal(50) < rising < Decimal(55)
        assert Decimal(45) < falling < Decimal(50)
        # Symmetric about the midpoint, which is the property that matters.
        assert abs((rising - Decimal(50)) + (falling - Decimal(50))) < Decimal("0.01")

    def test_it_stays_inside_its_range(self) -> None:
        series = [Decimal(100) + Decimal((i * 37) % 23) for i in range(300)]
        value = indicators.rsi(series)
        assert Decimal(0) <= value <= Decimal(100)


class TestMacd:
    def test_a_rising_series_puts_the_line_above_zero(self) -> None:
        """The fast average leads the slow one while price rises."""
        assert indicators.macd(ramp(600)).line_bps > 0

    def test_a_falling_series_puts_it_below(self) -> None:
        assert indicators.macd(ramp(600, start="1000", step="-1")).line_bps < 0

    def test_a_constant_slope_gives_no_histogram_at_all(self) -> None:
        """Surprising, correct, and worth pinning down.

        On a perfectly linear series the gap between the fast and slow averages
        settles to a constant, so the signal — an average of that gap — equals
        it, and the histogram is exactly zero. The histogram measures
        *acceleration*, not direction, and a test that expected a positive
        histogram from a straight line was testing the wrong thing.
        """
        assert indicators.macd(ramp(600)).histogram_bps == 0

    def test_acceleration_is_what_lifts_the_histogram(self) -> None:
        price, step = Decimal(100), Decimal("0.1")
        accelerating = []
        for _ in range(600):
            accelerating.append(price)
            price += step
            step += Decimal("0.002")
        reading = indicators.macd(accelerating)
        assert reading.line_bps > 0
        assert reading.histogram_bps > 0

    def test_a_flat_series_gives_nothing(self) -> None:
        reading = indicators.macd([Decimal(100)] * 600)
        assert reading.line_bps == 0
        assert reading.histogram_bps == 0

    def test_it_is_scale_free(self) -> None:
        """Same shape at 100 and at 60,000 must read the same.

        ADR-011 §5 re-runs a rule unchanged on another asset; an indicator
        carrying a dollar amount would make that test meaningless.
        """
        cheap = indicators.macd(ramp(600, start="100", step="0.5"))
        dear = indicators.macd(ramp(600, start="60000", step="300"))
        assert abs(cheap.line_bps - dear.line_bps) < Decimal("0.01")


class TestBollinger:
    def test_a_flat_series_has_no_width(self) -> None:
        band = indicators.bollinger([Decimal(100)] * 30)
        assert band.upper == band.lower == band.middle
        assert band.width_bps == 0

    def test_the_bands_are_two_deviations_out(self) -> None:
        """Checked against a deviation computed independently."""
        series = closes(["10", "12", "14", "16", "18"] * 4)
        band = indicators.bollinger(series, 20)
        middle = sum(series, Decimal(0)) / 20
        variance = sum(((value - middle) ** 2 for value in series), Decimal(0)) / 20
        assert band.upper == middle + variance.sqrt() * 2
        assert band.lower == middle - variance.sqrt() * 2

    def test_position_is_a_half_at_the_middle(self) -> None:
        band = indicators.Bollinger(
            middle=Decimal(100), upper=Decimal(110), lower=Decimal(90), price=Decimal(100)
        )
        assert band.position == Decimal("0.5")

    def test_position_goes_past_one_outside_the_band(self) -> None:
        """Clamping would hide exactly the case a reader most wants to see."""
        band = indicators.Bollinger(
            middle=Decimal(100), upper=Decimal(110), lower=Decimal(90), price=Decimal(120)
        )
        assert band.position > 1


class TestReading:
    def test_the_full_set_needs_the_stated_warmup(self) -> None:
        with pytest.raises(ValueError, match="need"):
            indicators.read(ramp(indicators.warmup_needed() - 1))

    def test_a_rising_series_stacks_the_averages_up(self) -> None:
        reading = indicators.read(ramp(400))
        assert reading.averages_stacked_up
        assert not reading.averages_stacked_down

    def test_a_falling_series_stacks_them_down(self) -> None:
        reading = indicators.read(ramp(400, start="1000", step="-2"))
        assert reading.averages_stacked_down

    def test_a_flat_series_stacks_neither_way(self) -> None:
        reading = indicators.read([Decimal(100)] * 400)
        assert not reading.averages_stacked_up
        assert not reading.averages_stacked_down

    def test_distance_to_an_average_is_signed(self) -> None:
        reading = indicators.read(ramp(400))
        assert reading.distance_to_average_bps(200) > 0
        assert reading.distance_to_average_bps(20) < reading.distance_to_average_bps(200)
