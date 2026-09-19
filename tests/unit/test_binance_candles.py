"""Binance as a history source.

Same two silent failures as the Hyperliquid fetcher — a capped page that looks
like the end of the range, a still-forming candle that looks closed — plus one
of its own: Binance's close time is the last millisecond of the interval rather
than the first of the next, so a candle that has closed looks a millisecond
short of closed.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from libs.domain.candles import Candle, CandleError, CandleRequest
from libs.exchange.binance.candles import (
    PAGE_LIMIT,
    fetch_candles,
    parse_kline,
    symbol_for,
)

START = datetime(2020, 1, 1, tzinfo=UTC)
HOUR4 = timedelta(hours=4)


def kline(index: int, *, close: str = "200.0") -> list[Any]:
    open_time = START + HOUR4 * index
    close_time = open_time + HOUR4 - timedelta(milliseconds=1)
    return [
        int(open_time.timestamp() * 1000),
        "199.0",
        "205.0",
        "195.0",
        close,
        "1234.5",
        int(close_time.timestamp() * 1000),
        "246000.0",
        4321,
        "600.0",
        "120000.0",
        "0",
    ]


def candle(index: int) -> Candle:
    return parse_kline(kline(index), asset="SOL", interval="4h")


class TestSymbols:
    def test_an_asset_becomes_its_usdt_market(self) -> None:
        assert symbol_for("sol") == "SOLUSDT"
        assert symbol_for("BTC") == "BTCUSDT"


class TestParsing:
    def test_the_close_time_is_the_start_of_the_next_interval(self) -> None:
        """Binance sends the last millisecond; a closed candle must read closed.

        Left as sent, every stored interval would sit one millisecond short of
        its successor, and the hole detector would report a gap between every
        pair of candles in the archive.
        """
        parsed = candle(0)
        assert parsed.close_time == parsed.open_time + HOUR4
        assert candle(1).open_time == parsed.close_time

    def test_prices_are_exact_not_floats(self) -> None:
        parsed = candle(0)
        assert parsed.open == Decimal("199.0")
        assert parsed.volume == Decimal("1234.5")
        assert parsed.trades == 4321

    def test_a_short_row_is_refused(self) -> None:
        """A response shorter than this parser was written against."""
        with pytest.raises(CandleError, match="expected at least"):
            parse_kline(kline(0)[:5], asset="SOL", interval="4h")


def transport(pages: list[list[list[Any]]]) -> httpx.MockTransport:
    remaining = list(pages)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=remaining.pop(0) if remaining else [])

    return httpx.MockTransport(handler)


def fetch(pages: list[list[list[Any]]], *, candles: int) -> tuple[Candle, ...]:
    request = CandleRequest(asset="SOL", interval="4h", start=START, end=START + HOUR4 * candles)

    async def run() -> tuple[Candle, ...]:
        async with httpx.AsyncClient(transport=transport(pages)) as client:
            return await fetch_candles(request, now=START + HOUR4 * (candles + 1), client=client)

    return asyncio.run(run())


class TestFetching:
    def test_a_range_inside_the_cap_is_one_request(self) -> None:
        assert len(fetch([[kline(0), kline(1)]], candles=3)) == 2

    def test_a_range_wider_than_the_cap_is_split(self) -> None:
        """1,000 klines is truncation, not the end of history."""
        first = [kline(index) for index in range(PAGE_LIMIT - 1)]
        second = [kline(PAGE_LIMIT - 1), kline(PAGE_LIMIT)]
        assert len(fetch([first, second], candles=PAGE_LIMIT + 3)) == PAGE_LIMIT + 1

    def test_an_empty_window_does_not_end_the_walk(self) -> None:
        """A period before the symbol was listed is not the end of the range."""
        second = [kline(PAGE_LIMIT - 1), kline(PAGE_LIMIT)]
        assert len(fetch([[], second], candles=PAGE_LIMIT + 3)) == 2

    def test_no_window_ever_asks_for_more_than_the_cap(self) -> None:
        asked: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            params = request.url.params
            span = int(params["endTime"]) - int(params["startTime"])
            asked.append(span)
            return httpx.Response(200, json=[])

        wide = CandleRequest(
            asset="SOL", interval="4h", start=START, end=START + HOUR4 * (PAGE_LIMIT * 3)
        )

        async def run() -> None:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await fetch_candles(wide, now=START + HOUR4 * PAGE_LIMIT * 4, client=client)

        asyncio.run(run())
        assert len(asked) >= 3
        for span in asked:
            assert span / 1000 / (4 * 3600) < PAGE_LIMIT

    def test_an_unknown_symbol_names_itself_in_the_error(self) -> None:
        """A bare 400 does not say which market the venue does not list."""
        request = CandleRequest(asset="NOTACOIN", interval="4h", start=START, end=START + HOUR4 * 3)

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

        async def run() -> tuple[Candle, ...]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await fetch_candles(request, now=START + HOUR4 * 9, client=client)

        with pytest.raises(CandleError, match="NOTACOINUSDT"):
            asyncio.run(run())

    def test_a_still_forming_candle_is_dropped(self) -> None:
        request = CandleRequest(asset="SOL", interval="4h", start=START, end=START + HOUR4 * 3)

        async def run() -> tuple[Candle, ...]:
            async with httpx.AsyncClient(transport=transport([[kline(0), kline(1)]])) as client:
                # Half way through the second candle.
                return await fetch_candles(
                    request, now=START + HOUR4 + timedelta(hours=2), client=client
                )

        kept = asyncio.run(run())
        assert len(kept) == 1
        assert kept[0].open_time == START
