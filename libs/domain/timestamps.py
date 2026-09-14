"""Timestamp and latency models.

Build 0.1 Rev.1 §17-18 requires that an event carry several distinct
timestamps, and TBIE v1.1 §42 extends the list through the decision path. The
reason is that these answer different questions:

- when did the event happen, according to the venue?
- when did *we* first learn about it?
- how long did each of our own stages take?

Only the second and third are within our control, and only they determine
whether a fast-decaying signal is reachable. A study can establish that
information exists at a one-second horizon using venue consensus timestamps and
still say nothing about whether our order can arrive in time (TBIE v1.1 §18).
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _require_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


class EventTimestamps(BaseModel):
    """Every time we can observe for a single event.

    Only `local_receive_time` and `local_receive_monotonic_ns` are mandatory:
    they are the two we always control. Venue-supplied fields stay optional
    because a source that does not provide them must leave them empty rather
    than have a value invented (Build 0.1 Rev.1 §32: unknown information must
    not be fabricated).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    local_receive_time: datetime = Field(
        description="UTC wall-clock time at which this process first saw the event."
    )
    local_receive_monotonic_ns: int = Field(
        description=(
            "Monotonic reading taken with local_receive_time. Latency is measured "
            "from this, never from wall-clock differences."
        )
    )

    consensus_time: datetime | None = Field(
        default=None,
        description="Venue consensus timestamp, where the venue publishes one.",
    )
    exchange_time: datetime | None = Field(
        default=None, description="Timestamp supplied by the exchange for the event."
    )
    block_time: datetime | None = Field(
        default=None, description="Block timestamp, for on-chain sourced events."
    )
    provider_time: datetime | None = Field(
        default=None, description="Timestamp supplied by a third-party provider."
    )
    decode_complete_time: datetime | None = Field(
        default=None, description="When decoding and validation of the raw message finished."
    )
    persist_time: datetime | None = Field(
        default=None, description="When the event entered durable storage."
    )

    _utc = field_validator(
        "local_receive_time",
        "consensus_time",
        "exchange_time",
        "block_time",
        "provider_time",
        "decode_complete_time",
        "persist_time",
        mode="after",
    )(_require_utc)

    @property
    def best_event_time(self) -> datetime:
        """The most authoritative available notion of when the event occurred.

        Falls back to our receive time, which is always present. Callers that
        need to know *which* source was used should read the fields directly
        rather than relying on this convenience.
        """
        return (
            self.consensus_time
            or self.exchange_time
            or self.block_time
            or self.provider_time
            or self.local_receive_time
        )

    @property
    def source_to_receive_seconds(self) -> float | None:
        """Delay between the venue's timestamp and our receipt, when measurable.

        Returns None when the venue supplied no timestamp. The value can be
        negative if the two clocks disagree, and is returned as measured rather
        than clamped — clock skew is a condition to monitor, not to hide
        (Build 0.1 Rev.1 §70, Phase 6 §62).
        """
        source = self.consensus_time or self.exchange_time or self.block_time
        if source is None:
            return None
        return (self.local_receive_time - source).total_seconds()


class LatencyBreakdown(BaseModel):
    """Per-stage latency for one decision, in nanoseconds.

    Stages are recorded as deltas from the monotonic reading taken at receipt.
    TBIE v1.1 §63 requires distributions at p50/p90/p95/p99/p99.9 rather than
    averages, because trading systems fail in the tail; this model is the
    per-observation record those distributions are computed from.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: str
    receive_to_feature_ns: int | None = None
    feature_to_decision_ns: int | None = None
    decision_to_order_ns: int | None = None
    order_to_ack_ns: int | None = None
    ack_to_fill_ns: int | None = None

    @property
    def receive_to_order_ns(self) -> int | None:
        """Total time we controlled, from first sight of the event to order send.

        None when any constituent stage was not measured: a partial sum would
        understate the delay, which is the specific error this instrumentation
        exists to prevent.
        """
        stages = (
            self.receive_to_feature_ns,
            self.feature_to_decision_ns,
            self.decision_to_order_ns,
        )
        if any(stage is None for stage in stages):
            return None
        return sum(stage for stage in stages if stage is not None)
