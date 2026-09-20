"""Collect the inputs that are not the price series.

Two of them, with opposite shapes.

**The Fear & Greed index has eight years of history** and downloads in one
request, so it can be tested against the same period as everything else. It is
only half an outside input — about half its composite is volatility and
momentum — and the half that is not is the reason to bother.

**Headlines have no history at all.** A feed carries its last few dozen items,
so this collects forward and the signal cannot be judged for weeks. That is the
cost of the free route, and the alternative was to wait for a budget.

Both store our own receipt time beside the source's claimed time, and every
point-in-time query uses ours.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from libs.config import load_settings
from libs.information import fear_greed, headlines
from libs.observability import configure_logging
from libs.storage import clickhouse as ch
from services.research.information_store import (
    read_headlines,
    read_sentiment,
    write_headlines,
    write_sentiment,
)

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from clickhouse_connect.driver.client import Client

HISTORY_DAYS: Final = 3300


def _describe_sentiment(readings: tuple[fear_greed.Reading, ...]) -> None:
    if not readings:
        print("no sentiment stored")
        return
    values = sorted(entry.value for entry in readings)
    middle = len(values) // 2
    median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    fearful = sum(1 for entry in readings if entry.is_extreme_fear)
    greedy = sum(1 for entry in readings if entry.is_extreme_greed)
    latest = readings[-1]

    print(f"Fear & Greed: {len(readings):,} daily readings")
    print(f"  {readings[0].moment:%Y-%m-%d} to {latest.moment:%Y-%m-%d}")
    print(f"  median {median:.0f}, range {min(values):.0f} to {max(values):.0f}")
    print(
        f"  extreme fear on {fearful / len(readings):.0%} of days, "
        f"extreme greed on {greedy / len(readings):.0%}"
    )
    print(f"  right now: {latest.value:.0f} ({latest.classification})")
    print(f"  usable by a decision from {latest.known_from:%Y-%m-%d %H:%M} UTC")


def _describe_headlines(items: tuple[headlines.Headline, ...]) -> None:
    if not items:
        print("no headlines stored yet; the collector has just started")
        return
    lags = [item.claimed_lag_seconds for item in items]
    measured = [lag for lag in lags if lag is not None]
    print(f"headlines: {len(items):,} stored")
    by_source: dict[str, int] = {}
    for item in items:
        by_source[item.source] = by_source.get(item.source, 0) + 1
    for source, count in sorted(by_source.items()):
        print(f"  {source:<16} {count:>4}")
    if measured:
        # A feed that routinely publishes items long after their stated time is
        # a feed whose stated times cannot be trusted, and this is the number
        # that shows it before anything is built on them.
        median_lag = sorted(measured)[len(measured) // 2]
        print(f"  median claimed-to-received lag: {median_lag / 60:.0f} minutes")
    print()
    print("  most recent:")
    for item in items[:5]:
        print(f"    {item.fetched_at:%m-%d %H:%M}  [{item.source}] {item.title[:70]}")


def main() -> int:
    import argparse  # noqa: PLC0415 - CLI-local

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--what",
        default="both",
        choices=["sentiment", "headlines", "both"],
        help="which input to collect",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="describe what is stored without fetching",
    )
    args = parser.parse_args()

    configure_logging()
    settings = load_settings()
    now = datetime.now(tz=UTC)
    want_sentiment = args.what in {"sentiment", "both"}
    want_headlines = args.what in {"headlines", "both"}

    with ch.connect_from_settings(settings) as client:
        if want_sentiment:
            if not args.read_only:
                readings = asyncio.run(fear_greed.fetch_history())
                written = write_sentiment(client, readings, source=fear_greed.SOURCE)
                print(f"downloaded {len(readings):,} readings, wrote {written:,}")
                print()
            _describe_sentiment(
                read_sentiment(
                    client,
                    source=fear_greed.SOURCE,
                    start=now - timedelta(days=HISTORY_DAYS),
                    end=now + timedelta(days=1),
                )
            )

        if want_headlines:
            if want_sentiment:
                print()
            if not args.read_only:
                print(f"collected {_collect_headlines(client, now=now):,} new headlines")
                print()
            _describe_headlines(
                read_headlines(client, start=now - timedelta(days=30), end=now + timedelta(days=1))
            )
    return 0


def _collect_headlines(client: Client, *, now: datetime) -> int:
    """Read every configured feed and store what came back.

    One outlet failing must not stop the others: a feed that changed its URL,
    rate-limited us, or simply went down is a normal Tuesday, and the run
    should collect the other three and say which one it missed.
    """
    collected: list[headlines.Headline] = []
    for source in headlines.FEEDS:
        try:
            items = asyncio.run(headlines.fetch_feed(source, now=now))
        except Exception as exc:  # noqa: BLE001 - one bad feed must not stop the rest
            print(f"  {source}: {type(exc).__name__}")
            continue
        print(f"  {source}: {len(items)} items")
        collected.extend(items)
    return write_headlines(client, headlines.deduplicate(collected))


if __name__ == "__main__":
    raise SystemExit(main())
