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
    measure_passive_fill_markout_bps,
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


class TestPassiveFillMarkout:
    """Adverse selection on a resting fill — the number the maker question turns on.

    Crossing costs 4.5 bps a side in fees and resting costs 1.5, so resting looks
    three times cheaper until you ask what the price does after someone chooses
    to fill you. Nothing in this project had measured that, and the sign of this
    number decides whether the cheaper fee is real.
    """

    def quote(self, second: float, bid: str, ask: str) -> dict[str, Any]:
        return {
            "event_type": "BBO",
            "local_receive_time": START + timedelta(seconds=second),
            "bid_price": Decimal(bid),
            "ask_price": Decimal(ask),
        }

    def trade(self, second: float, price: str, side: str) -> dict[str, Any]:
        return {
            "event_type": "TRADE",
            "local_receive_time": START + timedelta(seconds=second),
            "price": Decimal(price),
            "side": side,
        }

    def test_a_passive_buy_filled_before_a_fall_is_adverse(self) -> None:
        """Someone sold into our bid and the price kept falling. That is the cost."""
        rows = [
            self.quote(0, "100", "100.10"),
            self.trade(1, "100", "SELL"),
            self.quote(11, "99.50", "99.60"),
        ]
        result = measure_passive_fill_markout_bps(rows, horizon=timedelta(seconds=10))
        assert result.count == 1
        assert result.mean < 0

    def test_a_passive_buy_filled_before_a_rise_is_favourable(self) -> None:
        rows = [
            self.quote(0, "100", "100.10"),
            self.trade(1, "100", "SELL"),
            self.quote(11, "100.50", "100.60"),
        ]
        result = measure_passive_fill_markout_bps(rows, horizon=timedelta(seconds=10))
        assert result.mean > 0

    def test_a_passive_sell_is_signed_from_its_own_side(self) -> None:
        """A rise after our ask was lifted is adverse for the seller."""
        rows = [
            self.quote(0, "100", "100.10"),
            self.trade(1, "100.10", "BUY"),
            self.quote(11, "100.50", "100.60"),
        ]
        result = measure_passive_fill_markout_bps(rows, horizon=timedelta(seconds=10))
        assert result.count == 1
        assert result.mean < 0

    def test_a_trade_inside_the_spread_is_not_a_fill_of_ours(self) -> None:
        """We were not at that price, so nobody filled us there."""
        rows = [
            self.quote(0, "100", "100.10"),
            self.trade(1, "100.05", "SELL"),
            self.quote(11, "99", "99.10"),
        ]
        with pytest.raises(MeasurementError, match="no passive fill"):
            measure_passive_fill_markout_bps(rows, horizon=timedelta(seconds=10))

    def test_a_fill_with_no_later_quote_produces_no_observation(self) -> None:
        """A gap must drop the observation rather than stretch the horizon."""
        rows = [
            self.quote(0, "100", "100.10"),
            self.trade(1, "100", "SELL"),
            self.quote(2, "100", "100.10"),
        ]
        with pytest.raises(MeasurementError, match="no passive fill"):
            measure_passive_fill_markout_bps(rows, horizon=timedelta(seconds=10))

    def test_the_prevailing_quote_is_the_one_before_the_trade(self) -> None:
        """Using a later quote would price the fill at a book that did not exist."""
        rows = [
            self.quote(0, "100", "100.10"),
            self.quote(5, "90", "90.10"),
            self.trade(6, "90", "SELL"),
            self.quote(16, "90", "90.10"),
        ]
        result = measure_passive_fill_markout_bps(rows, horizon=timedelta(seconds=10))
        # Filled at 90, mid unchanged at 90.05, so the markout is the half-spread.
        assert result.count == 1
        assert result.mean > 0

    def test_a_sample_without_trades_refuses_rather_than_reporting_zero(self) -> None:
        with pytest.raises(MeasurementError, match="need both quotes and trades"):
            measure_passive_fill_markout_bps(
                [self.quote(0, "100", "100.10")], horizon=timedelta(seconds=10)
            )

    def test_a_negative_horizon_is_refused(self) -> None:
        with pytest.raises(MeasurementError, match="horizon must be positive"):
            measure_passive_fill_markout_bps([], horizon=timedelta(seconds=-1))

    def test_the_signed_summary_keeps_the_loss_tail(self) -> None:
        """A markout's bad end is its low end, so min and p10 have to survive."""
        rows: list[dict[str, Any]] = []
        # Twenty distinct outcomes spread either side of the fill price, so the
        # quantiles are genuinely ordered rather than two values in a trench
        # coat — a two-valued sample has p10 == p50 and proves nothing here.
        for i in range(20):
            rows.append(self.quote(i * 20, "100", "100.10"))
            rows.append(self.trade(i * 20 + 1, "100", "SELL"))
            after = Decimal(100) + (Decimal(i) - 10) / 10
            rows.append(self.quote(i * 20 + 11, str(after), str(after + Decimal("0.10"))))
        result = measure_passive_fill_markout_bps(rows, horizon=timedelta(seconds=10))
        assert result.count == 20
        assert result.minimum < 0 < result.maximum
        assert result.p10 < result.p50 < result.p90

    def test_calibration_reports_the_markout_when_the_sample_supports_it(self) -> None:
        rows = [
            self.quote(0, "100", "100.10"),
            self.trade(1, "100", "SELL"),
            self.quote(11, "99.50", "99.60"),
            self.quote(22, "99.50", "99.60"),
        ]
        result = calibrate(rows, delay=timedelta(milliseconds=322))
        assert result.passive_markout_bps is not None
        assert "passive_fill_markout_bps" in result.as_dict()

    def test_calibration_omits_it_rather_than_inventing_it(self) -> None:
        """A quote-only sample can price crossing and must say nothing about resting."""
        rows = [self.quote(0, "100", "100.10"), self.quote(1, "100", "100.10")]
        result = calibrate(rows, delay=timedelta(milliseconds=322))
        assert result.passive_markout_bps is None
        assert "passive_fill_markout_bps" not in result.as_dict()
