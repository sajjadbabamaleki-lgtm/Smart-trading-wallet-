"""Download the price history a trader-style strategy reasons over.

The recorder captures every tick, and it begins the day it was switched on.
That is the right data for questions about microstructure and the wrong data
for the question this project actually exists to answer: given a chart, a
trend, and where an asset has been over the last year or two, is now a moment
to be long, short, or out.

So this fills the other table. It downloads closed candles from the venue's
public archive, stores them, and then says plainly what was stored and what it
implies about the cost of trading at that horizon — because the horizon is the
whole reason the earlier tick-scale work did not lead anywhere, and the
contrast is worth printing rather than remembering.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

from libs.config import load_settings
from libs.exchange.hyperliquid.candles import Candle, CandleRequest, fetch_candles
from libs.observability import configure_logging
from libs.storage import clickhouse as ch
from services.research.candle_store import missing_intervals, read_candles, write_candles

ROUND_TRIP_COST_BPS: Final = Decimal("9.62")
"""What one round trip costs, measured: 4.5 bps taker each way plus spread.

Printed against the candle ranges below because the comparison is the point. At
a thirty-second horizon the typical move was 1.04 bps against this, which is why
nothing at that scale could work. At a daily horizon it is a rounding error, and
seeing both numbers on one screen is more convincing than being told.
"""


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        return Decimal(0)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _describe(candles: tuple[Candle, ...], *, interval: str, step: timedelta) -> None:
    """Say what was stored, in terms that do not require reading the code."""
    if not candles:
        print("no candles stored: the venue returned nothing for that range")
        return

    first, last = candles[0], candles[-1]
    covered = last.close_time - first.open_time
    expected = int(covered / step)
    holes = missing_intervals(candles, step=step)

    ranges = [candle.range_bps for candle in candles]
    changes = [abs(candle.change_bps) for candle in candles]

    print(f"stored {len(candles):,} {interval} candles")
    print(f"  from {first.open_time:%Y-%m-%d %H:%M} to {last.close_time:%Y-%m-%d %H:%M} UTC")
    print(f"  {covered.days:,} days covered, {expected:,} intervals expected")
    if holes:
        # Declared, never filled. A series with an invisible hole has been
        # tested over a market that skipped those days.
        print(f"  {len(holes)} hole(s) in the archive; the largest are:")
        for after, before in sorted(holes, key=lambda pair: pair[1] - pair[0], reverse=True)[:3]:
            print(f"    {after:%Y-%m-%d %H:%M} -> {before:%Y-%m-%d %H:%M}")
    else:
        print("  no holes: every interval in the range is present")

    print()
    print(f"typical {interval} candle, as a percentage of price:")
    print(f"  high to low  : {_median(ranges) / 100:.2f}%  (median)")
    print(f"  open to close: {_median(changes) / 100:.2f}%  (median, direction ignored)")
    print()
    print(f"one round trip costs {ROUND_TRIP_COST_BPS / 100:.2f}%.")
    ratio = _median(changes) / ROUND_TRIP_COST_BPS
    print(f"A typical {interval} move is {ratio:.0f}x the cost of trading it.")
    print(
        "So at this horizon cost is not the binding constraint — being right\n"
        "about direction is. That is the question the strategy has to answer."
    )


def main() -> int:
    import argparse  # noqa: PLC0415 - CLI-local

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="SOL")
    parser.add_argument("--interval", default="1h")
    parser.add_argument(
        "--days",
        type=int,
        default=730,
        help="how far back to download; two years by default",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="describe what is already stored without downloading anything",
    )
    args = parser.parse_args()

    configure_logging()
    settings = load_settings()
    end = datetime.now(tz=UTC)
    request = CandleRequest(
        asset=args.asset.upper(),
        interval=args.interval,
        start=end - timedelta(days=args.days),
        end=end,
    )

    with ch.connect_from_settings(settings) as client:
        if not args.read_only:
            downloaded = asyncio.run(fetch_candles(request, now=end))
            written = write_candles(client, downloaded)
            print(f"downloaded {len(downloaded):,} closed candles, wrote {written:,}")
            print()
        stored = read_candles(client, request)

    _describe(stored, interval=request.interval, step=request.step)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
