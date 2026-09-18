"""Sinks that write to the real stores.

Two writes per frame, in a fixed order: the raw archive first (object storage,
indexed in ClickHouse), then the normalized events. That order is the point —
see the note in `sinks.py`.

Writes are batched. A BTC feed delivers a book update per block and trades in
bursts; one round trip per event would make the recorder's throughput a function
of network latency rather than of the feed. Batches are flushed on size or age,
whichever comes first, so a quiet period does not leave events unwritten
indefinitely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from libs.domain.clock import Clock
from libs.observability.logging import get_logger
from libs.schemas.market_event import MarketEvent
from libs.schemas.trader_event import TraderEvent
from libs.storage.object_store import raw_key
from services.market_data.gaps import GapReport
from services.market_data.sinks import RawFrame

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from clickhouse_connect.driver.client import Client
    from mypy_boto3_s3.client import S3Client
    from psycopg import Connection

logger = get_logger(__name__)

MARKET_EVENT_COLUMNS: Final[tuple[str, ...]] = (
    "event_id",
    "schema_version",
    "source",
    "venue",
    "asset",
    "instrument",
    "event_type",
    "exchange_time",
    "consensus_time",
    "local_receive_time",
    "local_receive_monotonic_ns",
    "venue_event_id",
    "sequence",
    "price",
    "quantity",
    "side",
    "bid_price",
    "bid_quantity",
    "ask_price",
    "ask_quantity",
    "funding_rate",
    "open_interest",
    "raw_reference",
    "quality_status",
    "pit_status",
)

TRADER_EVENT_COLUMNS: Final[tuple[str, ...]] = (
    "event_id",
    "schema_version",
    "source",
    "venue",
    "asset",
    "instrument",
    "event_type",
    "exchange_time",
    "consensus_time",
    "local_receive_time",
    "local_receive_monotonic_ns",
    "wallet",
    "counterparty",
    "side",
    "price",
    "quantity",
    "notional",
    "order_id",
    "client_order_id",
    "twap_id",
    "start_position",
    "end_position",
    "raw_reference",
    "quality_status",
    "pit_status",
)

RAW_MESSAGE_COLUMNS: Final[tuple[str, ...]] = (
    "raw_id",
    "source",
    "venue",
    "channel",
    "local_receive_time",
    "local_receive_monotonic_ns",
    "payload",
    "payload_bytes",
    "payload_sha256",
    "archive_uri",
)


def _market_row(event: MarketEvent) -> list[Any]:
    stamps = event.timestamps
    return [
        event.event_id,
        event.schema_version,
        event.source,
        event.venue,
        event.asset,
        event.instrument,
        event.event_type.value,
        stamps.exchange_time,
        stamps.consensus_time,
        stamps.local_receive_time,
        stamps.local_receive_monotonic_ns,
        event.venue_event_id,
        event.sequence,
        event.price,
        event.quantity,
        None if event.side is None else event.side.value,
        event.bid_price,
        event.bid_quantity,
        event.ask_price,
        event.ask_quantity,
        event.funding_rate,
        event.open_interest,
        event.raw_reference or "",
        event.quality_status.value,
        event.pit_status.value,
    ]


def _trader_row(event: TraderEvent) -> list[Any]:
    stamps = event.timestamps
    # Empty strings rather than nulls for the String columns, matching the
    # schema: ClickHouse String is not nullable there, and the materialized
    # exclusion rule tests `twap_id != ''`.
    return [
        event.event_id,
        event.schema_version,
        event.source,
        event.venue,
        event.asset,
        event.instrument,
        event.event_type.value,
        stamps.exchange_time,
        stamps.consensus_time,
        stamps.local_receive_time,
        stamps.local_receive_monotonic_ns,
        event.wallet,
        event.counterparty or "",
        None if event.side is None else event.side.value,
        event.price,
        event.quantity,
        event.notional,
        event.order_id or "",
        event.client_order_id or "",
        event.twap_id or "",
        event.start_position,
        event.end_position,
        event.raw_reference or "",
        event.quality_status.value,
        event.pit_status.value,
    ]


@dataclass
class StoreSink:
    """Writes to object storage, ClickHouse and PostgreSQL."""

    clickhouse: Client
    object_store: S3Client
    postgres: Connection[Any]
    bucket: str
    clock: Clock
    batch_size: int = 500
    max_batch_age_seconds: float = 2.0

    _raw_batch: list[tuple[RawFrame, str]] = field(default_factory=list, init=False)
    _market_batch: list[MarketEvent] = field(default_factory=list, init=False)
    _trader_batch: list[TraderEvent] = field(default_factory=list, init=False)
    _oldest_pending: datetime | None = field(default=None, init=False)

    async def write_raw(self, frame: RawFrame) -> None:
        """Archive the payload, then queue its index row.

        The object write happens immediately rather than in a batch: it is the
        evidence everything else can be re-derived from, so it must be durable
        before the normalized rows referencing it are written.
        """
        received = datetime.fromisoformat(frame.received_at_iso).astimezone(UTC)
        key = raw_key(
            source=frame.source,
            channel=frame.channel,
            date=received.date().isoformat(),
            raw_id=frame.raw_id,
        )
        self.object_store.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=frame.payload.encode("utf-8"),
            ContentType="application/json",
            Metadata={"sha256": frame.payload_sha256, "channel": frame.channel},
        )
        self._raw_batch.append((frame, f"s3://{self.bucket}/{key}"))
        self._note_pending()
        await self._flush_if_due()

    async def write_market_events(self, events: tuple[MarketEvent, ...]) -> None:
        self._market_batch.extend(events)
        self._note_pending()
        await self._flush_if_due()

    async def write_trader_events(self, events: tuple[TraderEvent, ...]) -> None:
        self._trader_batch.extend(events)
        self._note_pending()
        await self._flush_if_due()

    async def write_gap(self, gap: GapReport) -> None:
        """Record a gap immediately, outside any batch.

        A gap is the one thing that must not be lost to a crash before the next
        flush: losing it turns an explicitly reported gap into a silent one,
        which is the failure Phase 3 §29 is about.

        Writing the same gap again closes it rather than being ignored, which
        is how a silence that ended stops claiming that data is still missing.
        `COALESCE` keeps the recorded end: a later restatement without one must
        not reopen a gap that was closed.
        """
        with self.postgres.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO data_gaps (
                    gap_id, source, venue, asset, event_type, gap_start, gap_end,
                    detection_reason, expected_sequence, actual_sequence,
                    quality_impact
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (gap_id) DO UPDATE SET
                    gap_end = COALESCE(EXCLUDED.gap_end, data_gaps.gap_end),
                    detection_reason = EXCLUDED.detection_reason
                """,
                (
                    gap.gap_id,
                    "hyperliquid_ws",
                    "hyperliquid",
                    gap.asset,
                    gap.event_type,
                    gap.gap_start,
                    gap.gap_end,
                    gap.detection_reason,
                    gap.expected_sequence,
                    gap.actual_sequence,
                    # A suspected gap makes no claim about impact yet; a proven
                    # one is at least material until investigated.
                    "UNKNOWN" if gap.suspected else "MATERIAL",
                ),
            )
        self.postgres.commit()

    async def flush(self) -> None:
        """Write every pending batch."""
        if self._raw_batch:
            self.clickhouse.insert(
                "raw_messages",
                [
                    [
                        frame.raw_id,
                        frame.source,
                        frame.venue,
                        frame.channel,
                        datetime.fromisoformat(frame.received_at_iso),
                        frame.received_monotonic_ns,
                        frame.payload,
                        frame.payload_bytes,
                        frame.payload_sha256,
                        uri,
                    ]
                    for frame, uri in self._raw_batch
                ],
                column_names=list(RAW_MESSAGE_COLUMNS),
            )
            self._raw_batch.clear()

        if self._market_batch:
            self.clickhouse.insert(
                "market_events",
                [_market_row(event) for event in self._market_batch],
                column_names=list(MARKET_EVENT_COLUMNS),
            )
            self._market_batch.clear()

        if self._trader_batch:
            self.clickhouse.insert(
                "trader_events",
                [_trader_row(event) for event in self._trader_batch],
                column_names=list(TRADER_EVENT_COLUMNS),
            )
            self._trader_batch.clear()

        self._oldest_pending = None

    def _note_pending(self) -> None:
        if self._oldest_pending is None:
            self._oldest_pending = self.clock.now()

    async def _flush_if_due(self) -> None:
        pending = len(self._raw_batch) + len(self._market_batch) + len(self._trader_batch)
        if pending >= self.batch_size:
            await self.flush()
            return
        if self._oldest_pending is None:
            return
        age = (self.clock.now() - self._oldest_pending).total_seconds()
        if age >= self.max_batch_age_seconds:
            await self.flush()
