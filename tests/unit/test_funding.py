"""Funding rates: positioning, and the point-in-time cut that keeps it honest.

The test this file exists for is `test_a_percentile_cannot_see_a_later_payment`.
Funding is the first input here that is not derived from the candle window, so
it is the first one that can leak the future — and the series is short enough
to be tempting to handle as a plain array, which is exactly how that leak gets
written.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from libs.domain.funding import (
    MINIMUM_SAMPLE,
    FundingError,
    FundingHistory,
    FundingRate,
)
from libs.exchange.binance.funding import PAGE_LIMIT, fetch_funding, parse_funding

START = datetime(2024, 1, 1, tzinfo=UTC)
EIGHT_HOURS = timedelta(hours=8)


def rate(index: int, *, value: str) -> FundingRate:
    return FundingRate(asset="SOL", moment=START + EIGHT_HOURS * index, rate=Decimal(value))


def history(values: list[str]) -> FundingHistory:
    return FundingHistory.build([rate(index, value=value) for index, value in enumerate(values)])


class TestRate:
    def test_a_rate_is_reported_in_basis_points(self) -> None:
        assert rate(0, value="0.0001").rate_bps == Decimal(1)

    def test_the_annualised_figure_is_the_one_a_person_can_judge(self) -> None:
        """0.01% per settlement, three a day, is about 11% a year."""
        annual = rate(0, value="0.0001").annualised_pct
        assert Decimal(10) < annual < Decimal(12)


class TestHistory:
    def test_it_sorts_records_given_in_any_order(self) -> None:
        built = FundingHistory.build([rate(2, value="0.1"), rate(0, value="0.3")])
        assert built.moments == (START, START + EIGHT_HOURS * 2)

    def test_an_unsorted_construction_is_refused(self) -> None:
        """Built directly rather than through `build`, a cut would include the future."""
        with pytest.raises(FundingError, match="not in time order"):
            FundingHistory(
                asset="SOL",
                moments=(START + EIGHT_HOURS, START),
                rates=(Decimal(1), Decimal(2)),
            )

    def test_mismatched_lengths_are_refused(self) -> None:
        with pytest.raises(FundingError, match="one rate per moment"):
            FundingHistory(asset="SOL", moments=(START,), rates=())

    def test_an_empty_history_is_refused(self) -> None:
        with pytest.raises(FundingError, match="no payments"):
            FundingHistory.build([])


class TestPointInTime:
    def test_a_percentile_cannot_see_a_later_payment(self) -> None:
        """The leak this module is written to make impossible.

        The series rises steadily, so the latest known rate is always the
        highest so far. Asked as of the middle of sixty payments, a correct
        implementation ranks it against the thirty that had settled and returns
        about 0.98 — mid-rank keeps it just under 1. An implementation that
        could see the whole array would rank payment thirty of sixty and return
        about 0.49. The two answers are far enough apart that this test cannot
        pass by accident.
        """
        rising = history([str(Decimal(index) / 10000) for index in range(1, 61)])
        midpoint = START + EIGHT_HOURS * 29
        percentile = rising.percentile_at(midpoint, window=timedelta(days=365))
        assert percentile is not None
        assert percentile > Decimal("0.95")

    def test_the_same_series_read_at_the_end_agrees_with_reading_it_early(self) -> None:
        """A reading must not change because more data arrived afterwards.

        The property a backtest depends on: the percentile computed at candle
        thirty over the full series equals the one computed when the series
        ended at thirty.
        """
        values = [str(Decimal((index * 7) % 23) / 10000) for index in range(1, 61)]
        moment = START + EIGHT_HOURS * 29
        window = timedelta(days=365)
        full = history(values).percentile_at(moment, window=window)
        truncated = history(values[:30]).percentile_at(moment, window=window)
        assert full == truncated

    def test_the_latest_known_rate_stops_at_the_moment_asked(self) -> None:
        series = history(["0.001", "0.002", "0.003", "0.004"])
        assert series.latest_at(START + EIGHT_HOURS) == Decimal("0.002")
        assert series.latest_at(START + EIGHT_HOURS * 3) == Decimal("0.004")

    def test_before_the_first_payment_there_is_nothing(self) -> None:
        series = history(["0.001", "0.002"])
        assert series.latest_at(START - EIGHT_HOURS) is None
        assert series.percentile_at(START - EIGHT_HOURS) is None

    def test_a_settlement_exactly_at_the_moment_counts(self) -> None:
        """A payment that settled at the close was known at the close."""
        series = history(["0.001", "0.002"])
        assert series.latest_at(START) == Decimal("0.001")

    def test_only_the_window_is_considered(self) -> None:
        """A crowded month last year must not make this month look normal."""
        values = ["0.01"] * 40 + ["0.001"] * 40
        series = history(values)
        asked = START + EIGHT_HOURS * 79
        # Over the last thirty days only the low rates are in range, and they
        # are all equal, so the reading is mid-rank rather than an extreme.
        assert series.percentile_at(asked, window=timedelta(days=10)) == Decimal("0.5")

    def test_a_small_sample_reports_nothing_rather_than_a_number(self) -> None:
        series = history(["0.001"] * (MINIMUM_SAMPLE - 1))
        latest = START + EIGHT_HOURS * (MINIMUM_SAMPLE - 2)
        assert series.percentile_at(latest, window=timedelta(days=365)) is None

    def test_ties_sit_in_the_middle_not_at_an_extreme(self) -> None:
        """Otherwise a flat stretch reads as maximally crowded by accident."""
        series = history(["0.001"] * 40)
        asked = START + EIGHT_HOURS * 39
        assert series.percentile_at(asked, window=timedelta(days=365)) == Decimal("0.5")

    def test_the_highest_rate_of_the_window_reads_as_crowded(self) -> None:
        series = history(["0.001"] * 39 + ["0.05"])
        asked = START + EIGHT_HOURS * 39
        percentile = series.percentile_at(asked, window=timedelta(days=365))
        assert percentile is not None
        assert percentile > Decimal("0.95")


def record(index: int, *, value: str = "0.0001") -> dict[str, Any]:
    moment = START + EIGHT_HOURS * index
    return {
        "symbol": "SOLUSDT",
        "fundingTime": int(moment.timestamp() * 1000),
        "fundingRate": value,
        "markPrice": "200.5",
    }


class TestParsing:
    def test_a_rate_is_exact_not_a_float(self) -> None:
        """A small fraction times a large notional is where float error becomes money."""
        parsed = parse_funding(record(0, value="0.00012345"), asset="SOL")
        assert parsed.rate == Decimal("0.00012345")

    def test_a_missing_rate_is_refused(self) -> None:
        payload = record(0)
        del payload["fundingRate"]
        with pytest.raises(FundingError, match="missing 'fundingRate'"):
            parse_funding(payload, asset="SOL")

    def test_an_absent_mark_price_stays_absent(self) -> None:
        payload = record(0)
        payload["markPrice"] = ""
        assert parse_funding(payload, asset="SOL").mark_price is None


def transport(pages: list[list[dict[str, Any]]]) -> httpx.MockTransport:
    remaining = list(pages)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=remaining.pop(0) if remaining else [])

    return httpx.MockTransport(handler)


def fetch(pages: list[list[dict[str, Any]]]) -> tuple[FundingRate, ...]:
    async def run() -> tuple[FundingRate, ...]:
        async with httpx.AsyncClient(transport=transport(pages)) as client:
            return await fetch_funding(
                asset="SOL", start=START, end=START + timedelta(days=3000), client=client
            )

    return asyncio.run(run())


class TestFetching:
    def test_a_short_page_ends_the_walk(self) -> None:
        assert len(fetch([[record(0), record(1)]])) == 2

    def test_a_full_page_is_followed_by_another_request(self) -> None:
        first = [record(index) for index in range(PAGE_LIMIT)]
        second = [record(PAGE_LIMIT), record(PAGE_LIMIT + 1)]
        assert len(fetch([first, second])) == PAGE_LIMIT + 2

    def test_a_settlement_repeated_across_pages_is_stored_once(self) -> None:
        first = [record(index) for index in range(PAGE_LIMIT)]
        second = [record(PAGE_LIMIT - 1), record(PAGE_LIMIT)]
        fetched = fetch([first, second])
        assert len({entry.moment for entry in fetched}) == len(fetched)

    def test_a_full_page_that_does_not_advance_is_refused(self) -> None:
        """Otherwise the walk spins forever on a changing funding schedule."""
        page = [record(0) for _ in range(PAGE_LIMIT)]
        with pytest.raises(FundingError, match="did not advance"):
            fetch([page, page])

    def test_a_refused_symbol_says_which_one(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

        async def run() -> tuple[FundingRate, ...]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await fetch_funding(
                    asset="NOTACOIN", start=START, end=START + EIGHT_HOURS, client=client
                )

        with pytest.raises(FundingError, match="NOTACOIN"):
            asyncio.run(run())

    def test_a_backwards_range_is_refused(self) -> None:
        async def run() -> tuple[FundingRate, ...]:
            return await fetch_funding(asset="SOL", start=START, end=START - EIGHT_HOURS)

        with pytest.raises(FundingError, match="after its start"):
            asyncio.run(run())
