"""Gap registry operations.

The `data_gaps` table exists from M1 and the recorder writes rows into it. What
was missing is the other half: reading open gaps back, closing them when a
stream resumes, recording a backfill attempt and its outcome, and producing the
summary a dataset needs in order to declare what it overlaps.

The point of the registry is stated in Phase 3 §20 and §30: missing data must
never be silently filled, and a synthetic reconstruction must be labelled as
such rather than confused with observed data. A registry that only recorded
gaps without ever resolving them would drift into noise; one that closed them
optimistically would be worse than none.

So closure is explicit and typed. `RECOVERED` requires a known extent and real
backfilled data. A gap that cannot be recovered is marked `UNRECOVERABLE` and
stays visible forever — which is the honest outcome for most venue gaps, since
bounded API history means public trade data usually cannot be refetched
(TBIE v1.1 §32).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from libs.observability.logging import get_logger
from services.market_data.gaps import GapReport

logger = get_logger(__name__)


class BackfillStatus(StrEnum):
    """Mirrors the `data_gaps.backfill_status` constraint from M1."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    RECOVERED = "RECOVERED"
    PARTIAL = "PARTIAL"
    UNRECOVERABLE = "UNRECOVERABLE"

    @property
    def is_open(self) -> bool:
        return self in (BackfillStatus.PENDING, BackfillStatus.IN_PROGRESS)

    @property
    def leaves_data_missing(self) -> bool:
        """Whether data is still absent after this outcome.

        `PARTIAL` counts. Partially recovered is not recovered, and a dataset
        overlapping it must still declare the gap.
        """
        return self in (
            BackfillStatus.PENDING,
            BackfillStatus.IN_PROGRESS,
            BackfillStatus.PARTIAL,
            BackfillStatus.UNRECOVERABLE,
        )


class QualityImpact(StrEnum):
    UNKNOWN = "UNKNOWN"
    NONE = "NONE"
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"
    INVALIDATING = "INVALIDATING"


@dataclass(frozen=True, slots=True)
class RegisteredGap:
    """A gap as stored, with its resolution state."""

    gap_id: str
    asset: str
    event_type: str
    gap_start: datetime
    gap_end: datetime | None
    detection_reason: str
    backfill_status: BackfillStatus
    backfill_attempts: int
    quality_impact: QualityImpact
    expected_sequence: int | None = None
    actual_sequence: int | None = None
    resolution: str | None = None

    @property
    def is_open(self) -> bool:
        return self.backfill_status.is_open

    @property
    def duration_seconds(self) -> float | None:
        """How long the gap lasted, if it is closed.

        None for an open gap: the stream has not resumed, so the duration is
        genuinely unknown. Reporting elapsed-time-so-far as the duration would
        make an ongoing outage look like a bounded one.
        """
        if self.gap_end is None:
            return None
        return (self.gap_end - self.gap_start).total_seconds()

    def as_source_dict(self) -> dict[str, Any]:
        """Constructor arguments, for building a modified copy.

        A frozen dataclass with an enum field cannot use `dataclasses.replace`
        without re-validating, and spelling the fields out here keeps a new
        field from being silently dropped when one is added.
        """
        return {
            "gap_id": self.gap_id,
            "asset": self.asset,
            "event_type": self.event_type,
            "gap_start": self.gap_start,
            "gap_end": self.gap_end,
            "detection_reason": self.detection_reason,
            "backfill_status": self.backfill_status,
            "backfill_attempts": self.backfill_attempts,
            "quality_impact": self.quality_impact,
            "expected_sequence": self.expected_sequence,
            "actual_sequence": self.actual_sequence,
            "resolution": self.resolution,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "asset": self.asset,
            "event_type": self.event_type,
            "gap_start": self.gap_start.isoformat(),
            "gap_end": None if self.gap_end is None else self.gap_end.isoformat(),
            "duration_seconds": self.duration_seconds,
            "detection_reason": self.detection_reason,
            "backfill_status": self.backfill_status.value,
            "backfill_attempts": self.backfill_attempts,
            "quality_impact": self.quality_impact.value,
            "expected_sequence": self.expected_sequence,
            "actual_sequence": self.actual_sequence,
            "resolution": self.resolution,
        }


@dataclass(frozen=True, slots=True)
class GapSummary:
    """What a dataset needs to know about the gaps it overlaps."""

    total: int
    open_gaps: int
    recovered: int
    partial: int
    unrecoverable: int
    by_stream: dict[str, int]
    longest_seconds: float | None

    @property
    def has_missing_data(self) -> bool:
        """Whether any gap still leaves data absent."""
        return (self.open_gaps + self.partial + self.unrecoverable) > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "open": self.open_gaps,
            "recovered": self.recovered,
            "partial": self.partial,
            "unrecoverable": self.unrecoverable,
            "has_missing_data": self.has_missing_data,
            "longest_seconds": self.longest_seconds,
            "by_stream": dict(sorted(self.by_stream.items())),
        }


@runtime_checkable
class GapRegistry(Protocol):
    """Storage for detected gaps."""

    async def register(self, gap: GapReport) -> RegisteredGap: ...

    async def close(
        self, gap_id: str, *, ended_at: datetime, status: BackfillStatus, resolution: str
    ) -> RegisteredGap: ...

    async def record_attempt(self, gap_id: str, *, outcome: str) -> RegisteredGap: ...

    async def open_gaps(self) -> tuple[RegisteredGap, ...]: ...

    async def summary(self) -> GapSummary: ...


class InMemoryGapRegistry:
    """Registry backed by a dict.

    Used by the tests and by `--dry-run`, where nothing should be written to a
    store but gap handling still has to be exercised.
    """

    def __init__(self) -> None:
        self._gaps: dict[str, RegisteredGap] = {}

    async def register(self, gap: GapReport) -> RegisteredGap:
        if gap.gap_id in self._gaps:
            return self._gaps[gap.gap_id]
        registered = RegisteredGap(
            gap_id=gap.gap_id,
            asset=gap.asset,
            event_type=gap.event_type,
            gap_start=gap.gap_start,
            gap_end=gap.gap_end,
            detection_reason=gap.detection_reason,
            backfill_status=BackfillStatus.PENDING,
            backfill_attempts=0,
            # A suspected gap makes no claim about impact yet; a proven one is
            # material until an investigation says otherwise.
            quality_impact=QualityImpact.UNKNOWN if gap.suspected else QualityImpact.MATERIAL,
            expected_sequence=gap.expected_sequence,
            actual_sequence=gap.actual_sequence,
        )
        self._gaps[gap.gap_id] = registered
        return registered

    async def close(
        self, gap_id: str, *, ended_at: datetime, status: BackfillStatus, resolution: str
    ) -> RegisteredGap:
        existing = self._require(gap_id)
        if status is BackfillStatus.RECOVERED and ended_at < existing.gap_start:
            raise ValueError(
                f"cannot close gap {gap_id}: end {ended_at.isoformat()} precedes "
                f"start {existing.gap_start.isoformat()}"
            )
        updated = RegisteredGap(
            gap_id=existing.gap_id,
            asset=existing.asset,
            event_type=existing.event_type,
            gap_start=existing.gap_start,
            gap_end=ended_at,
            detection_reason=existing.detection_reason,
            backfill_status=status,
            backfill_attempts=existing.backfill_attempts,
            quality_impact=QualityImpact.NONE
            if status is BackfillStatus.RECOVERED
            else existing.quality_impact,
            expected_sequence=existing.expected_sequence,
            actual_sequence=existing.actual_sequence,
            resolution=resolution,
        )
        self._gaps[gap_id] = updated
        logger.info(
            "gap_closed",
            extra={
                "gap_id": gap_id,
                "status": status.value,
                "resolution": resolution,
                "duration_seconds": updated.duration_seconds,
            },
        )
        return updated

    async def record_attempt(self, gap_id: str, *, outcome: str) -> RegisteredGap:
        existing = self._require(gap_id)
        updated = RegisteredGap(
            **{
                **existing.as_source_dict(),
                "backfill_attempts": existing.backfill_attempts + 1,
                "backfill_status": BackfillStatus.IN_PROGRESS,
                "resolution": outcome,
            }
        )
        self._gaps[gap_id] = updated
        return updated

    async def open_gaps(self) -> tuple[RegisteredGap, ...]:
        return tuple(gap for gap in self._gaps.values() if gap.is_open)

    async def summary(self) -> GapSummary:
        by_stream: dict[str, int] = {}
        durations: list[float] = []
        counts = dict.fromkeys(BackfillStatus, 0)
        for gap in self._gaps.values():
            key = f"{gap.asset}/{gap.event_type}"
            by_stream[key] = by_stream.get(key, 0) + 1
            counts[gap.backfill_status] += 1
            duration = gap.duration_seconds
            if duration is not None:
                durations.append(duration)
        return GapSummary(
            total=len(self._gaps),
            open_gaps=counts[BackfillStatus.PENDING] + counts[BackfillStatus.IN_PROGRESS],
            recovered=counts[BackfillStatus.RECOVERED],
            partial=counts[BackfillStatus.PARTIAL],
            unrecoverable=counts[BackfillStatus.UNRECOVERABLE],
            by_stream=by_stream,
            longest_seconds=max(durations) if durations else None,
        )

    def _require(self, gap_id: str) -> RegisteredGap:
        if gap_id not in self._gaps:
            raise KeyError(f"gap {gap_id} is not registered")
        return self._gaps[gap_id]
