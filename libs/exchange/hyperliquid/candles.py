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

**The venue caps a response at 5,000 candles, and the cap is silent.** A
request for two years of hourly candles does not fail — it returns 5,000 of
them and says nothing about the rest. Worse, the 5,000 it keeps are the *most
recent*, so the missing part is the beginning of the range, which is exactly
the part a two-year request is asking for.

So the range is walked in windows of fewer than 5,000 intervals each, computed
arithmetically. A truncated response then cannot occur, the venue's truncation
rule stops mattering, and the walk is guaranteed to progress regardless of what
comes back.

**The same 5,000 is also a retention limit, which windowing cannot fix.** With
the walk corrected, the windows covering 2024-09 to 2026-02 came back empty for
both BTC and SOL at 1h: the venue does not hold hourly candles older than about
5,000 hours, or 208 days. At 1d the same two-year request returns everything,
because 5,000 days is thirteen years. Intraday history beyond seven months has
to come from a longer interval — 4h reaches about 833 days — and this is a
property of the source, not of the request.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

import httpx

from libs.domain.candles import (
    Candle,
    CandleError,
    CandleRequest,
    closed_only,
)

logger = logging.getLogger(__name__)

MAINNET_INFO_URL: Final = "https://api.hyperliquid.xyz/info"
"""Public, unsigned, read-only. Reaches no capital and accepts no order."""

VENUE: Final = "hyperliquid"

PAGE_LIMIT: Final = 5000
"""The venue's per-response cap. Not an error when exceeded — just truncation."""

REQUEST_TIMEOUT_SECONDS: Final = 30.0
"""Generous, because a 5,000-candle page is a large response and a backfill is
not latency-sensitive. A timeout here costs a retry, not a trade."""


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


async def fetch_candles(
    request: CandleRequest,
    *,
    now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
    endpoint: str = MAINNET_INFO_URL,
) -> tuple[Candle, ...]:
    """Every closed candle the request covers.

    Walks the range in windows narrow enough that the page cap cannot bite:
    each request asks for at most `PAGE_LIMIT - 1` intervals, so a truncated
    response is impossible and the venue's truncation rule stops mattering.

    That rule is why this is written this way. The first version paged forward
    from the last candle received, on the assumption that a capped response
    keeps the *oldest* candles in the range. Hyperliquid keeps the newest: a
    request for two years of hours returned the most recent 208 days and said
    nothing, and the walk then finished in one page because its cursor had
    already passed the end. Two years of hourly history came back as seven
    months of it, with no error and no gap.

    Windowing by arithmetic removes the assumption instead of replacing it with
    the opposite one. It also guarantees progress — the cursor advances by a
    fixed amount whatever the venue returns — so the walk cannot loop.

    `now` is injected rather than read here so that a test can decide what
    "closed" means without waiting.
    """
    moment = now or datetime.now(tz=UTC)
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    collected: dict[datetime, Candle] = {}
    # One interval short of the cap, because the venue may count both ends of
    # the window inclusively and a page at exactly the cap is indistinguishable
    # from a truncated one.
    window = request.step * (PAGE_LIMIT - 1)
    cursor = request.start

    try:
        while cursor < request.end:
            window_end = min(cursor + window, request.end)
            page = await _fetch_page(http, request, start=cursor, end=window_end, endpoint=endpoint)
            for entry in page:
                candle = parse_candle(entry, asset=request.asset, interval=request.interval)
                # Keyed by open time, so an overlapping window cannot
                # double-count an hour.
                collected[candle.open_time] = candle
            logger.info(
                "candle window fetched",
                extra={
                    "asset": request.asset,
                    "interval": request.interval,
                    "window_end": window_end.isoformat(),
                    "returned": len(page),
                },
            )
            # An empty or short window is not the end of the range — it is a
            # hole in the archive, and `missing_intervals` declares those. The
            # walk continues by arithmetic either way.
            cursor = window_end
    finally:
        if owns_client:
            await http.aclose()

    ordered = tuple(collected[key] for key in sorted(collected))
    return closed_only(ordered, now=moment)


async def _fetch_page(
    client: httpx.AsyncClient,
    request: CandleRequest,
    *,
    start: datetime,
    end: datetime,
    endpoint: str,
) -> list[dict[str, Any]]:
    """One `candleSnapshot` request, in the venue's own shape."""
    body = {
        "type": "candleSnapshot",
        "req": {
            "coin": request.asset.upper(),
            "interval": request.interval,
            "startTime": int(start.timestamp() * 1000),
            "endTime": int(end.timestamp() * 1000),
        },
    }
    response = await client.post(endpoint, json=body)
    response.raise_for_status()
    payload = response.json()
    if payload is None:
        # The venue answers a range it holds nothing for with null, not [].
        return []
    if not isinstance(payload, list):
        raise CandleError(f"expected a list of candles, got {type(payload).__name__}")
    return payload
