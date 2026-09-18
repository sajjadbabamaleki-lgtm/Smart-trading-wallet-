"""The watchdog's decision, at the moment everything else has stopped.

Every branch is exercised without a store, because a component whose purpose is
to behave correctly when the recorder is gone cannot be tested only in the case
where the recorder is fine.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.market_data.watchdog import (
    DEFAULT_LIMIT,
    OpenOutage,
    StoreState,
    Verdict,
    assess,
)

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
LIMIT = timedelta(minutes=10)


def state(*, age: timedelta | None, outage: OpenOutage | None = None) -> StoreState:
    newest = None if age is None else NOW - age
    return StoreState(newest_event_at=newest, open_outage=outage)


def outage(*, started_minutes_ago: float = 60.0, restarts: int = 0) -> OpenOutage:
    return OpenOutage(
        gap_id="11111111-1111-1111-1111-111111111111",
        started_at=NOW - timedelta(minutes=started_minutes_ago),
        restarts_attempted=restarts,
    )


class TestFreshness:
    def test_a_recent_event_is_healthy_and_silent(self) -> None:
        decision = assess(state(age=timedelta(seconds=30)), now=NOW, limit=LIMIT)
        assert decision.verdict is Verdict.FRESH
        assert decision.is_healthy
        assert not decision.should_open
        assert not decision.should_restart

    def test_the_boundary_is_not_an_outage(self) -> None:
        decision = assess(state(age=LIMIT), now=NOW, limit=LIMIT)
        assert decision.verdict is Verdict.FRESH

    def test_an_empty_store_is_not_an_outage(self) -> None:
        """No rows means no start time, and inventing one would be a lie."""
        decision = assess(state(age=None), now=NOW, limit=LIMIT)
        assert decision.verdict is Verdict.EMPTY
        assert decision.is_healthy
        assert not decision.should_open
        assert decision.started_at is None


class TestDetection:
    def test_a_stopped_store_is_an_outage(self) -> None:
        decision = assess(state(age=timedelta(hours=39)), now=NOW, limit=LIMIT)
        assert decision.verdict is Verdict.STALE
        assert not decision.is_healthy
        assert decision.should_open

    def test_the_outage_starts_when_data_stopped_not_when_it_was_noticed(self) -> None:
        """The difference between those two is what this exists to record."""
        decision = assess(state(age=timedelta(hours=39)), now=NOW, limit=LIMIT)
        assert decision.started_at == NOW - timedelta(hours=39)

    def test_an_outage_already_recorded_is_not_recorded_again(self) -> None:
        decision = assess(state(age=timedelta(hours=39), outage=outage()), now=NOW, limit=LIMIT)
        assert decision.verdict is Verdict.STILL_STALE
        assert not decision.should_open
        assert not decision.is_healthy


class TestRestartPolicy:
    def test_a_new_outage_earns_one_restart(self) -> None:
        assert assess(state(age=timedelta(hours=1)), now=NOW, limit=LIMIT).should_restart

    def test_a_restart_already_attempted_is_not_repeated(self) -> None:
        """A recorder refusing to start refuses again; a loop buries the reason."""
        decision = assess(
            state(age=timedelta(hours=39), outage=outage(restarts=1)), now=NOW, limit=LIMIT
        )
        assert decision.verdict is Verdict.STILL_STALE
        assert not decision.should_restart

    def test_an_outage_recorded_but_never_restarted_still_gets_its_try(self) -> None:
        decision = assess(
            state(age=timedelta(hours=39), outage=outage(restarts=0)), now=NOW, limit=LIMIT
        )
        assert decision.should_restart

    def test_a_healthy_store_is_never_restarted(self) -> None:
        assert not assess(state(age=timedelta(seconds=5)), now=NOW, limit=LIMIT).should_restart
        assert not assess(state(age=None), now=NOW, limit=LIMIT).should_restart


class TestResumption:
    def test_data_arriving_again_closes_the_outage(self) -> None:
        decision = assess(state(age=timedelta(seconds=20), outage=outage()), now=NOW, limit=LIMIT)
        assert decision.verdict is Verdict.RESUMED
        assert decision.should_close
        assert decision.is_healthy

    def test_the_outage_ends_when_data_resumed_not_when_we_looked(self) -> None:
        """Otherwise every outage is padded by however long the timer slept."""
        decision = assess(state(age=timedelta(seconds=20), outage=outage()), now=NOW, limit=LIMIT)
        assert decision.ended_at == NOW - timedelta(seconds=20)
        assert decision.ended_at != NOW

    def test_the_recorded_extent_spans_from_stop_to_resume(self) -> None:
        decision = assess(
            state(age=timedelta(seconds=20), outage=outage(started_minutes_ago=90)),
            now=NOW,
            limit=LIMIT,
        )
        assert decision.started_at is not None
        assert decision.ended_at is not None
        assert decision.ended_at > decision.started_at


class TestReporting:
    def test_the_default_limit_is_stated_rather_than_assumed(self) -> None:
        assert assess(state(age=timedelta(seconds=1)), now=NOW).limit == DEFAULT_LIMIT

    def test_an_outage_describes_itself_with_its_length(self) -> None:
        decision = assess(state(age=timedelta(hours=39)), now=NOW, limit=LIMIT)
        assert "140400s" in decision.describe()

    def test_an_empty_store_says_so_rather_than_reporting_an_age(self) -> None:
        assert "no market events" in assess(state(age=None), now=NOW).describe()
