"""Long historical candles from Binance's public klines endpoint.

Read-only and unauthenticated. The endpoint takes no key, accepts no order,
and reaches no capital — the same standing as Hyperliquid's `/info`, and the
only reason this exists is history length.

**Why a second source at all.** Hyperliquid keeps about 5,000 candles per
interval. At 4h that is 833 days, which contains roughly one change of market
regime, and the first rule this project tested failed in one half of that
window and worked in the other on three of four assets. A regime-dependent
rule cannot be judged over a window that holds one regime change; the answer
is more history, and more history makes the test harder rather than easier.

Binance's klines reach back to each symbol's listing — 2017 for BTC, ETH and
BNB, 2020 for SOL — which covers the 2018 bear market, the 2021 run, the 2022
collapse and the recovery. Four regimes instead of one.

**Two shapes of truncation, handled the same way as Hyperliquid's.** The
endpoint caps a response at 1,000 candles and does not treat the cap as an
error. So the range is walked in windows narrower than the cap, computed
arithmetically, which makes truncation impossible and guarantees the walk
progresses whatever comes back. A short window is a hole in the archive, not
the end of history.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

import httpx

from libs.domain.candles import INTERVAL_SECONDS, Candle, CandleError, CandleRequest, closed_only

logger = logging.getLogger(__name__)

KLINES_URL: Final = "https://api.binance.com/api/v3/klines"
"""Public, unauthenticated, read-only. Takes no key and accepts no order."""

VENUE: Final = "binance"

PAGE_LIMIT: Final = 1000
"""The endpoint's per-response cap. Silent, like Hyperliquid's."""

REQUEST_TIMEOUT_SECONDS: Final = 30.0

QUOTE: Final = "USDT"
"""The quote asset these series are denominated in.

USDT rather than USD or a perpetual's mark: it is what has the longest
continuous history on this venue for all four assets. It is not the same
instrument Hyperliquid quotes, which is one more reason the rows carry their
venue and the cost model does not come from here.
"""

# Binance names its intervals the same way this project does, for the ones
# this project uses. Written out rather than assumed, because a silent
# mismatch would return a different interval's candles without failing.
BINANCE_INTERVALS: Final = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


def symbol_for(asset: str) -> str:
    """The venue's name for an asset's market."""
    return f"{asset.upper()}{QUOTE}"


def _decimal(raw: object, *, field: str) -> Decimal:
    """Parse without going through float, so a venue tick stays exact."""
    if not isinstance(raw, str | int):
        raise CandleError(f"kline field {field} is {type(raw).__name__}, expected a number")
    try:
        return Decimal(raw)
    except ArithmeticError as exc:  # pragma: no cover - venue would have to send junk
        raise CandleError(f"kline field {field} is not a number: {raw!r}") from exc


# Binance returns each candle as a positional array rather than an object, so
# the indices are the schema. Named here because a bare `entry[4]` in the
# parser is a number nobody can check against the documentation.
OPEN_TIME, OPEN, HIGH, LOW, CLOSE, VOLUME, CLOSE_TIME = 0, 1, 2, 3, 4, 5, 6
TRADE_COUNT = 8
FIELD_COUNT = 9
"""The shortest response this parser will accept. The endpoint sends twelve
fields; nine is where the ones used here end, and a shorter row means the
response is not what this code was written against."""


def parse_kline(entry: list[Any], *, asset: str, interval: str) -> Candle:
    """Turn one positional kline into a Candle, refusing anything malformed."""
    if len(entry) < FIELD_COUNT:
        raise CandleError(f"kline has {len(entry)} fields, expected at least {FIELD_COUNT}")
    return Candle(
        asset=asset,
        interval=interval,
        open_time=datetime.fromtimestamp(int(entry[OPEN_TIME]) / 1000, tz=UTC),
        # Binance's close time is the last millisecond of the interval rather
        # than the first of the next, so it is one millisecond short. Rounded
        # up, because "has this candle closed" is compared against it and a
        # one-millisecond gap would make every stored interval look incomplete.
        close_time=datetime.fromtimestamp((int(entry[CLOSE_TIME]) + 1) / 1000, tz=UTC),
        open=_decimal(entry[OPEN], field="open"),
        high=_decimal(entry[HIGH], field="high"),
        low=_decimal(entry[LOW], field="low"),
        close=_decimal(entry[CLOSE], field="close"),
        volume=_decimal(entry[VOLUME], field="volume"),
        trades=int(entry[TRADE_COUNT]),
    )


async def fetch_candles(
    request: CandleRequest,
    *,
    now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
    endpoint: str = KLINES_URL,
) -> tuple[Candle, ...]:
    """Every closed candle the request covers, walked in sub-cap windows."""
    if request.interval not in BINANCE_INTERVALS:
        raise CandleError(f"no Binance interval for {request.interval!r}")

    moment = now or datetime.now(tz=UTC)
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    collected: dict[datetime, Candle] = {}
    window = request.step * (PAGE_LIMIT - 1)
    cursor = request.start

    try:
        while cursor < request.end:
            window_end = min(cursor + window, request.end)
            page = await _fetch_page(http, request, start=cursor, end=window_end, endpoint=endpoint)
            for entry in page:
                candle = parse_kline(entry, asset=request.asset, interval=request.interval)
                collected[candle.open_time] = candle
            logger.info(
                "kline window fetched",
                extra={
                    "asset": request.asset,
                    "interval": request.interval,
                    "window_end": window_end.isoformat(),
                    "returned": len(page),
                },
            )
            # Arithmetic advance, so an empty window — a gap in the archive, or
            # a period before the symbol was listed — does not end the walk and
            # cannot loop it either.
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
) -> list[list[Any]]:
    """One klines request, in the venue's own shape."""
    params: dict[str, str | int] = {
        "symbol": symbol_for(request.asset),
        "interval": BINANCE_INTERVALS[request.interval],
        "startTime": int(start.timestamp() * 1000),
        "endTime": int(end.timestamp() * 1000),
        "limit": PAGE_LIMIT,
    }
    response = await client.get(endpoint, params=params)
    if response.status_code == httpx.codes.BAD_REQUEST:
        # The endpoint answers an unknown symbol with 400 and a JSON message.
        # Saying which symbol beats a bare status code, because the likely
        # cause is an asset this venue does not list under that name.
        raise CandleError(
            f"Binance refused {params['symbol']} {params['interval']}: {response.text[:200]}"
        )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise CandleError(f"expected a list of klines, got {type(payload).__name__}")
    return payload


def interval_seconds(interval: str) -> int:
    """Exposed so a caller need not import the domain table separately."""
    return INTERVAL_SECONDS[interval]
