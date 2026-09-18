"""Gap detection.

Build 0.1 Rev.1 §30 and §32, Phase 3 §20: missing data must never silently
disappear, and where the source publishes a sequence number, an unexpected jump
produces a gap event.

Two kinds of gap are detectable, and they are not the same claim:

**Sequence gap** — the venue numbered its messages and a number is missing. This
is evidence that data existed and we do not have it. It is definite.

**Silence gap** — no message arrived on a stream for longer than expected. This
is weaker: a quiet market and a broken socket look identical from inside the
process, which is why the heartbeat exists (Build 0.1 Rev.1 §28 — a connected
socket is not the same as data flowing). A silence gap is reported as
`suspected`, so a quiet period is never recorded as certain data loss.

Reports are returned rather than written: this module decides *what happened*,
the recorder decides what to do about it, and the `data_gaps` table stores it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final


class GapKind(StrEnum):
    SEQUENCE = "SEQUENCE"
    SILENCE = "SILENCE"
    DISCONNECT = "DISCONNECT"


@dataclass(frozen=True, slots=True)
class GapReport:
    """One detected gap, shaped for the `data_gaps` table."""

    gap_id: str
    kind: GapKind
    asset: str
    event_type: str
    gap_start: datetime
    gap_end: datetime | None
    detection_reason: str
    expected_sequence: int | None = None
    actual_sequence: int | None = None
    suspected: bool = False
    """True when inferred from silence rather than proven by a missing sequence
    number. A suspected gap must not be reported as certain data loss."""

    @property
    def missing_count(self) -> int | None:
        """How many messages are known missing, for a sequence gap."""
        if self.expected_sequence is None or self.actual_sequence is None:
            return None
        return max(0, self.actual_sequence - self.expected_sequence)


@dataclass
class StreamPosition:
    """What we last saw on one (asset, event type) stream."""

    last_sequence: int | None = None
    last_seen_at: datetime | None = None
    message_count: int = 0
    mean_interval_seconds: float | None = None
    """Exponentially weighted mean gap between messages, in seconds.

    Recent intervals weigh more than old ones, which is the point: BTC trades
    arrive every two seconds in the busy hours and every ten in the quiet ones,
    and a mean over the whole day describes neither.

    The first interval seen becomes the mean outright, because there is nothing
    to average it against. A stream whose first interval happens to be long is
    therefore slow to react for a while; the ceiling is what bounds how long,
    and bounding it is why the ceiling exists.
    """


# How much quieter than its own recent rhythm a stream must go before the
# silence is worth reporting.
SILENCE_MULTIPLIER: Final = 10.0
# Weight of the newest interval in the mean. Low enough that one slow message
# does not move the threshold, high enough to follow the day.
INTERVAL_SMOOTHING: Final = 0.1


class GapDetector:
    """Tracks per-stream continuity.

    A stream is one `(asset, event_type)` pair, because sequence numbers and
    update cadences are per-stream: a funding update every eight hours and a
    book update every block cannot share a silence threshold.

    **The threshold follows the stream.** A single fixed one cannot work here:
    measured over 15 hours, BTC's quote rate ran about ten times higher at
    14:00 than at 21:00, and trades with it. A 30-second threshold set for the
    busy hours reported hundreds of silences overnight that were the market
    being quiet, and a threshold loose enough for the quiet hours would miss a
    real outage at midday. So each stream is judged against its own recent
    rhythm, bounded at both ends: never twitchier than `floor`, never blinder
    than `ceiling`.
    """

    def __init__(
        self,
        *,
        silence_threshold: timedelta = timedelta(seconds=30),
        silence_ceiling: timedelta = timedelta(seconds=300),
    ) -> None:
        self._silence_threshold = silence_threshold
        self._silence_ceiling = silence_ceiling
        self._streams: dict[tuple[str, str], StreamPosition] = {}

    def threshold_for(self, asset: str, event_type: str) -> timedelta:
        """How long this stream may be quiet before it is worth reporting.

        A stream that has not yet shown a rhythm is judged at the floor: with
        one message seen there is nothing to be adaptive about, and the floor is
        the conservative end.
        """
        position = self._streams.get((asset, event_type))
        if position is None or position.mean_interval_seconds is None:
            return self._silence_threshold
        adapted = timedelta(seconds=position.mean_interval_seconds * SILENCE_MULTIPLIER)
        return max(self._silence_threshold, min(adapted, self._silence_ceiling))

    def observe(
        self,
        *,
        asset: str,
        event_type: str,
        sequence: int | None,
        seen_at: datetime,
    ) -> GapReport | None:
        """Record one observation, returning a gap report if one is implied.

        Out-of-order and repeated sequence numbers return no gap: the first is a
        delivery-order question and the second is the duplicate detector's
        concern. Only a forward jump proves absence.
        """
        key = (asset, event_type)
        position = self._streams.setdefault(key, StreamPosition())
        previous_sequence = position.last_sequence
        previous_seen = position.last_seen_at

        position.message_count += 1
        if previous_seen is not None:
            interval = (seen_at - previous_seen).total_seconds()
            # Out-of-order arrivals would otherwise pull the mean negative and
            # make the threshold shorter than any real interval.
            if interval > 0:
                previous_mean = position.mean_interval_seconds
                position.mean_interval_seconds = (
                    interval
                    if previous_mean is None
                    else previous_mean + INTERVAL_SMOOTHING * (interval - previous_mean)
                )
        position.last_seen_at = seen_at
        if sequence is not None and (
            position.last_sequence is None or sequence > position.last_sequence
        ):
            position.last_sequence = sequence

        if sequence is None or previous_sequence is None:
            return None
        expected = previous_sequence + 1
        if sequence <= previous_sequence or sequence == expected:
            return None

        return GapReport(
            gap_id=str(uuid.uuid4()),
            kind=GapKind.SEQUENCE,
            asset=asset,
            event_type=event_type,
            gap_start=previous_seen or seen_at,
            gap_end=seen_at,
            detection_reason=(
                f"sequence jumped from {previous_sequence} to {sequence}, "
                f"{sequence - expected + 1} message(s) missing"
            ),
            expected_sequence=expected,
            actual_sequence=sequence,
            suspected=False,
        )

    def check_silence(self, *, now: datetime) -> tuple[GapReport, ...]:
        """Report streams that have gone quiet for longer than the threshold.

        Called on a timer by the recorder, not per message — a stream that has
        stopped sends nothing to trigger a per-message check, which is the
        entire point.
        """
        reports: list[GapReport] = []
        for (asset, event_type), position in self._streams.items():
            if position.last_seen_at is None:
                continue
            silence = now - position.last_seen_at
            threshold = self.threshold_for(asset, event_type)
            if silence <= threshold:
                continue
            reports.append(
                GapReport(
                    gap_id=str(uuid.uuid4()),
                    kind=GapKind.SILENCE,
                    asset=asset,
                    event_type=event_type,
                    gap_start=position.last_seen_at,
                    # Deliberately open: the stream has not resumed, so the end
                    # is genuinely unknown. The table's constraint enforces the
                    # same thing — a gap cannot be recovered while open.
                    gap_end=None,
                    detection_reason=(
                        f"no message for {silence.total_seconds():.0f}s, threshold "
                        f"{threshold.total_seconds():.0f}s"
                    ),
                    suspected=True,
                )
            )
        return tuple(reports)

    def report_disconnect(
        self, *, asset: str, event_type: str, disconnected_at: datetime, reason: str
    ) -> GapReport:
        """Record a gap caused by a known disconnect.

        Definite rather than suspected: we know the socket dropped, so any data
        published during the outage is data we do not have. `gap_end` stays open
        until the stream resumes.
        """
        return GapReport(
            gap_id=str(uuid.uuid4()),
            kind=GapKind.DISCONNECT,
            asset=asset,
            event_type=event_type,
            gap_start=disconnected_at,
            gap_end=None,
            detection_reason=reason,
            suspected=False,
        )

    def position(self, asset: str, event_type: str) -> StreamPosition | None:
        return self._streams.get((asset, event_type))

    @property
    def streams(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._streams)


@dataclass
class Heartbeat:
    """Data-flow liveness.

    Build 0.1 Rev.1 §28 draws the distinction this exists for: *socket
    connected* and *useful data flowing* are not equivalent, and heartbeat
    monitoring must detect a silent connection.

    Tracked separately from the gap detector because it answers a different
    question. The gap detector asks "did we miss something on this stream"; the
    heartbeat asks "is this connection worth keeping". A connection delivering
    nothing across every stream is dead regardless of whether any individual
    stream's silence is explainable.
    """

    threshold: timedelta = timedelta(seconds=30)
    last_data_at: datetime | None = None
    messages: int = 0
    _silent_reports: int = field(default=0, repr=False)

    def record_data(self, at: datetime) -> None:
        self.last_data_at = at
        self.messages += 1

    def is_silent(self, *, now: datetime) -> bool:
        """Whether the connection has delivered nothing for too long."""
        if self.last_data_at is None:
            return False
        return now - self.last_data_at > self.threshold

    def silence_seconds(self, *, now: datetime) -> float | None:
        if self.last_data_at is None:
            return None
        return (now - self.last_data_at).total_seconds()

    def reset(self) -> None:
        """Clear state on reconnect, keeping the cumulative message count."""
        self.last_data_at = None
