"""Deterministic replay.

Build 0.1 Rev.2 §22 states the guarantee: the same input dataset and the same
system version must produce the same ordered event stream. Rev.1 §66 says why
this module matters beyond testing — it is the seed of the event-driven
backtester, so any nondeterminism here becomes nondeterminism in every backtest
built on it.

Three things could break determinism, and each is addressed rather than hoped
about:

**Wall-clock reads.** A component reading the current time produces different
output on every run. The `ReplayClock` reports the session's time instead, and
`ruff`'s `DTZ` rules plus the injected-clock convention keep direct reads out of
the codebase (ADR-007).

**Generated identifiers.** Event ids are random UUIDs, so two runs produce
different ids for the same event. Comparison therefore excludes them — an id
identifies a row, it is not part of what the row says. `ReplayComparison` makes
that explicit rather than leaving each test to remember it.

**Iteration order.** Frames replay in file order, which is receipt order.
Nothing sorts or groups them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from libs.domain.clock import ReplayClock
from libs.observability.logging import get_logger
from libs.schemas.market_event import MarketEvent
from libs.schemas.trader_event import TraderEvent
from services.market_data.capture import CapturedSession, CapturedSessionSource, load_session
from services.market_data.recorder import Recorder, RecorderMetrics
from services.market_data.sinks import InMemorySink

logger = get_logger(__name__)

VOLATILE_FIELDS = frozenset({"event_id", "raw_reference"})
"""Fields that legitimately differ between two runs of the same input.

`event_id` is generated per run. `raw_reference` points at the archive row
written this run. Neither is part of what the event asserts about the market, so
neither belongs in a determinism comparison — and stating that here keeps the
decision in one place instead of repeated in every test.
"""


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """The outcome of one replay."""

    session: CapturedSession
    metrics: RecorderMetrics
    market_events: tuple[MarketEvent, ...]
    trader_events: tuple[TraderEvent, ...]
    gaps: tuple[Any, ...]
    final_state: str

    def signature(self) -> list[dict[str, Any]]:
        """A comparable, stable representation of everything recorded.

        Excludes the volatile fields above. Two replays of one session must
        produce identical signatures; if they do not, the pipeline is not
        deterministic and every backtest built on it inherits that.
        """
        return [
            event.model_dump(exclude=set(VOLATILE_FIELDS), mode="json")
            for event in (*self.market_events, *self.trader_events)
        ]


@dataclass(frozen=True, slots=True)
class ReplayComparison:
    """Whether two replays agree, and where they do not."""

    identical: bool
    first_count: int
    second_count: int
    metrics_match: bool
    first_divergence: str | None = None

    def render(self) -> str:
        if self.identical:
            return f"deterministic: {self.first_count} events identical across two runs"
        return (
            f"NOT deterministic: {self.first_divergence or 'unknown divergence'} "
            f"({self.first_count} vs {self.second_count} events, "
            f"metrics {'match' if self.metrics_match else 'differ'})"
        )


class ReplayEngine:
    """Runs the recorder over a captured session.

    The recorder itself is unchanged: replay differs only in which
    `MessageSource` and which `Clock` it is given. That is deliberate — a replay
    that exercised a different code path would prove nothing about the live
    pipeline (Phase 7 §27: the same code, the same models, the same logic, with
    only the final permission disabled).
    """

    def __init__(self, session: CapturedSession) -> None:
        self._session = session

    @classmethod
    def from_file(cls, path: Path) -> ReplayEngine:
        return cls(load_session(path))

    @property
    def session(self) -> CapturedSession:
        return self._session

    async def run(self) -> ReplayResult:
        """Replay once."""
        start = self._start_time()
        clock = ReplayClock(start)
        sink = InMemorySink()
        source = CapturedSessionSource(self._session)

        recorder = Recorder(source=source, sink=sink, clock=clock)

        # Advance the replay clock to each frame's receipt time as it is
        # emitted, so components that ask "what time is it" during processing
        # see the session's time rather than today's.
        original_frames = source.frames

        async def clocked_frames():  # type: ignore[no-untyped-def]
            async for frame in original_frames():
                clock.set_event_time(frame.receipt.local_receive_time)
                yield frame

        source.frames = clocked_frames  # type: ignore[method-assign]

        metrics = await recorder.run()

        return ReplayResult(
            session=self._session,
            metrics=metrics,
            market_events=tuple(sink.market_events),
            trader_events=tuple(sink.trader_events),
            gaps=tuple(sink.gaps),
            final_state=recorder.machine.state.value,
        )

    def _start_time(self) -> datetime:
        span = self._session.span
        if span is None:
            raise ValueError(f"cannot replay {self._session.path}: the session contains no frames")
        return span[0]


async def verify_determinism(session: CapturedSession) -> ReplayComparison:
    """Replay twice and compare.

    This is the check Build 0.1's hard gate asks for (Rev.1 §77: "recorded
    events can be replayed deterministically"). Running it is the only way to
    know — determinism is a property of the whole pipeline, and no single
    component's test establishes it.
    """
    engine = ReplayEngine(session)
    first = await engine.run()
    second = await engine.run()

    first_signature = first.signature()
    second_signature = second.signature()
    metrics_match = first.metrics.as_dict() == second.metrics.as_dict()

    if first_signature == second_signature and metrics_match:
        return ReplayComparison(
            identical=True,
            first_count=len(first_signature),
            second_count=len(second_signature),
            metrics_match=True,
        )

    divergence = _first_difference(first_signature, second_signature)
    if divergence is None and not metrics_match:
        divergence = f"metrics differ: {first.metrics.as_dict()} vs {second.metrics.as_dict()}"

    return ReplayComparison(
        identical=False,
        first_count=len(first_signature),
        second_count=len(second_signature),
        metrics_match=metrics_match,
        first_divergence=divergence,
    )


def _first_difference(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> str | None:
    """Locate the first disagreement, for a diagnosable error message."""
    if len(first) != len(second):
        return f"event count differs: {len(first)} vs {len(second)}"
    for index, (left, right) in enumerate(zip(first, second, strict=True)):
        if left == right:
            continue
        differing = sorted(key for key in set(left) | set(right) if left.get(key) != right.get(key))
        details = ", ".join(f"{key}: {left.get(key)!r} != {right.get(key)!r}" for key in differing)
        return f"event {index} differs on {details}"
    return None


@dataclass
class ReplayReport:
    """Human- and machine-readable summary of a replay."""

    result: ReplayResult
    comparison: ReplayComparison | None = None
    findings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        session = self.result.session
        span = session.span
        return {
            "capture": {
                "path": str(session.path),
                "frames": len(session.frames),
                "malformed_lines": list(session.malformed_lines),
                "duration_seconds": round(session.duration_seconds, 3),
                "span": [span[0].isoformat(), span[1].isoformat()] if span else None,
                "header": None
                if session.header is None
                else {
                    "venue": session.header.venue,
                    "assets": list(session.header.assets),
                    "channels": list(session.header.channels),
                    "started_at": session.header.started_at,
                    "recorder_version": session.header.recorder_version,
                },
            },
            "recorder": {
                "final_state": self.result.final_state,
                "metrics": self.result.metrics.as_dict(),
            },
            "events": {
                "market": len(self.result.market_events),
                "trader": len(self.result.trader_events),
                "gaps": len(self.result.gaps),
            },
            "determinism": None
            if self.comparison is None
            else {
                "identical": self.comparison.identical,
                "events_compared": self.comparison.first_count,
                "divergence": self.comparison.first_divergence,
            },
            "findings": self.findings,
        }
