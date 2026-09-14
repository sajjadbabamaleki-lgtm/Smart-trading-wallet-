"""The monitor loop.

M2 built the detectors; nothing drove the ones that need a timer. A stream that
has stopped sends nothing, so a per-message check can never notice it — which is
the whole reason Build 0.1 Rev.1 §28 separates "socket connected" from "data
flowing", and §35 makes freshness a monitored metric rather than a property
checked on arrival.

This loop runs alongside the recorder and asks, on a schedule:

- has any stream gone quiet past its threshold? (silence gaps, Rev.1 §30)
- is the connection delivering anything at all? (heartbeat, §28)
- how stale is the freshest data we hold? (§35)

Freshness is where this connects to trading later. Phase 2 §11 requires

    Data Quality Failure -> Trading Restriction -> NO TRADE / SAFE MODE

and M2's staleness limit is already in settings. There is nothing to restrict at
this milestone, so the monitor reports and records; the restriction is wired in
when the Risk Engine exists at M7. Writing the measurement now means that wiring
is a connection rather than a new capability.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from libs.domain.clock import Clock
from libs.observability.logging import get_logger
from services.market_data.gaps import GapDetector, GapReport, Heartbeat
from services.market_data.state import RecorderState, StateMachine

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FreshnessSnapshot:
    """How current the data is, per stream, at one moment."""

    checked_at: datetime
    ages_seconds: dict[str, float]
    stalest_stream: str | None
    stalest_age_seconds: float | None
    limit_seconds: float

    @property
    def within_limit(self) -> bool:
        """Whether every stream is fresh enough to decide on.

        A recorder with no streams yet is vacuously within limit: nothing is
        stale because nothing has arrived. That is distinct from *fresh*, and
        the caller that eventually gates trading must treat "no data at all" as
        a refusal rather than a pass — which is why `ages_seconds` being empty
        is visible here rather than collapsed into the boolean.
        """
        if self.stalest_age_seconds is None:
            return True
        return self.stalest_age_seconds <= self.limit_seconds

    @property
    def has_data(self) -> bool:
        return bool(self.ages_seconds)

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at.isoformat(),
            "within_limit": self.within_limit,
            "has_data": self.has_data,
            "limit_seconds": self.limit_seconds,
            "stalest_stream": self.stalest_stream,
            "stalest_age_seconds": (
                None if self.stalest_age_seconds is None else round(self.stalest_age_seconds, 3)
            ),
            "ages_seconds": {
                stream: round(age, 3) for stream, age in sorted(self.ages_seconds.items())
            },
        }


@dataclass
class MonitorCheck:
    """The outcome of one monitor pass."""

    at: datetime
    freshness: FreshnessSnapshot
    silence_gaps: tuple[GapReport, ...] = ()
    connection_silent: bool = False

    @property
    def is_healthy(self) -> bool:
        return not self.connection_silent and not self.silence_gaps and self.freshness.within_limit


@dataclass
class Monitor:
    """Periodic health checks over the recorder's detectors.

    Takes the same detector instances the recorder holds, so it observes the
    live state rather than a copy. It reports and records; it does not decide to
    reconnect — that belongs to the source, which is the only component that
    knows whether its socket is usable.
    """

    clock: Clock
    gaps: GapDetector
    heartbeat: Heartbeat
    machine: StateMachine
    staleness_limit: timedelta = timedelta(seconds=5)
    interval: timedelta = timedelta(seconds=5)
    on_gap: Callable[[GapReport], Awaitable[object]] | None = None
    """Called once per newly detected silence gap.

    The return value is ignored, so a registry's `register` - which returns the
    stored row - can be passed directly rather than wrapped.
    """

    checks: int = field(default=0, init=False)
    reported_gap_ids: set[str] = field(default_factory=set, init=False)
    last_check: MonitorCheck | None = field(default=None, init=False)

    async def check(self) -> MonitorCheck:
        """Run one pass.

        A silence gap for a stream already reported is not reported again. A
        stream quiet for an hour would otherwise produce a gap row per interval,
        flooding the registry with restatements of one fact — and burying the
        new gaps that matter among them.
        """
        now = self.clock.now()
        self.checks += 1

        fresh = self._freshness(now)
        silent = self.heartbeat.is_silent(now=now)

        new_gaps: list[GapReport] = []
        for gap in self.gaps.check_silence(now=now):
            key = f"{gap.asset}/{gap.event_type}/{gap.gap_start.isoformat()}"
            if key in self.reported_gap_ids:
                continue
            self.reported_gap_ids.add(key)
            new_gaps.append(gap)
            logger.warning(
                "silence_gap",
                extra={
                    "gap_id": gap.gap_id,
                    "asset": gap.asset,
                    "event_type": gap.event_type,
                    "reason": gap.detection_reason,
                    "suspected": gap.suspected,
                },
            )
            if self.on_gap is not None:
                await self.on_gap(gap)

        check = MonitorCheck(
            at=now,
            freshness=fresh,
            silence_gaps=tuple(new_gaps),
            connection_silent=silent,
        )
        self.last_check = check
        self._reflect_in_state(check)
        return check

    async def run(self, *, stop: asyncio.Event | None = None) -> None:
        """Check on the interval until stopped."""
        seconds = self.interval.total_seconds()
        while True:
            await self.check()
            if stop is None:
                await asyncio.sleep(seconds)
                continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=seconds)
            except TimeoutError:
                continue
            return

    def _freshness(self, now: datetime) -> FreshnessSnapshot:
        ages: dict[str, float] = {}
        for asset, event_type in self.gaps.streams:
            position = self.gaps.position(asset, event_type)
            if position is None or position.last_seen_at is None:
                continue
            ages[f"{asset}/{event_type}"] = (now - position.last_seen_at).total_seconds()

        stalest_stream: str | None = None
        stalest_age: float | None = None
        if ages:
            stalest_stream, stalest_age = max(ages.items(), key=lambda item: item[1])

        return FreshnessSnapshot(
            checked_at=now,
            ages_seconds=ages,
            stalest_stream=stalest_stream,
            stalest_age_seconds=stalest_age,
            limit_seconds=self.staleness_limit.total_seconds(),
        )

    def _reflect_in_state(self, check: MonitorCheck) -> None:
        """Move the recorder between HEALTHY and DEGRADED.

        The monitor is the component that can see staleness, so it is the one
        that must make it visible in the state — a recorder reporting HEALTHY
        while holding hour-old data is the silent failure this whole milestone
        is about.
        """
        if not check.is_healthy and self.machine.state is RecorderState.HEALTHY:
            reason = self._degradation_reason(check)
            self.machine.transition(RecorderState.DEGRADED, at=check.at, reason=reason)
            logger.warning("recorder_degraded", extra={"reason": reason})
        elif check.is_healthy and self.machine.state is RecorderState.DEGRADED:
            self.machine.transition(
                RecorderState.HEALTHY, at=check.at, reason="streams fresh again"
            )
            logger.info("recorder_recovered", extra={"checks": self.checks})

    def _degradation_reason(self, check: MonitorCheck) -> str:
        if check.connection_silent:
            return "connection delivering no data"
        if check.silence_gaps:
            streams = ", ".join(f"{gap.asset}/{gap.event_type}" for gap in check.silence_gaps)
            return f"stream(s) quiet: {streams}"
        return (
            f"{check.freshness.stalest_stream} is "
            f"{check.freshness.stalest_age_seconds:.0f}s old, limit "
            f"{check.freshness.limit_seconds:.0f}s"
        )
