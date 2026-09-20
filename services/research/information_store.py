"""Writing and reading outside information.

Kept apart from the candle and funding stores for the reason those are kept
apart from each other: the grain differs and the point-in-time rule differs.
Sentiment is daily and carries a publication lag; headlines arrive whenever an
outlet publishes and are read by our own receipt time.

FINAL on every read, as everywhere in this project: both tables replace
duplicates at merge time, both are re-fetched by a loop that runs every few
hours, and a duplicated row would shift a count without appearing anywhere.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from libs.information.fear_greed import Reading
from libs.information.headlines import Headline
from libs.storage.batching import in_partition_batches, month_of
from services.research.candle_store import as_utc

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from clickhouse_connect.driver.client import Client

SENTIMENT_COLUMNS: Sequence[str] = ("source", "published_at", "value", "classification")
HEADLINE_COLUMNS: Sequence[str] = (
    "item_id",
    "source",
    "title",
    "link",
    "published_at",
    "fetched_at",
)


def write_sentiment(client: Client, readings: Sequence[Reading], *, source: str) -> int:
    """Store readings, replacing any already held for the same day."""
    if not readings:
        return 0
    rows: list[list[object]] = [
        [source, entry.moment, entry.value, entry.classification] for entry in readings
    ]
    written = 0
    # Eight years of daily readings spans about a hundred monthly partitions,
    # which is the limit ClickHouse refuses at — the same problem the candle
    # backfill hit, and the same fix.
    for batch in in_partition_batches(rows, partition=_sentiment_partition):
        client.insert("sentiment_index", list(batch), column_names=list(SENTIMENT_COLUMNS))
        written += len(batch)
    return written


def _sentiment_partition(row: Sequence[object]) -> tuple[int, int]:
    moment = row[SENTIMENT_COLUMNS.index("published_at")]
    if not isinstance(moment, datetime):
        raise TypeError("published_at must be a datetime to determine its partition")
    return month_of(moment)


def read_sentiment(
    client: Client, *, source: str, start: datetime, end: datetime
) -> tuple[Reading, ...]:
    """Every stored reading in the range, oldest first."""
    result = client.query(
        "SELECT published_at, value, classification FROM sentiment_index FINAL "
        "WHERE source = %(source)s AND published_at >= %(range_start)s "
        "AND published_at < %(range_end)s ORDER BY published_at",
        parameters={"source": source, "range_start": start, "range_end": end},
    )
    return tuple(
        Reading(moment=as_utc(row[0]), value=row[1], classification=row[2])
        for row in result.result_rows
    )


def write_headlines(client: Client, headlines: Sequence[Headline]) -> int:
    """Store headlines, replacing any already held for the same link."""
    if not headlines:
        return 0
    rows: list[list[object]] = [
        [
            item.item_id,
            item.source,
            item.title,
            item.link,
            item.published_at,
            item.fetched_at,
        ]
        for item in headlines
    ]
    client.insert("headlines", rows, column_names=list(HEADLINE_COLUMNS))
    return len(rows)


def read_headlines(
    client: Client, *, start: datetime, end: datetime, limit: int = 200
) -> tuple[Headline, ...]:
    """Headlines we received in the range, newest first.

    Selected on `fetched_at`, never on `published_at`. What a decision at a
    moment may use is what we had received by then, and an outlet's claimed
    time can be earlier than the moment the item actually appeared.
    """
    result = client.query(
        "SELECT item_id, source, title, link, published_at, fetched_at FROM headlines "
        "FINAL WHERE fetched_at >= %(range_start)s AND fetched_at < %(range_end)s "
        "ORDER BY fetched_at DESC LIMIT %(limit)s",
        parameters={"range_start": start, "range_end": end, "limit": limit},
    )
    return tuple(
        Headline(
            source=row[1],
            title=row[2],
            link=row[3],
            published_at=None if row[4] is None else as_utc(row[4]),
            fetched_at=as_utc(row[5]),
        )
        for row in result.result_rows
    )
