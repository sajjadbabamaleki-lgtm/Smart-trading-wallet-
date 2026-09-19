"""Funding-rate history from Binance's public futures endpoint.

Read-only, unauthenticated, no key. Same standing as the klines endpoint and
the same reason for existing: years of history, which the venue this project
trades does not retain.

**Why funding and not more indicators.** Everything in `indicators.py` is a
transformation of the same public price series, so everyone who wants it has
it and it is priced in. Funding is not a transformation of price — it is what
the two sides of the market are paying each other to hold their positions. It
is the only input this project has that describes *positioning* rather than
*pattern*.

**Pagination walks by the last record, not by arithmetic.** The klines fetcher
does the opposite, and the difference is deliberate: Binance has changed some
symbols from eight-hour funding to four-hour and one-hour since 2023, so the
interval is not a constant to compute windows from. Walking by the last
settlement handles a changing schedule; a no-progress guard stops it looping
if the venue ever returns a page that does not advance.

**Open interest is deliberately absent.** Binance retains only about thirty
days of open-interest history, so it cannot be backtested over six years and
would have to be collected forward. Adding it here would put a column in the
store that looks like the others and silently covers a month.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import httpx

from libs.domain.funding import FundingError, FundingRate
from libs.exchange.binance.candles import QUOTE, symbol_for

logger = logging.getLogger(__name__)

FUNDING_URL: Final = "https://fapi.binance.com/fapi/v1/fundingRate"
"""Public, unauthenticated, read-only. Takes no key and accepts no order."""

VENUE: Final = "binance"

PAGE_LIMIT: Final = 1000
REQUEST_TIMEOUT_SECONDS: Final = 30.0

MAX_PAGES: Final = 200
"""A hard stop on the walk.

Six years of eight-hour funding is about 6,600 payments, so seven pages. Two
hundred is far beyond any legitimate range and exists so that a venue
behaviour nobody anticipated ends the run with a message instead of spinning.
"""


def parse_funding(payload: dict[str, Any], *, asset: str) -> FundingRate:
    """One settlement, refusing anything malformed rather than defaulting it."""
    for key in ("fundingTime", "fundingRate"):
        if key not in payload:
            raise FundingError(f"funding record is missing {key!r}: {payload!r}")
    mark = payload.get("markPrice")
    return FundingRate(
        asset=asset,
        moment=datetime.fromtimestamp(int(payload["fundingTime"]) / 1000, tz=UTC),
        # Decimal from the string the venue sent. A funding rate is a small
        # number multiplied by a large notional, so float error here becomes
        # real money in a cost model.
        rate=Decimal(str(payload["fundingRate"])),
        mark_price=Decimal(str(mark)) if mark not in (None, "") else None,
    )


async def fetch_funding(
    *,
    asset: str,
    start: datetime,
    end: datetime,
    client: httpx.AsyncClient | None = None,
    endpoint: str = FUNDING_URL,
) -> tuple[FundingRate, ...]:
    """Every settled funding payment for `asset` between `start` and `end`."""
    if end <= start:
        raise FundingError("the range end must be after its start")

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    collected: dict[datetime, FundingRate] = {}
    cursor = start

    try:
        for _ in range(MAX_PAGES):
            page = await _fetch_page(http, asset=asset, start=cursor, end=end, endpoint=endpoint)
            if not page:
                break
            for entry in page:
                record = parse_funding(entry, asset=asset)
                collected[record.moment] = record
            newest = max(collected)
            logger.info(
                "funding page fetched",
                extra={"asset": asset, "through": newest.isoformat(), "returned": len(page)},
            )
            if len(page) < PAGE_LIMIT:
                break
            if newest <= cursor:
                raise FundingError(
                    f"the venue returned a full page that did not advance past "
                    f"{cursor.isoformat()}; the range cannot be walked"
                )
            # One millisecond past the last settlement, so the same payment is
            # not re-requested forever.
            cursor = newest + timedelta(milliseconds=1)
        else:
            raise FundingError(
                f"gave up after {MAX_PAGES} pages; the range or the venue's paging "
                f"is not what this code expects"
            )
    finally:
        if owns_client:
            await http.aclose()

    return tuple(collected[key] for key in sorted(collected))


async def _fetch_page(
    client: httpx.AsyncClient,
    *,
    asset: str,
    start: datetime,
    end: datetime,
    endpoint: str,
) -> list[dict[str, Any]]:
    """One `fundingRate` request, in the venue's own shape."""
    params: dict[str, str | int] = {
        "symbol": symbol_for(asset),
        "startTime": int(start.timestamp() * 1000),
        "endTime": int(end.timestamp() * 1000),
        "limit": PAGE_LIMIT,
    }
    response = await client.get(endpoint, params=params)
    if response.status_code == httpx.codes.BAD_REQUEST:
        raise FundingError(f"Binance refused funding for {asset}{QUOTE}: {response.text[:200]}")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise FundingError(f"expected a list of funding records, got {type(payload).__name__}")
    return payload
