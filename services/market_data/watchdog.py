"""Watching the recorder from outside it.

Everything M2 and M3 built to notice a failing recorder runs *inside* the
recorder. The gap detector, the freshness monitor, the heartbeat and the state
machine all observe the process from within, which means they observe nothing
at all about the failure that actually happened: on 2026-09-17 the recorder
refused to start, systemd exhausted its restart limit, and the store stopped
growing for thirty-nine hours. No gap was registered, because a gap is written
by a process that is running. Nobody was told, because the only thing that
could have told anyone had exited. It was found two days later by a person
running a report.

This is the part that cannot live in the recorder. It asks the store one
question — *when did you last receive anything?* — and it asks from a separate
process on a separate schedule, so a recorder that is dead, wedged, or refusing
to start all look the same from here: the number stops moving.

The decision is pure and lives here. The queries, the clock and the restart
live in `infrastructure/scripts/watch_recording.py`, so every branch below can
be tested without a store, which matters for a component whose whole purpose is
to behave correctly at the moment everything else has stopped.

What it deliberately does not do is decide that silence is the market's fault.
A quiet market still produces mark-price updates about once a second; the venue
publishes those whether or not anyone trades. Total silence across every stream
is not a quiet market, it is a recorder that has stopped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

# Belongs to the watchdog rather than to the recorder, and is recorded on the
# row so a reader can tell the two apart in `data_gaps`.
WATCHDOG_SOURCE: Final = "watchdog"

# The outage is not per-stream. When the recorder stops, every stream stops
# together, and one row per stream would be five restatements of one fact.
ALL_STREAMS: Final = "ALL_STREAMS"

DEFAULT_LIMIT: Final = timedelta(minutes=10)


class Verdict(StrEnum):
    """What the store's newest timestamp says about the recorder."""

    FRESH = "FRESH"
    """Receiving. Nothing to do, and nothing to say."""

    STALE = "STALE"
    """Stopped, and this is the first check to notice."""

    STILL_STALE = "STILL_STALE"
    """Stopped, and already recorded. Not recorded again."""

    RESUMED = "RESUMED"
    """Receiving again, with an outage still open to close."""

    EMPTY = "EMPTY"
    """The store holds nothing at all.

    Distinct from stale on purpose: a store with no rows has no newest
    timestamp to be stale relative to, and the cause is a first run or the
    wrong database rather than a recorder that stopped. Reporting it as an
    outage would invent a start time.
    """


@dataclass(frozen=True, slots=True)
class OpenOutage:
    """An outage this watchdog opened and has not yet closed."""

    gap_id: str
    started_at: datetime
    restarts_attempted: int


@dataclass(frozen=True, slots=True)
class StoreState:
    """What the two stores say, at one moment."""

    newest_event_at: datetime | None
    open_outage: OpenOutage | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    """What this check concluded and what the caller should do about it."""

    verdict: Verdict
    age: timedelta | None
    limit: timedelta
    open_outage: OpenOutage | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @property
    def should_open(self) -> bool:
        return self.verdict is Verdict.STALE

    @property
    def should_close(self) -> bool:
        return self.verdict is Verdict.RESUMED

    @property
    def should_restart(self) -> bool:
        """Whether to ask systemd to restart the recorder.

        Once per outage, not once per check. A recorder refusing to start for a
        configuration reason will refuse again, and a watchdog restarting it
        every five minutes turns one legible failure into a loop that buries
        it. One attempt is a fair try; a second is not a diagnosis.
        """
        if self.verdict is Verdict.STALE:
            return True
        if self.verdict is Verdict.STILL_STALE and self.open_outage is not None:
            return self.open_outage.restarts_attempted == 0
        return False

    @property
    def is_healthy(self) -> bool:
        """Whether the recorder is receiving *now*.

        `RESUMED` counts. The outage is real, recorded and closed, but it is
        over, and a check that reported failure for it would be reporting the
        past — which on a five-minute timer means one historical outage raising
        an alarm forever after it ended.
        """
        return self.verdict in (Verdict.FRESH, Verdict.EMPTY, Verdict.RESUMED)

    def describe(self) -> str:
        if self.verdict is Verdict.EMPTY:
            return "the store holds no market events at all"
        age = "unknown" if self.age is None else f"{self.age.total_seconds():.0f}s"
        limit = f"{self.limit.total_seconds():.0f}s"
        if self.verdict is Verdict.FRESH:
            return f"receiving: newest event {age} old, limit {limit}"
        if self.verdict is Verdict.RESUMED:
            return f"receiving again: newest event {age} old"
        return f"the store has not grown for {age}, limit {limit}"


def assess(state: StoreState, *, now: datetime, limit: timedelta = DEFAULT_LIMIT) -> Decision:
    """Decide what the store's newest timestamp means.

    `now` is passed rather than read so that the verdict is a function of its
    inputs. A watchdog that consulted the wall clock could not be tested at the
    only moment it matters.
    """
    newest = state.newest_event_at
    if newest is None:
        return Decision(verdict=Verdict.EMPTY, age=None, limit=limit)

    age = now - newest

    if age <= limit:
        if state.open_outage is not None:
            return Decision(
                verdict=Verdict.RESUMED,
                age=age,
                limit=limit,
                open_outage=state.open_outage,
                started_at=state.open_outage.started_at,
                # The outage ended when data started arriving again, which is
                # not when this check happened to run. Using `now` would add
                # however long the watchdog slept to the recorded outage.
                ended_at=newest,
            )
        return Decision(verdict=Verdict.FRESH, age=age, limit=limit)

    if state.open_outage is not None:
        return Decision(
            verdict=Verdict.STILL_STALE,
            age=age,
            limit=limit,
            open_outage=state.open_outage,
            started_at=state.open_outage.started_at,
        )
    return Decision(
        verdict=Verdict.STALE,
        age=age,
        limit=limit,
        # The outage began when the last event arrived, not when it was
        # noticed. The difference is the whole point of recording a start.
        started_at=newest,
    )
