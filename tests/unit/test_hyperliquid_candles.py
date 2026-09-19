"""Downloading historical candles.

The rules worth holding this to are the ones whose failure is silent: a candle
that is still forming looks exactly like a closed one, a truncated page looks
exactly like the end of the range, and a duplicated hour looks exactly like an
hour. Each of those would produce a number that is wrong and plausible.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from libs.exchange.hyperliquid.candles import (
    PAGE_LIMIT,
    Candle,
    CandleError,
    CandleRequest,
    closed_only,
    fetch_candles,
    parse_candle,
)
from services.research.candle_store import as_utc, missing_intervals

START = datetime(2026, 9, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


def venue_candle(index: int, *, close: str = "200.0") -> dict[str, Any]:
    open_time = START + HOUR * index
    return {
        "t": int(open_time.timestamp() * 1000),
        "T": int((open_time + HOUR).timestamp() * 1000),
        "s": "SOL",
        "i": "1h",
        "o": "199.0",
        "h": "205.0",
        "l": "195.0",
        "c": close,
        "v": "12345.5",
        "n": 4321,
    }


def candle(index: int) -> Candle:
    return parse_candle(venue_candle(index), asset="SOL", interval="1h")


class TestParsing:
    def test_prices_are_exact_not_floats(self) -> None:
        """A float cannot hold a venue tick, and the drift compounds silently."""
        parsed = candle(0)
        assert parsed.open == Decimal("199.0")
        assert parsed.volume == Decimal("12345.5")

    def test_a_missing_field_is_refused_not_defaulted(self) -> None:
        """A candle with no high is not a candle with a high of zero."""
        payload = venue_candle(0)
        del payload["h"]
        with pytest.raises(CandleError, match="missing 'h'"):
            parse_candle(payload, asset="SOL", interval="1h")

    def test_range_and_change_are_reported_in_basis_points(self) -> None:
        parsed = candle(0)
        # 205 - 195 on an open of 199 is 502.5 bps.
        assert parsed.range_bps.quantize(Decimal("0.1")) == Decimal("502.5")
        # 200 - 199 on 199 is 50.25 bps.
        assert parsed.change_bps.quantize(Decimal("0.01")) == Decimal("50.25")


class TestClosedOnly:
    def test_a_candle_still_forming_is_dropped(self) -> None:
        """Its high, low and close will change. Using one is lookahead."""
        kept = closed_only([candle(0), candle(1)], now=START + HOUR + timedelta(minutes=30))
        assert len(kept) == 1
        assert kept[0].open_time == START

    def test_a_candle_closing_exactly_now_is_kept(self) -> None:
        kept = closed_only([candle(0)], now=START + HOUR)
        assert len(kept) == 1


class TestRequest:
    def test_an_unknown_interval_is_refused(self) -> None:
        """An '8h' typo must not become a silently accepted eight minutes."""
        with pytest.raises(CandleError, match="unknown interval"):
            CandleRequest(asset="SOL", interval="8h", start=START, end=START + HOUR)

    def test_a_backwards_range_is_refused(self) -> None:
        with pytest.raises(CandleError, match="after its start"):
            CandleRequest(asset="SOL", interval="1h", start=START + HOUR, end=START)


def transport_returning(pages: list[list[dict[str, Any]]]) -> httpx.MockTransport:
    """Serve each page in turn, then empty. Records nothing the test asserts on."""
    remaining = list(pages)

    def handler(_request: httpx.Request) -> httpx.Response:
        page = remaining.pop(0) if remaining else []
        return httpx.Response(200, json=page)

    return httpx.MockTransport(handler)


def fetch(pages: list[list[dict[str, Any]]], *, hours: int = 3) -> tuple[Candle, ...]:
    request = CandleRequest(asset="SOL", interval="1h", start=START, end=START + HOUR * hours)
    now = START + HOUR * (hours + 1)

    async def run() -> tuple[Candle, ...]:
        async with httpx.AsyncClient(transport=transport_returning(pages)) as client:
            return await fetch_candles(request, now=now, client=client)

    return asyncio.run(run())


class TestFetching:
    def test_a_range_inside_the_cap_is_one_request(self) -> None:
        """Three hours needs no windowing, so the walk asks once."""
        assert len(fetch([[venue_candle(0), venue_candle(1)]])) == 2

    def test_a_range_wider_than_the_cap_is_split_into_windows(self) -> None:
        """The cap is silent, so the range is narrowed until it cannot bite."""
        first = [venue_candle(index) for index in range(PAGE_LIMIT - 1)]
        second = [venue_candle(PAGE_LIMIT - 1), venue_candle(PAGE_LIMIT)]
        fetched = fetch([first, second], hours=PAGE_LIMIT + 3)
        assert len(fetched) == PAGE_LIMIT + 1

    def test_an_hour_returned_by_two_windows_is_stored_once(self) -> None:
        """Window edges can overlap, and a duplicated hour corrupts averages."""
        first = [venue_candle(index) for index in range(PAGE_LIMIT - 1)]
        second = [venue_candle(PAGE_LIMIT - 2), venue_candle(PAGE_LIMIT - 1)]
        fetched = fetch([first, second], hours=PAGE_LIMIT + 3)
        assert len({item.open_time for item in fetched}) == len(fetched)

    def test_an_empty_window_does_not_end_the_walk(self) -> None:
        """A hole in the archive is a hole, not the end of history.

        This is the failure the first version shipped with, from the other
        direction: a walk that stops at the first short response silently
        returns part of the range as though it were all of it.
        """
        second = [venue_candle(PAGE_LIMIT - 1), venue_candle(PAGE_LIMIT)]
        fetched = fetch([[], second], hours=PAGE_LIMIT + 3)
        assert len(fetched) == 2

    def test_a_null_response_is_an_empty_range_not_an_error(self) -> None:
        """The venue answers a range it has nothing for with null."""
        request = CandleRequest(asset="SOL", interval="1h", start=START, end=START + HOUR)

        def handler(_request: httpx.Request) -> httpx.Response:
            # A literal JSON null, which is what the venue sends. Passing
            # json=None to httpx produces an empty body instead.
            return httpx.Response(
                200, content=b"null", headers={"content-type": "application/json"}
            )

        async def run() -> tuple[Candle, ...]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await fetch_candles(request, now=START + HOUR * 2, client=client)

        assert asyncio.run(run()) == ()

    def test_no_window_ever_asks_for_more_than_the_cap(self) -> None:
        """The whole point: a request that could be truncated is never sent."""
        asked: list[tuple[int, int]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)["req"]
            asked.append((body["startTime"], body["endTime"]))
            return httpx.Response(200, json=[])

        wide = CandleRequest(
            asset="SOL", interval="1h", start=START, end=START + HOUR * (PAGE_LIMIT * 3)
        )

        async def run() -> None:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await fetch_candles(wide, now=START + HOUR * (PAGE_LIMIT * 4), client=client)

        asyncio.run(run())
        assert len(asked) >= 3
        for window_start, window_end in asked:
            hours = (window_end - window_start) / 1000 / 3600
            assert hours < PAGE_LIMIT


class TestHoles:
    def test_a_gap_in_the_archive_is_declared(self) -> None:
        """A silent hole means the strategy was tested on a market that paused."""
        holes = missing_intervals([candle(0), candle(1), candle(5)], step=HOUR)
        assert holes == ((START + HOUR, START + HOUR * 5),)

    def test_an_unbroken_series_has_none(self) -> None:
        assert missing_intervals([candle(index) for index in range(4)], step=HOUR) == ()


class TestStoredTimestamps:
    """ClickHouse returns these columns naive, and a naive candle crashes.

    It crashed in the report that was written to make a different silence
    visible, which is the usual way: the guard finds the bug the guard was not
    about.
    """

    def test_a_naive_timestamp_is_read_as_utc(self) -> None:
        naive = datetime(2026, 9, 1, 12, 0)
        assert as_utc(naive) == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    def test_an_aware_timestamp_is_not_relabelled(self) -> None:
        """Re-stamping one that already has a zone is the same error, reversed."""
        aware = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        assert as_utc(aware) == aware

    def test_a_stored_candle_can_be_compared_with_now(self) -> None:
        """The operation that failed: an aware/naive comparison."""
        assert as_utc(datetime(2026, 9, 1)) < datetime.now(tz=UTC)
