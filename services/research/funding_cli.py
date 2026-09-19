"""Download funding-rate history, and say what is stored.

Funding is the one input this project has that describes positioning rather
than pattern: it is what the long and short sides are paying each other, so it
exists only because capital was committed. Every indicator is computed from the
same public candles by everyone who wants one; this is not.

It is also free and goes back years, which makes it the only fundamental-type
signal that can be tested against the six years of history already stored
rather than collected forward for months.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from libs.config import load_settings
from libs.domain.funding import FundingHistory, FundingRate
from libs.exchange.binance import funding as binance_funding
from libs.observability import configure_logging
from libs.storage import clickhouse as ch
from services.research.funding_store import read_funding, write_funding


def _describe(rates: tuple[FundingRate, ...], *, asset: str) -> None:
    """What was stored, and what it says about the period it covers."""
    if not rates:
        print(f"{asset}: no funding stored")
        return

    history = FundingHistory.build(rates)
    values = sorted(entry.rate for entry in rates)
    middle = len(values) // 2
    median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    positive = sum(1 for entry in rates if entry.rate > 0)

    print(f"{asset}: {len(rates):,} settlements")
    print(f"  {rates[0].moment:%Y-%m-%d} to {rates[-1].moment:%Y-%m-%d}")
    print(f"  median {median * Decimal(10000):+.4f} bps per settlement")
    print(f"  longs paid in {positive / len(rates):.0%} of them")
    print(
        f"  most extreme: {min(values) * Decimal(10000):+.2f} to "
        f"{max(values) * Decimal(10000):+.2f} bps"
    )
    latest = history.percentile_at(rates[-1].moment)
    if latest is not None:
        print(f"  right now: {latest:.0%} percentile of the last 30 days")


def main() -> int:
    import argparse  # noqa: PLC0415 - CLI-local

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="SOL")
    parser.add_argument("--days", type=int, default=2200)
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="describe what is stored without downloading",
    )
    args = parser.parse_args()

    configure_logging()
    settings = load_settings()
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=args.days)
    asset = args.asset.upper()
    venue = binance_funding.VENUE

    with ch.connect_from_settings(settings) as client:
        if not args.read_only:
            downloaded = asyncio.run(
                binance_funding.fetch_funding(asset=asset, start=start, end=end)
            )
            written = write_funding(client, downloaded, venue=venue)
            print(f"downloaded {len(downloaded):,} settlements, wrote {written:,}")
            print()
        stored = read_funding(client, venue=venue, asset=asset, start=start, end=end)

    _describe(stored, asset=asset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
