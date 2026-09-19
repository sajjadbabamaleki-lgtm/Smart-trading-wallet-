"""Downloading historical candles from Hyperliquid.

This is the only part of the system that reaches back before the recorder was
switched on. A trader that reasons about a trend, a level, or how an asset
behaved through the last two cycles cannot get that from our own capture, which
begins when we started it.

**It reads mainnet, and that is deliberate and safe.** `/info` is unsigned and
public: no key is presented, nothing can be submitted through it, and no
capital is reachable. The same reasoning as `MarketDataEnvironment.MAINNET_PUBLIC`
applies here, and for history there is no alternative — testnet price history is
not the history of a real market, so a strategy calibrated on it would be
calibrated on nothing.

**Only closed candles come back.** The candle covering the current interval is
still forming; its high, low and close will change. Handing one to a backtest
means acting on a number that did not exist at the moment of the decision,
which is lookahead. So the venue's most recent candle is dropped unless the
clock says its interval is over.

**The venue caps a response at 5,000 candles**, which is undocumented in the
sense that it is not an error — a request for two years of hours simply returns
the first 5,000 and says nothing. That silence is why this paginates by the
last candle received rather than by arithmetic on the range: a page that comes
back short ends the walk, and a page that comes back full continues it from
where it actually stopped.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import httpx

logger = logging.getLogger(__name__)

MAINNET_INFO_URL: Final = "https://api.hyperliquid.xyz/info"
"""Public, unsigned, read-only. Reaches no capital and accepts no order."""

VENUE: Final = "hyperliquid"

PAGE_LIMIT: Final = 5000
"""The venue's per-response cap. Not an error when exceeded — just truncation."""

REQUEST_TIMEOUT_SECONDS: Final = 30.0
"""Generous, because a 5,000-candle page is a large response and a backfill is
not latency-sensitive. A timeout here costs a retry, not a trade."""

INTERVAL_SECONDS: Final = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}
"""The intervals this project asks for, with their length in seconds.

An explicit table rather than a parser, because the length is needed to decide
whether a candle has closed, and guessing that from a string is how an "8h"
typo becomes a silently accepted eight-minute candle.
"""


class CandleError(RuntimeError):
    """The venue returned something this module will not interpret."""


@dataclass(frozen=True, slots=True)
class Candle:
    """One closed interval, as the venue reported it."""

    asset: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trades: int

    @property
    def interval_seconds(self) -> int:
        return INTERVAL_SECONDS[self.interval]

    @property
    def range_bps(self) -> Decimal:
        """High to low, in basis points of the open.

        The single most useful number for the question this project spent two
        days on from the wrong end: how much movement an interval contains. A
        candle whose range is smaller than the round-trip cost held nothing to
        take, whatever a signal said about it.
        """
        if self.open <= 0:
            return Decimal(0)
        return (self.high - self.low) / self.open * Decimal(10000)

    @property
    def change_bps(self) -> Decimal:
        """Open to close, signed. What a position held for the whole candle made."""
        if self.open <= 0:
            return Decimal(0)
        return (self.close - self.open) / self.open * Decimal(10000)


def _decimal(raw: object, *, field: str) -> Decimal:
    """Parse a venue-supplied number without going through float.

    Hyperliquid sends prices as strings. `Decimal(str)` keeps them exact;
    `Decimal(float(str))` does not, and the error is invisible until it has been
    compounded through a year of candles.
    """
    if not isinstance(raw, str | int):
        raise CandleError(f"candle field {field} is {type(raw).__name__}, expected a number")
    try:
        return Decimal(raw)
    except ArithmeticError as exc:  # pragma: no cover - venue would have to send junk
        raise CandleError(f"candle field {field} is not a number: {raw!r}") from exc


def parse_candle(payload: dict[str, Any], *, asset: str, interval: str) -> Candle:
    """Turn one venue candle into ours, refusing anything malformed.

    Refusing rather than defaulting. A candle with a missing high is not a
    candle with a high of zero, and a zero there would become a 100% drawdown in
    whatever read it next.
    """
    for key in ("t", "T", "o", "h", "l", "c", "v"):
        if key not in payload:
            raise CandleError(f"candle is missing {key!r}: {payload!r}")
    return Candle(
        asset=asset,
        interval=interval,
        open_time=datetime.fromtimestamp(int(payload["t"]) / 1000, tz=UTC),
        close_time=datetime.fromtimestamp(int(payload["T"]) / 1000, tz=UTC),
        open=_decimal(payload["o"], field="o"),
        high=_decimal(payload["h"], field="h"),
        low=_decimal(payload["l"], field="l"),
        close=_decimal(payload["c"], field="c"),
        volume=_decimal(payload["v"], field="v"),
        trades=int(payload.get("n", 0)),
    )


def closed_only(candles: Sequence[Candle], *, now: datetime) -> tuple[Candle, ...]:
    """Drop any candle whose interval has not finished.

    Separated from fetching so it can be tested without a network, and so the
    rule is stated in one place: a candle is usable when its close time has
    passed. Everything else is a number still being written.
    """
    return tuple(candle for candle in candles if candle.close_time <= now)


@dataclass(frozen=True, slots=True)
class CandleRequest:
    """What history to download. Validated on construction.

    A dataclass rather than four parameters, because the four travel together
    through the fetch, the pagination and the store, and a call site that can
    pass them in the wrong order eventually does.
    """

    asset: str
    interval: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.interval not in INTERVAL_SECONDS:
            raise CandleError(
                f"unknown interval {self.interval!r}; this project uses "
                f"{', '.join(sorted(INTERVAL_SECONDS))}"
            )
        if self.end <= self.start:
            raise CandleError("the range end must be after its start")

    @property
    def step(self) -> timedelta:
        return timedelta(seconds=INTERVAL_SECONDS[self.interval])


async def fetch_candles(
    request: CandleRequest,
    *,
    now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
    endpoint: str = MAINNET_INFO_URL,
) -> tuple[Candle, ...]:
    """Every closed candle the request covers.

    Walks forward a page at a time. `now` is injected rather than read here so
    that a test can decide what "closed" means without waiting.
    """
    moment = now or datetime.now(tz=UTC)
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    collected: dict[datetime, Candle] = {}
    cursor = request.start

    try:
        while cursor < request.end:
            page = await _fetch_page(http, request, cursor=cursor, endpoint=endpoint)
            if not page:
                break
            for entry in page:
                candle = parse_candle(entry, asset=request.asset, interval=request.interval)
                # Keyed by open time, so an overlapping page cannot double-count
                # an hour. The venue returns the candle containing the cursor,
                # which means every page after the first repeats the one before.
                collected[candle.open_time] = candle
            newest = max(collected)
            if len(page) < PAGE_LIMIT:
                break
            if newest + request.step <= cursor:
                # The page was full but advanced nothing. Continuing would loop
                # forever; stopping loses data. Say so instead of doing either
                # silently.
                raise CandleError(
                    f"the venue returned a full page that did not advance past "
                    f"{cursor.isoformat()}; the range cannot be walked"
                )
            cursor = newest + request.step
            logger.info(
                "candle page fetched",
                extra={
                    "asset": request.asset,
                    "interval": request.interval,
                    "through": newest.isoformat(),
                },
            )
    finally:
        if owns_client:
            await http.aclose()

    ordered = tuple(collected[key] for key in sorted(collected))
    return closed_only(ordered, now=moment)


async def _fetch_page(
    client: httpx.AsyncClient,
    request: CandleRequest,
    *,
    cursor: datetime,
    endpoint: str,
) -> list[dict[str, Any]]:
    """One `candleSnapshot` request, in the venue's own shape."""
    body = {
        "type": "candleSnapshot",
        "req": {
            "coin": request.asset.upper(),
            "interval": request.interval,
            "startTime": int(cursor.timestamp() * 1000),
            "endTime": int(request.end.timestamp() * 1000),
        },
    }
    response = await client.post(endpoint, json=body)
    response.raise_for_status()
    payload = response.json()
    if payload is None:
        # The venue answers an empty range with null rather than [].
        return []
    if not isinstance(payload, list):
        raise CandleError(f"expected a list of candles, got {type(payload).__name__}")
    return payload
