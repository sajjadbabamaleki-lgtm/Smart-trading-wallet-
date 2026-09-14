"""Clock abstraction.

Nothing in this codebase may read wall-clock time directly. Every component
receives a `Clock`, so that production components can be replaced with
deterministic test doubles and so that recorded events can be replayed without
depending on the time at which the replay happens to run
(Build 0.1 Rev.1 §67, §68).

Two distinct notions of time are kept apart:

`now()`
    UTC wall-clock time. Used for audit, persistence and cross-system
    synchronisation. It can jump backwards when the host clock is corrected, so
    it must never be used to measure a duration.

`monotonic_ns()`
    A monotonic counter with no defined epoch. Used for every latency
    measurement. Only differences between two readings from the *same* clock
    instance are meaningful.

The distinction is mandatory rather than stylistic: TBIE v1.1 §42-43 makes
receipt-time and monotonic instrumentation a precondition for answering whether
trader-identity information survives our own observe-to-fill path, and that
question cannot be answered retroactively if the measurements were never taken.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Source of time for a component."""

    def now(self) -> datetime:
        """Current UTC wall-clock time, always timezone-aware."""
        ...

    def monotonic_ns(self) -> int:
        """Monotonic counter in nanoseconds, for measuring durations only."""
        ...


class SystemClock:
    """Production clock, reading the host's time sources."""

    __slots__ = ()

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()


class ManualClock:
    """Clock advanced explicitly by a test.

    Wall-clock and monotonic time advance together, so a test can assert on a
    duration without sleeping.
    """

    __slots__ = ("_monotonic_ns", "_now")

    def __init__(self, start: datetime, monotonic_ns: int = 0) -> None:
        if start.tzinfo is None:
            raise ValueError("ManualClock requires a timezone-aware start time")
        self._now = start.astimezone(UTC)
        self._monotonic_ns = monotonic_ns

    def now(self) -> datetime:
        return self._now

    def monotonic_ns(self) -> int:
        return self._monotonic_ns

    def advance_ns(self, nanoseconds: int) -> None:
        """Move both clocks forward. Time never moves backwards."""
        if nanoseconds < 0:
            raise ValueError("ManualClock cannot move backwards")
        self._monotonic_ns += nanoseconds
        self._now = self._now.fromtimestamp(
            self._now.timestamp() + nanoseconds / 1_000_000_000, tz=UTC
        )

    def advance_seconds(self, seconds: float) -> None:
        self.advance_ns(int(seconds * 1_000_000_000))


class ReplayClock:
    """Clock driven by the event stream being replayed.

    A replay engine calls `set_event_time()` as it emits each recorded event, so
    that downstream components observe the historical time rather than the
    present. This is what makes a replay deterministic: the same recorded input
    and the same code version must produce the same ordered output
    (Build 0.1 Rev.2 §22).

    The monotonic counter still advances by real elapsed time, because it
    measures how long *our* computation takes — which is a property of this run,
    not of the recording.
    """

    __slots__ = ("_event_time", "_monotonic_origin")

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("ReplayClock requires a timezone-aware start time")
        self._event_time = start.astimezone(UTC)
        self._monotonic_origin = time.monotonic_ns()

    def now(self) -> datetime:
        return self._event_time

    def monotonic_ns(self) -> int:
        return time.monotonic_ns() - self._monotonic_origin

    def set_event_time(self, event_time: datetime) -> None:
        """Advance replay time to the next event's timestamp.

        Refuses to move backwards: out-of-order replay is a defect in the
        recorded stream or the replay engine, not something to absorb silently.
        """
        if event_time.tzinfo is None:
            raise ValueError("ReplayClock requires a timezone-aware event time")
        candidate = event_time.astimezone(UTC)
        if candidate < self._event_time:
            raise ValueError(
                f"replay time moved backwards: {self._event_time.isoformat()} "
                f"-> {candidate.isoformat()}"
            )
        self._event_time = candidate
