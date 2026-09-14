"""Clock behaviour."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from libs.domain.clock import Clock, ManualClock, ReplayClock, SystemClock

NAIVE = datetime(2026, 9, 14, 12, 0, 0)
AWARE = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)


def test_system_clock_satisfies_protocol() -> None:
    assert isinstance(SystemClock(), Clock)


def test_system_clock_returns_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_system_clock_monotonic_never_decreases() -> None:
    clock = SystemClock()
    readings = [clock.monotonic_ns() for _ in range(50)]
    assert readings == sorted(readings)


def test_manual_clock_satisfies_protocol() -> None:
    assert isinstance(ManualClock(AWARE), Clock)


def test_manual_clock_does_not_move_on_its_own() -> None:
    clock = ManualClock(AWARE)
    assert clock.now() == AWARE
    assert clock.now() == AWARE
    assert clock.monotonic_ns() == 0


def test_manual_clock_advances_both_clocks_together() -> None:
    clock = ManualClock(AWARE)
    clock.advance_seconds(1.5)
    assert clock.monotonic_ns() == 1_500_000_000
    assert clock.now() == AWARE + timedelta(seconds=1.5)


def test_manual_clock_rejects_naive_start() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ManualClock(NAIVE)


def test_manual_clock_refuses_to_move_backwards() -> None:
    clock = ManualClock(AWARE)
    with pytest.raises(ValueError, match="backwards"):
        clock.advance_ns(-1)


def test_replay_clock_reports_event_time_not_wall_clock() -> None:
    """A replay must not see the time at which the replay happens to run."""
    clock = ReplayClock(AWARE)
    assert clock.now() == AWARE

    later = AWARE + timedelta(hours=3)
    clock.set_event_time(later)
    assert clock.now() == later


def test_replay_clock_measures_real_elapsed_computation_time() -> None:
    """Monotonic time reflects this run, because it measures our own cost."""
    clock = ReplayClock(AWARE)
    first = clock.monotonic_ns()
    for _ in range(10_000):
        pass
    assert clock.monotonic_ns() >= first


def test_replay_clock_rejects_out_of_order_events() -> None:
    """Out-of-order replay is a defect, not something to absorb silently."""
    clock = ReplayClock(AWARE)
    clock.set_event_time(AWARE + timedelta(seconds=10))
    with pytest.raises(ValueError, match="backwards"):
        clock.set_event_time(AWARE + timedelta(seconds=5))


def test_replay_clock_allows_repeated_timestamps() -> None:
    """Two events can share a timestamp; that is not out of order."""
    clock = ReplayClock(AWARE)
    clock.set_event_time(AWARE)
    clock.set_event_time(AWARE)
    assert clock.now() == AWARE


def test_replay_clock_normalises_other_timezones() -> None:
    clock = ReplayClock(AWARE)
    tokyo = (AWARE + timedelta(hours=1)).astimezone(timezone(timedelta(hours=9)))
    clock.set_event_time(tokyo)
    assert clock.now() == AWARE + timedelta(hours=1)
    assert clock.now().utcoffset() == timedelta(0)
