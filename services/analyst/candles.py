"""OHLCV candles and where they come from.

Two sources: Hyperliquid's own candle history (the market actually traded,
most recent 5,000 candles per request), and Binance kline CSV files from
`data.binance.vision` for longer history. Binance spot is a different market
from a Hyperliquid perp — no funding, different fees — so a backtest on it is
an approximation and says so.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

INTERVALS: Final[dict[str, timedelta]] = {
    "1h": timedelta(hours=1),
    "2h": timedelta(hours=2),
    "4h": timedelta(hours=4),
    "8h": timedelta(hours=8),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
}
HYPERLIQUID_MAX_CANDLES: Final = 5000

MICROSECOND_TIMESTAMP_THRESHOLD: Final = 10**14
"""Binance switched spot kline timestamps from milliseconds to microseconds in
2025. Millisecond timestamps stay below 10^14 until the year 5138."""


class CandleError(ValueError):
    """Candle data is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class Candle:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.open_time.tzinfo is None:
            raise CandleError("candle time must be timezone-aware")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise CandleError(f"non-positive price in candle at {self.open_time}")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise CandleError(f"high/low inconsistent with open/close at {self.open_time}")


def _from_epoch(value: int) -> datetime:
    seconds = value / 1_000_000 if value >= MICROSECOND_TIMESTAMP_THRESHOLD else value / 1_000
    return datetime.fromtimestamp(seconds, tz=UTC)


def validate_series(candles: Sequence[Candle], interval: str) -> list[Candle]:
    """Sorted, de-duplicated candles; refuses gaps rather than silently bridging them.

    A gap would make every lookback in bars mean a different span of time, and
    a backtest across one would enter and exit at prices that never traded.
    """
    step = INTERVALS.get(interval)
    if step is None:
        raise CandleError(f"unsupported interval {interval!r}; use one of {sorted(INTERVALS)}")
    unique = {c.open_time: c for c in candles}
    ordered = [unique[t] for t in sorted(unique)]
    for previous, current in pairwise(ordered):
        if current.open_time - previous.open_time != step:
            raise CandleError(
                f"gap in candles between {previous.open_time:%Y-%m-%d %H:%M} and "
                f"{current.open_time:%Y-%m-%d %H:%M} UTC"
            )
    return ordered


def parse_hyperliquid(rows: Iterable[dict[str, Any]]) -> list[Candle]:
    return [
        Candle(
            open_time=_from_epoch(int(row["t"])),
            open=float(row["o"]),
            high=float(row["h"]),
            low=float(row["l"]),
            close=float(row["c"]),
            volume=float(row["v"]),
        )
        for row in rows
    ]


def load_binance_csv(paths: Iterable[Path]) -> list[Candle]:
    """Binance kline CSVs: open_time, open, high, low, close, volume, ...

    Files from `data.binance.vision` have no header; exports from other tools
    often do. Both are accepted.
    """
    candles: list[Candle] = []
    for path in paths:
        with path.open(newline="") as handle:
            for row in csv.reader(handle):
                if not row or not row[0].strip().isdigit():
                    continue  # header or blank line
                candles.append(
                    Candle(
                        open_time=_from_epoch(int(row[0])),
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                    )
                )
    if not candles:
        raise CandleError("no candles found in the given files")
    return candles


def closed_only(candles: Sequence[Candle], interval: str, now: datetime) -> list[Candle]:
    """Drop the still-forming last candle: a signal on it can change before it closes."""
    step = INTERVALS[interval]
    return [c for c in candles if c.open_time + step <= now]


def fetch_hyperliquid(info: Any, symbol: str, interval: str, *, now: datetime) -> list[Candle]:
    step = INTERVALS[interval]
    start = now - step * HYPERLIQUID_MAX_CANDLES
    rows = info.candles_snapshot(
        symbol, interval, int(start.timestamp() * 1000), int(now.timestamp() * 1000)
    )
    candles = closed_only(parse_hyperliquid(rows), interval, now)
    return validate_series(candles, interval)


def fetch_hyperliquid_funding(
    info: Any, symbol: str, *, start: datetime, end: datetime
) -> dict[datetime, float]:
    """Hourly funding rates, keyed by the hour they were paid.

    The endpoint returns a limited page per call, so it is walked forward
    until it stops returning newer rows.
    """
    rates: dict[datetime, float] = {}
    cursor = int(start.timestamp() * 1000)
    stop = int(end.timestamp() * 1000)
    while cursor < stop:
        page = info.funding_history(symbol, cursor, stop)
        if not page:
            break
        for row in page:
            paid = _from_epoch(int(row["time"])).replace(minute=0, second=0, microsecond=0)
            rates[paid] = float(row["fundingRate"])
        newest = max(int(row["time"]) for row in page)
        if newest < cursor:
            break
        cursor = newest + 1
    return rates
