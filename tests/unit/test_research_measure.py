"""Measuring cost inputs from recorded quotes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from services.research.measure import (
    MeasurementError,
    calibrate,
    measure_half_spread_bps,
    measure_mid_move_bps,
)

START = datetime(2026, 9, 14, 21, 0, tzinfo=UTC)


def quote(
    offset_ms: int,
    *,
    bid: str = "59999.5",
    ask: str = "60000.5",
) -> dict[str, Any]:
    return {
        "event_type": "BBO",
        "local_receive_time": START + timedelta(milliseconds=offset_ms),
        "bid_price": Decimal(bid),
        "ask_price": Decimal(ask),
    }


def trade(offset_ms: int) -> dict[str, Any]:
    return {
        "event_type": "TRADE",
        "local_receive_time": START + timedelta(milliseconds=offset_ms),
        "bid_price": None,
        "ask_price": None,
        "price": Decimal(60000),
    }


class TestHalfSpread:
    def test_a_one_dollar_spread_on_sixty_thousand(self) -> None:
        """1 wide on 60000 mid is 0.833 bps of spread, so 0.0833 each way."""
        measured = measure_half_spread_bps([quote(0)])
        assert measured.count == 1
        assert measured.p50.quantize(Decimal("0.0001")) == Decimal("0.0833")

    def test_the_distribution_is_carried_not_the_mean(self) -> None:
        """Spreads widen exactly when a strategy most wants to trade."""
        rows = [quote(i, bid="59999.5", ask="60000.5") for i in range(99)]
        rows.append(quote(99, bid="59990", ask="60010"))
        measured = measure_half_spread_bps(rows)
        assert measured.p99 > measured.p50 * 10

    def test_trades_alone_cannot_measure_a_spread(self) -> None:
        with pytest.raises(MeasurementError, match="BBO or L2_SNAPSHOT"):
            measure_half_spread_bps([trade(0), trade(10)])

    def test_an_empty_range_says_so_rather_than_blaming_the_row_types(self) -> None:
        """An empty range and a range of trades share a symptom, not a cause."""
        with pytest.raises(MeasurementError, match="sample is empty"):
            measure_half_spread_bps([])

    def test_an_empty_range_says_so_for_mid_movement_too(self) -> None:
        with pytest.raises(MeasurementError, match="sample is empty"):
            measure_mid_move_bps([], delay=timedelta(milliseconds=322))

    def test_a_one_sided_quote_is_skipped_not_filled_in(self) -> None:
        """Inventing the missing side would put a fabricated number in a cost model."""
        one_sided = quote(0)
        one_sided["bid_price"] = None
        measured = measure_half_spread_bps([one_sided, quote(10)])
        assert measured.count == 1

    def test_a_crossed_book_is_not_a_negative_spread(self) -> None:
        measured = measure_half_spread_bps([quote(0, bid="60001", ask="60000"), quote(10)])
        assert measured.count == 1
        assert measured.p50 > 0


class TestMidMove:
    def test_a_move_over_the_delay_is_measured(self) -> None:
        rows = [quote(0), quote(400, bid="60059.5", ask="60060.5")]
        measured = measure_mid_move_bps(rows, delay=timedelta(milliseconds=322))
        assert measured.count == 1
        assert measured.p50.quantize(Decimal("0.1")) == Decimal("10.0")

    def test_the_magnitude_is_unsigned(self) -> None:
        """Direction is meaningless without a position; this measures scale."""
        up = [quote(0), quote(400, bid="60059.5", ask="60060.5")]
        down = [quote(0), quote(400, bid="59939.5", ask="59940.5")]
        delay = timedelta(milliseconds=322)
        assert (
            measure_mid_move_bps(up, delay=delay).p50 == measure_mid_move_bps(down, delay=delay).p50
        )

    def test_a_sample_shorter_than_the_delay_measures_nothing(self) -> None:
        with pytest.raises(MeasurementError, match="shorter than the delay"):
            measure_mid_move_bps([quote(0), quote(50)], delay=timedelta(seconds=10))

    def test_a_negative_delay_is_refused(self) -> None:
        with pytest.raises(MeasurementError, match="must be positive"):
            measure_mid_move_bps([quote(0)], delay=timedelta(milliseconds=-1))

    def test_pairing_takes_the_first_quote_past_the_delay(self) -> None:
        """A gap must not silently stretch into a longer-horizon observation."""
        rows = [quote(0), quote(100), quote(350, bid="60005.5", ask="60006.5")]
        measured = measure_mid_move_bps(rows, delay=timedelta(milliseconds=200))
        assert measured.count >= 1


class TestCalibration:
    def test_both_quantities_come_from_one_sample(self) -> None:
        rows = [quote(i * 100) for i in range(20)]
        result = calibrate(rows, delay=timedelta(milliseconds=322))
        assert result.half_spread_bps.count == 20
        assert result.mid_move_bps.count > 0
        assert result.sample_rows == 20

    def test_the_headline_states_both_medians(self) -> None:
        rows = [quote(i * 100) for i in range(20)]
        headline = calibrate(rows, delay=timedelta(milliseconds=322)).headline
        assert "half-spread" in headline
        assert "322 ms" in headline
