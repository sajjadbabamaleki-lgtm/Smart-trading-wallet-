"""The watchdog's decision, at the moment everything else has stopped.

Every branch is exercised without a store, because a component whose purpose is
to behave correctly when the recorder is gone cannot be tested only in the case
where the recorder is fine.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from libs.config import Settings, load_settings
from libs.observability.email import Alert, send
from services.market_data.watchdog import (
    DEFAULT_LIMIT,
    OpenOutage,
    StoreState,
    Verdict,
    alert_for,
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


class TestAlerting:
    """Two emails per outage. Not 468.

    The timer runs every five minutes, so the thirty-nine-hour outage would
    have produced 468 identical messages, and the 468th would be read exactly
    as carefully as the third. The branch that sends nothing is the one that
    makes the two that do arrive worth opening.
    """

    def test_a_new_outage_is_announced(self) -> None:
        decision = assess(state(age=timedelta(hours=39)), now=NOW, limit=LIMIT)
        alert = alert_for(decision, host="vmi")
        assert alert is not None
        assert "stopped" in alert.subject
        assert "vmi" in alert.subject

    def test_a_continuing_outage_says_nothing(self) -> None:
        """The branch that matters most, and has nothing to look at."""
        decision = assess(state(age=timedelta(hours=39), outage=outage()), now=NOW, limit=LIMIT)
        assert decision.verdict is Verdict.STILL_STALE
        assert alert_for(decision, host="vmi") is None

    def test_a_healthy_check_says_nothing(self) -> None:
        assert alert_for(assess(state(age=timedelta(seconds=5)), now=NOW), host="vmi") is None
        assert alert_for(assess(state(age=None), now=NOW), host="vmi") is None

    def test_resumption_is_announced_with_the_length_of_the_outage(self) -> None:
        decision = assess(
            state(age=timedelta(seconds=20), outage=outage(started_minutes_ago=120)),
            now=NOW,
            limit=LIMIT,
        )
        alert = alert_for(decision, host="vmi")
        assert alert is not None
        assert "receiving again" in alert.subject
        assert "2.0 hours" in alert.body

    def test_the_outage_email_says_what_was_done_about_it(self) -> None:
        alert = alert_for(assess(state(age=timedelta(hours=1)), now=NOW), host="vmi")
        assert alert is not None
        assert "data_gaps" in alert.body
        assert "journalctl" in alert.body


class TestAlertDelivery:
    """Sending must never take down the thing that notices."""

    def settings(self, **overrides: object) -> Settings:
        base: dict[str, object] = {}
        base.update(overrides)
        return load_settings(**base)

    def test_unconfigured_alerting_is_not_a_failure(self) -> None:
        """It is the default, and it asks a different question of a reader."""
        delivery = send(Alert(subject="s", body="b"), settings=self.settings())
        assert not delivery.attempted
        assert not delivery.sent
        assert delivery.error is not None
        assert "not configured" in delivery.error

    def test_a_refused_server_is_reported_rather_than_raised(self) -> None:
        delivery = send(
            Alert(subject="s", body="b"),
            settings=self.settings(
                alert_smtp_host="127.0.0.1",
                # Nothing listens here, so the connection is refused rather
                # than hanging, which is what makes this a fast test.
                alert_smtp_port=9,
                alert_email_from="a@example.invalid",
                alert_email_to="b@example.invalid",
            ),
        )
        assert delivery.attempted
        assert not delivery.sent
        assert delivery.error is not None

    def test_the_error_does_not_carry_the_recipient(self) -> None:
        """An SMTP error can quote the envelope, and a journal gets pasted around."""
        delivery = send(
            Alert(subject="s", body="b"),
            settings=self.settings(
                alert_smtp_host="127.0.0.1",
                alert_smtp_port=9,
                alert_email_from="sender@example.invalid",
                alert_email_to="recipient@example.invalid",
            ),
        )
        assert delivery.error is not None
        assert "recipient@example.invalid" not in delivery.error

    def test_alerting_needs_a_host_a_sender_and_a_recipient(self) -> None:
        assert not self.settings(alert_smtp_host="smtp.example.invalid").alerting_configured
        assert self.settings(
            alert_smtp_host="smtp.example.invalid",
            alert_email_from="a@example.invalid",
            alert_email_to="b@example.invalid",
        ).alerting_configured

    def test_the_safe_summary_says_whether_not_to_whom(self) -> None:
        secret = "hunter2"  # noqa: S105 - the point of the test is that it does not appear
        described = self.settings(
            alert_smtp_host="smtp.example.invalid",
            alert_email_from="a@example.invalid",
            alert_email_to="b@example.invalid",
            alert_smtp_password=secret,
        ).describe()
        assert described["alerting_configured"] is True
        assert "b@example.invalid" not in str(described)
        assert secret not in str(described)
