"""The recorder loop.

Build 0.1 Rev.2 §19 defines the pipeline this implements:

    CONNECT -> SUBSCRIBE -> CAPTURE RAW -> TIMESTAMP -> VALIDATE
    -> NORMALIZE -> PERSIST -> MONITOR

Three decisions shape the implementation, each of them a stated requirement
rather than a preference.

**Raw is archived before anything else is attempted.** Parsing, validation and
normalization all happen after the frame is safely stored, so a defect in any of
them costs a re-derivation rather than the data (Rev.2 §20). A frame that fails
to parse is still archived — an unparseable frame is evidence about the venue or
about our parser, and it is the only copy.

**A frame that cannot be processed does not stop the recorder.** It is counted,
logged with its reason, and the loop continues. The alternative — crashing on
one malformed frame — converts a single bad message into a total outage and a
gap in everything else.

**Nothing is silent.** Every state change, every gap, every rejected frame is
recorded. Phase 3 §29: a recorder that silently misses twenty minutes is worse
than one that reports a twenty-minute gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from libs.domain.clock import Clock
from libs.exchange.hyperliquid.messages import (
    MessageParseError,
    parse_message,
)
from libs.exchange.hyperliquid.normalize import NormalizationError, normalize
from libs.observability.logging import get_logger
from libs.schemas.enums import DataQualityStatus
from libs.schemas.market_event import MarketEvent
from services.market_data.dedup import DuplicateDetector
from services.market_data.gaps import GapDetector, Heartbeat
from services.market_data.quality import QualityEngine
from services.market_data.sinks import RawFrame, Sink
from services.market_data.source import IncomingFrame, MessageSource
from services.market_data.state import RecorderState, StateMachine

logger = get_logger(__name__)


@dataclass
class RecorderMetrics:
    """Counters the recorder exposes (Build 0.1 Rev.1 §61).

    `messages_invalid` counts frames we could not use. It is reported
    separately from `quality_invalid`, which counts events that parsed
    correctly but failed validation — a parser problem and a data problem need
    different responses.
    """

    messages_received: int = 0
    messages_archived: int = 0
    messages_parsed: int = 0
    messages_invalid: int = 0
    control_frames: int = 0
    market_events_written: int = 0
    trader_events_written: int = 0
    duplicates_dropped: int = 0
    backfill_events: int = 0
    """Events the venue replayed rather than delivered live.

    Counted separately because they are good data that no latency figure
    may be computed from. A run whose events are mostly backfill has
    observed the venue's history, not its behaviour.
    """
    quality_valid: int = 0
    quality_warning: int = 0
    quality_invalid: int = 0
    gaps_detected: int = 0
    persist_failures: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "messages_received": self.messages_received,
            "messages_archived": self.messages_archived,
            "messages_parsed": self.messages_parsed,
            "messages_invalid": self.messages_invalid,
            "control_frames": self.control_frames,
            "market_events_written": self.market_events_written,
            "trader_events_written": self.trader_events_written,
            "duplicates_dropped": self.duplicates_dropped,
            "backfill_events": self.backfill_events,
            "quality_valid": self.quality_valid,
            "quality_warning": self.quality_warning,
            "quality_invalid": self.quality_invalid,
            "gaps_detected": self.gaps_detected,
            "persist_failures": self.persist_failures,
        }


@dataclass
class Recorder:
    """Consumes a message source and records what it sees.

    Everything it needs is injected — source, sink, clock, detectors — so the
    whole pipeline runs deterministically in a test with no socket and no store
    (Build 0.1 Rev.1 §68).
    """

    source: MessageSource
    sink: Sink
    clock: Clock
    venue: str = "hyperliquid"
    quality: QualityEngine = field(default_factory=QualityEngine)
    dedup: DuplicateDetector = field(default_factory=DuplicateDetector)
    gaps: GapDetector = field(default_factory=GapDetector)
    heartbeat: Heartbeat = field(default_factory=Heartbeat)
    machine: StateMachine = field(default_factory=StateMachine)
    metrics: RecorderMetrics = field(default_factory=RecorderMetrics)
    # When we first heard from the venue. Set from the first frame's own
    # receipt time rather than from the clock at startup, so a replay
    # reconstructs the same boundary the live run used and reaches the same
    # verdicts. Everything the venue timestamps before this is history it
    # replayed to us on subscribing, not data that arrived late.
    stream_start: datetime | None = None
    staleness_limit: timedelta = timedelta(seconds=30)

    async def run(self) -> RecorderMetrics:
        """Record until the source is exhausted.

        Returns the metrics rather than logging and discarding them, so a test
        or an evidence run can assert on exactly what happened.
        """
        self._advance(RecorderState.CONNECTING, "opening source")
        self._advance(RecorderState.CONNECTED, f"source {self.source.name} open")
        self._advance(RecorderState.SUBSCRIBING, "subscribing")
        self._advance(RecorderState.HEALTHY, "receiving")

        async for frame in self.source.frames():
            await self._handle(frame)

        await self.sink.flush()
        return self.metrics

    async def _handle(self, frame: IncomingFrame) -> None:
        """Process one frame through the whole pipeline."""
        self.metrics.messages_received += 1
        received_at = frame.receipt.local_receive_time
        self.heartbeat.record_data(received_at)
        if self.stream_start is None:
            # The first frame we ever see fixes the boundary. Anything the
            # venue stamped earlier than this happened while we were not
            # listening.
            self.stream_start = received_at

        # 1. Archive raw, before anything can go wrong downstream.
        raw = RawFrame(
            raw_id=f"raw_{self.metrics.messages_received}_{int(received_at.timestamp() * 1e6)}",
            source=self.source.name,
            venue=self.venue,
            channel=self._channel_hint(frame.payload),
            payload=frame.payload,
            received_at_iso=received_at.isoformat(),
            received_monotonic_ns=frame.receipt.local_receive_monotonic_ns,
        )
        try:
            await self.sink.write_raw(raw)
            self.metrics.messages_archived += 1
        except Exception as exc:
            self.metrics.persist_failures += 1
            self._degrade(f"raw archive write failed: {type(exc).__name__}")
            logger.exception(
                "raw_archive_write_failed",
                extra={"raw_id": raw.raw_id, "error": str(exc)},
            )
            # Without the raw frame there is no recoverable evidence, so the
            # normalized rows derived from it would be unverifiable. Stop
            # processing this frame rather than store an orphan.
            return

        # 2. Parse.
        try:
            message = parse_message(frame.payload)
        except MessageParseError as exc:
            self.metrics.messages_invalid += 1
            logger.warning(
                "frame_parse_failed",
                extra={"raw_id": raw.raw_id, "reason": str(exc), "channel": raw.channel},
            )
            return
        self.metrics.messages_parsed += 1

        if not message.is_data:
            self.metrics.control_frames += 1
            logger.info("control_frame", extra={"channel": message.channel, "raw_id": raw.raw_id})
            return

        # 3. Normalize.
        try:
            market_events, trader_events = normalize(message, frame.receipt)
        except NormalizationError as exc:
            self.metrics.messages_invalid += 1
            logger.warning(
                "normalization_failed",
                extra={"raw_id": raw.raw_id, "reason": str(exc), "channel": message.channel},
            )
            return

        # 4. Validate, deduplicate and check continuity.
        accepted = await self._accept_market_events(market_events, raw)

        # 5. Persist.
        if accepted:
            try:
                await self.sink.write_market_events(accepted)
                self.metrics.market_events_written += len(accepted)
            except Exception as exc:
                self.metrics.persist_failures += 1
                self._degrade(f"market event write failed: {type(exc).__name__}")
                logger.exception(
                    "market_event_write_failed",
                    extra={"raw_id": raw.raw_id, "error": str(exc)},
                )
                return

        if trader_events:
            stamped = tuple(
                event.model_copy(update={"raw_reference": raw.raw_id}) for event in trader_events
            )
            try:
                await self.sink.write_trader_events(stamped)
                self.metrics.trader_events_written += len(stamped)
            except Exception as exc:
                self.metrics.persist_failures += 1
                self._degrade(f"trader event write failed: {type(exc).__name__}")
                logger.exception(
                    "trader_event_write_failed",
                    extra={"raw_id": raw.raw_id, "error": str(exc)},
                )

        # 6. Monitor.
        self._check_freshness()

    async def _accept_market_events(
        self, events: tuple[MarketEvent, ...], raw: RawFrame
    ) -> tuple[MarketEvent, ...]:
        """Validate and deduplicate, returning what should be written.

        Invalid events are still written. An `INVALID` verdict is a fact about
        the data that a dataset must be able to exclude, and excluding it
        requires knowing it existed (Rev.2 §21) — dropping it here would make
        the archive look cleaner than the feed was.
        """
        accepted: list[MarketEvent] = []
        for event in events:
            if self.dedup.is_duplicate(event):
                self.metrics.duplicates_dropped += 1
                logger.info(
                    "duplicate_dropped",
                    extra={
                        "asset": event.asset,
                        "event_type": event.event_type.value,
                        "raw_id": raw.raw_id,
                    },
                )
                continue

            gap = self.gaps.observe(
                asset=event.asset,
                event_type=event.event_type.value,
                sequence=event.sequence,
                seen_at=event.timestamps.local_receive_time,
            )
            if gap is not None:
                self.metrics.gaps_detected += 1
                await self.sink.write_gap(gap)
                logger.warning(
                    "gap_detected",
                    extra={
                        "gap_id": gap.gap_id,
                        "kind": gap.kind.value,
                        "asset": gap.asset,
                        "reason": gap.detection_reason,
                        "missing": gap.missing_count,
                    },
                )

            verdict = self.quality.validate(
                event, now=self.clock.now(), stream_start=self.stream_start
            )
            if verdict.backfill:
                self.metrics.backfill_events += 1
            if verdict.status is DataQualityStatus.VALID:
                self.metrics.quality_valid += 1
            elif verdict.status is DataQualityStatus.WARNING:
                self.metrics.quality_warning += 1
                logger.warning(
                    "quality_warning",
                    extra={
                        "asset": event.asset,
                        "event_type": event.event_type.value,
                        "findings": list(verdict.findings),
                    },
                )
            else:
                self.metrics.quality_invalid += 1
                logger.error(
                    "quality_invalid",
                    extra={
                        "asset": event.asset,
                        "event_type": event.event_type.value,
                        "findings": list(verdict.findings),
                    },
                )

            accepted.append(
                event.model_copy(
                    update={"quality_status": verdict.status, "raw_reference": raw.raw_id}
                )
            )
        return tuple(accepted)

    def _check_freshness(self) -> None:
        """Return to HEALTHY once data is flowing again, or degrade if stale."""
        now = self.clock.now()
        if self.heartbeat.is_silent(now=now):
            self._degrade(f"no data for {self.heartbeat.silence_seconds(now=now):.0f}s")
        elif self.machine.state is RecorderState.DEGRADED and self.machine.can_transition(
            RecorderState.HEALTHY
        ):
            self._advance(RecorderState.HEALTHY, "data flowing again")

    def _channel_hint(self, payload: str) -> str:
        """Cheap channel extraction for archiving, before full parsing.

        The archive is partitioned by channel, so the raw write needs a channel
        without depending on a parse that might fail. A frame whose channel
        cannot be read is archived as `unknown` rather than dropped.
        """
        marker = '"channel":"'
        start = payload.find(marker)
        if start == -1:
            return "unknown"
        start += len(marker)
        end = payload.find('"', start)
        return payload[start:end] if end != -1 else "unknown"

    def _advance(self, target: RecorderState, reason: str) -> None:
        transition = self.machine.transition(target, at=self.clock.now(), reason=reason)
        logger.info(
            "recorder_state",
            extra={
                "previous": transition.previous.value,
                "current": transition.current.value,
                "reason": reason,
            },
        )

    def _degrade(self, reason: str) -> None:
        """Move to DEGRADED, unless already there or unable to."""
        if self.machine.state is RecorderState.DEGRADED:
            return
        if not self.machine.can_transition(RecorderState.DEGRADED):
            return
        self._advance(RecorderState.DEGRADED, reason)
