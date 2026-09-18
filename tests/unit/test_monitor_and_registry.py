"""Monitor loop and gap registry."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from libs.domain.clock import ManualClock
from services.market_data.gaps import GapDetector, GapKind, GapReport, Heartbeat
from services.market_data.monitor import Monitor
from services.market_data.registry import (
    BackfillStatus,
    InMemoryGapRegistry,
    PersistingGapRegistry,
    QualityImpact,
)
from services.market_data.sinks import InMemorySink
from services.market_data.state import RecorderState, StateMachine

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)


def build_monitor(
    *,
    staleness: timedelta = timedelta(seconds=5),
    silence: timedelta = timedelta(seconds=10),
    state: RecorderState = RecorderState.HEALTHY,
) -> tuple[Monitor, ManualClock, GapDetector, Heartbeat, StateMachine]:
    clock = ManualClock(NOW)
    gaps = GapDetector(silence_threshold=silence)
    heartbeat = Heartbeat(threshold=silence)
    machine = StateMachine(state=state)
    monitor = Monitor(
        clock=clock,
        gaps=gaps,
        heartbeat=heartbeat,
        machine=machine,
        staleness_limit=staleness,
    )
    return monitor, clock, gaps, heartbeat, machine


class TestFreshness:
    async def test_a_recorder_with_no_data_reports_no_ages(self) -> None:
        monitor, *_ = build_monitor()
        check = await monitor.check()
        assert not check.freshness.has_data
        assert check.freshness.stalest_age_seconds is None

    async def test_no_data_is_vacuously_within_limit_but_flagged(self) -> None:
        """A caller gating trading must treat "no data" as a refusal, not a pass."""
        monitor, *_ = build_monitor()
        check = await monitor.check()
        assert check.freshness.within_limit
        assert not check.freshness.has_data

    async def test_fresh_streams_are_within_limit(self) -> None:
        monitor, clock, gaps, heartbeat, _ = build_monitor()
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        heartbeat.record_data(NOW)
        clock.advance_seconds(1)
        check = await monitor.check()
        assert check.freshness.within_limit
        assert check.freshness.ages_seconds == {"BTC/TRADE": 1.0}

    async def test_the_stalest_stream_is_identified(self) -> None:
        monitor, clock, gaps, heartbeat, _ = build_monitor()
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        clock.advance_seconds(3)
        gaps.observe(asset="BTC", event_type="BBO", sequence=None, seen_at=clock.now())
        heartbeat.record_data(clock.now())
        clock.advance_seconds(1)

        check = await monitor.check()
        assert check.freshness.stalest_stream == "BTC/TRADE"
        assert check.freshness.stalest_age_seconds == pytest.approx(4.0)

    async def test_a_stale_stream_breaches_the_limit(self) -> None:
        monitor, clock, gaps, heartbeat, _ = build_monitor(staleness=timedelta(seconds=5))
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        heartbeat.record_data(NOW)
        clock.advance_seconds(9)
        check = await monitor.check()
        assert not check.freshness.within_limit
        assert not check.is_healthy

    async def test_the_snapshot_serialises_for_a_report(self) -> None:
        monitor, clock, gaps, heartbeat, _ = build_monitor()
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        heartbeat.record_data(NOW)
        clock.advance_seconds(2)
        payload = (await monitor.check()).freshness.as_dict()
        assert payload["ages_seconds"] == {"BTC/TRADE": 2.0}
        assert payload["limit_seconds"] == 5.0


class TestSilenceDetection:
    async def test_a_quiet_stream_produces_a_suspected_gap(self) -> None:
        monitor, clock, gaps, heartbeat, _ = build_monitor(silence=timedelta(seconds=10))
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        heartbeat.record_data(NOW)
        clock.advance_seconds(30)

        check = await monitor.check()
        assert len(check.silence_gaps) == 1
        assert check.silence_gaps[0].kind is GapKind.SILENCE
        assert check.silence_gaps[0].suspected

    async def test_the_same_silence_is_not_reported_twice(self) -> None:
        """An hour of quiet must not become an hour of duplicate gap rows."""
        monitor, clock, gaps, heartbeat, _ = build_monitor(silence=timedelta(seconds=10))
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        heartbeat.record_data(NOW)

        clock.advance_seconds(30)
        first = await monitor.check()
        clock.advance_seconds(30)
        second = await monitor.check()

        assert len(first.silence_gaps) == 1
        assert second.silence_gaps == ()

    async def test_new_gaps_are_handed_to_the_callback(self) -> None:
        recorded: list[GapReport] = []

        async def collect(gap: GapReport) -> None:
            recorded.append(gap)

        monitor, clock, gaps, heartbeat, _ = build_monitor(silence=timedelta(seconds=10))
        monitor.on_gap = collect
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        heartbeat.record_data(NOW)
        clock.advance_seconds(30)
        await monitor.check()
        assert len(recorded) == 1

    async def test_a_silent_connection_is_detected(self) -> None:
        monitor, clock, _, heartbeat, _ = build_monitor(silence=timedelta(seconds=10))
        heartbeat.record_data(NOW)
        clock.advance_seconds(30)
        check = await monitor.check()
        assert check.connection_silent
        assert not check.is_healthy


class TestStateReflection:
    async def test_staleness_moves_the_recorder_to_degraded(self) -> None:
        """A recorder reporting HEALTHY on hour-old data is the silent failure."""
        monitor, clock, gaps, heartbeat, machine = build_monitor(staleness=timedelta(seconds=5))
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        heartbeat.record_data(NOW)
        clock.advance_seconds(20)

        await monitor.check()
        assert machine.state is RecorderState.DEGRADED

    async def test_recovery_returns_to_healthy(self) -> None:
        monitor, clock, gaps, heartbeat, machine = build_monitor(
            staleness=timedelta(seconds=5), silence=timedelta(seconds=10)
        )
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        heartbeat.record_data(NOW)
        clock.advance_seconds(20)
        await monitor.check()
        # Compared by value rather than identity: the field is mutated between
        # the two assertions, which an identity narrowing cannot express.
        assert machine.state.value == RecorderState.DEGRADED.value

        gaps.observe(asset="BTC", event_type="TRADE", sequence=2, seen_at=clock.now())
        heartbeat.record_data(clock.now())
        clock.advance_seconds(1)
        await monitor.check()
        assert machine.state.value == RecorderState.HEALTHY.value

    async def test_the_degradation_reason_is_specific(self) -> None:
        monitor, clock, gaps, heartbeat, machine = build_monitor(
            staleness=timedelta(seconds=5), silence=timedelta(seconds=600)
        )
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        heartbeat.record_data(NOW)
        clock.advance_seconds(20)
        await monitor.check()
        assert "BTC/TRADE" in machine.history[-1].reason

    async def test_a_reconnecting_recorder_is_left_alone(self) -> None:
        """Only the source knows whether its socket is usable."""
        monitor, clock, gaps, heartbeat, machine = build_monitor(state=RecorderState.RECONNECTING)
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        heartbeat.record_data(NOW)
        clock.advance_seconds(60)
        await monitor.check()
        assert machine.state is RecorderState.RECONNECTING


class TestMonitorLoop:
    async def test_the_loop_stops_when_asked(self) -> None:
        monitor, *_ = build_monitor()
        monitor.interval = timedelta(milliseconds=10)
        stop = asyncio.Event()

        task = asyncio.create_task(monitor.run(stop=stop))
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=1)

        assert monitor.checks >= 2


class TestGapRegistry:
    async def sequence_gap(self) -> GapReport:
        return GapDetector().report_disconnect(
            asset="BTC", event_type="TRADE", disconnected_at=NOW, reason="socket closed"
        )

    async def test_a_registered_gap_starts_pending(self) -> None:
        registry = InMemoryGapRegistry()
        gap = await registry.register(await self.sequence_gap())
        assert gap.backfill_status is BackfillStatus.PENDING
        assert gap.is_open

    async def test_a_proven_gap_is_material_a_suspected_one_unknown(self) -> None:
        registry = InMemoryGapRegistry()
        proven = await registry.register(await self.sequence_gap())
        assert proven.quality_impact is QualityImpact.MATERIAL

        suspected = GapReport(
            gap_id="suspected-1",
            kind=GapKind.SILENCE,
            asset="BTC",
            event_type="BBO",
            gap_start=NOW,
            gap_end=None,
            detection_reason="quiet",
            suspected=True,
        )
        assert (await registry.register(suspected)).quality_impact is QualityImpact.UNKNOWN

    async def test_registering_twice_is_idempotent(self) -> None:
        registry = InMemoryGapRegistry()
        report = await self.sequence_gap()
        first = await registry.register(report)
        second = await registry.register(report)
        assert first == second
        assert len(await registry.open_gaps()) == 1

    async def test_an_open_gap_has_no_duration(self) -> None:
        """Elapsed-so-far would make an ongoing outage look bounded."""
        registry = InMemoryGapRegistry()
        gap = await registry.register(await self.sequence_gap())
        assert gap.duration_seconds is None

    async def test_recovery_closes_the_gap_and_clears_impact(self) -> None:
        registry = InMemoryGapRegistry()
        gap = await registry.register(await self.sequence_gap())
        closed = await registry.close(
            gap.gap_id,
            ended_at=NOW + timedelta(seconds=30),
            status=BackfillStatus.RECOVERED,
            resolution="backfilled from venue history",
        )
        assert closed.backfill_status is BackfillStatus.RECOVERED
        assert closed.quality_impact is QualityImpact.NONE
        assert closed.duration_seconds == 30.0
        assert not closed.is_open

    async def test_an_unrecoverable_gap_stays_visible(self) -> None:
        """The honest outcome for most venue gaps: bounded API history."""
        registry = InMemoryGapRegistry()
        gap = await registry.register(await self.sequence_gap())
        closed = await registry.close(
            gap.gap_id,
            ended_at=NOW + timedelta(seconds=30),
            status=BackfillStatus.UNRECOVERABLE,
            resolution="venue exposes only the 10,000 most recent fills",
        )
        assert closed.quality_impact is QualityImpact.MATERIAL
        assert closed.backfill_status.leaves_data_missing

    async def test_partial_recovery_still_leaves_data_missing(self) -> None:
        assert BackfillStatus.PARTIAL.leaves_data_missing
        assert not BackfillStatus.RECOVERED.leaves_data_missing

    async def test_closing_before_the_start_is_refused(self) -> None:
        registry = InMemoryGapRegistry()
        gap = await registry.register(await self.sequence_gap())
        with pytest.raises(ValueError, match="precedes"):
            await registry.close(
                gap.gap_id,
                ended_at=NOW - timedelta(seconds=1),
                status=BackfillStatus.RECOVERED,
                resolution="impossible",
            )

    async def test_closing_an_unknown_gap_is_refused(self) -> None:
        registry = InMemoryGapRegistry()
        with pytest.raises(KeyError, match="not registered"):
            await registry.close(
                "absent",
                ended_at=NOW,
                status=BackfillStatus.RECOVERED,
                resolution="x",
            )

    async def test_an_attempt_is_counted(self) -> None:
        registry = InMemoryGapRegistry()
        gap = await registry.register(await self.sequence_gap())
        after = await registry.record_attempt(gap.gap_id, outcome="venue returned nothing")
        assert after.backfill_attempts == 1
        assert after.backfill_status is BackfillStatus.IN_PROGRESS
        assert after.is_open

    async def test_the_summary_reports_missing_data(self) -> None:
        registry = InMemoryGapRegistry()
        first = await registry.register(await self.sequence_gap())
        await registry.register(
            GapReport(
                gap_id="second",
                kind=GapKind.SEQUENCE,
                asset="BTC",
                event_type="BBO",
                gap_start=NOW,
                gap_end=NOW + timedelta(seconds=5),
                detection_reason="jump",
            )
        )
        await registry.close(
            first.gap_id,
            ended_at=NOW + timedelta(seconds=10),
            status=BackfillStatus.RECOVERED,
            resolution="recovered",
        )

        summary = await registry.summary()
        assert summary.total == 2
        assert summary.recovered == 1
        assert summary.open_gaps == 1
        assert summary.has_missing_data
        assert summary.by_stream == {"BTC/BBO": 1, "BTC/TRADE": 1}
        assert summary.longest_seconds == 10.0

    async def test_a_registry_with_everything_recovered_reports_no_missing_data(
        self,
    ) -> None:
        registry = InMemoryGapRegistry()
        gap = await registry.register(await self.sequence_gap())
        await registry.close(
            gap.gap_id,
            ended_at=NOW + timedelta(seconds=1),
            status=BackfillStatus.RECOVERED,
            resolution="recovered",
        )
        assert not (await registry.summary()).has_missing_data


class TestPersistingGapRegistry:
    """The monitor's silences have to reach the store, not just the report.

    A run that is killed never prints its report, and that is how a
    twenty-six-minute outage ended up recorded nowhere: the data showed the
    hole and `data_gaps` was empty, so "did the monitor notice?" had no
    answer either way.
    """

    def silence_gap(self, *, asset: str = "BTC") -> GapReport:
        return GapReport(
            gap_id=f"gap-{asset}",
            kind=GapKind.SILENCE,
            asset=asset,
            event_type="TRADE",
            gap_start=NOW,
            gap_end=None,
            detection_reason="no message for 1560s, threshold 30s",
            suspected=True,
        )

    async def test_registering_writes_the_gap_to_the_sink(self) -> None:
        sink = InMemorySink()
        registry = PersistingGapRegistry(sink=sink)
        await registry.register(self.silence_gap())
        assert [gap.gap_id for gap in sink.gaps] == ["gap-BTC"]
        assert registry.persist_failures == 0

    async def test_the_gap_is_still_registered_when_the_store_refuses(self) -> None:
        """Losing the row is bad; losing the monitor with it is worse."""

        class RefusingSink(InMemorySink):
            async def write_gap(self, gap: GapReport) -> None:
                raise OSError(f"simulated gap registry failure for {gap.gap_id}")

        registry = PersistingGapRegistry(sink=RefusingSink())
        registered = await registry.register(self.silence_gap())
        assert registered.is_open
        assert registry.persist_failures == 1
        assert (await registry.summary()).total == 1

    async def test_the_monitor_persists_the_silence_it_detects(self) -> None:
        """End to end: a quiet stream becomes a row without the run ending."""
        sink = InMemorySink()
        registry = PersistingGapRegistry(sink=sink)
        monitor, clock, gaps, heartbeat, _ = build_monitor(silence=timedelta(seconds=10))
        monitor.on_gap = registry.register
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        heartbeat.record_data(NOW)
        clock.advance_seconds(1560)

        await monitor.check()

        assert len(sink.gaps) == 1
        assert sink.gaps[0].kind is GapKind.SILENCE
        assert sink.gaps[0].gap_start == NOW
        assert sink.gaps[0].gap_end is None

    async def test_one_outage_is_one_row_however_long_it_lasts(self) -> None:
        sink = InMemorySink()
        registry = PersistingGapRegistry(sink=sink)
        monitor, clock, gaps, heartbeat, _ = build_monitor(silence=timedelta(seconds=10))
        monitor.on_gap = registry.register
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        heartbeat.record_data(NOW)

        for _ in range(26):
            clock.advance_seconds(60)
            await monitor.check()

        assert len(sink.gaps) == 1


class TestAdaptiveSilenceThreshold:
    """The threshold has to follow the stream, because the stream moves.

    Measured over 15 hours of BTC, the quote rate ran about ten times higher at
    14:00 than at 21:00, and trades with it. One fixed threshold reported
    hundreds of overnight silences that were the market being quiet, and a
    threshold loose enough for the quiet hours would sleep through a real
    midday outage.
    """

    def stream(self, *, interval: float, count: int = 40) -> GapDetector:
        gaps = GapDetector(silence_threshold=timedelta(seconds=5))
        for i in range(count):
            gaps.observe(
                asset="BTC",
                event_type="TRADE",
                sequence=None,
                seen_at=NOW + timedelta(seconds=i * interval),
            )
        return gaps

    def test_a_stream_with_no_rhythm_yet_is_judged_at_the_floor(self) -> None:
        gaps = GapDetector(silence_threshold=timedelta(seconds=5))
        gaps.observe(asset="BTC", event_type="TRADE", sequence=None, seen_at=NOW)
        assert gaps.threshold_for("BTC", "TRADE") == timedelta(seconds=5)

    def test_a_slow_stream_earns_a_looser_threshold(self) -> None:
        busy = self.stream(interval=1.0).threshold_for("BTC", "TRADE")
        quiet = self.stream(interval=10.0).threshold_for("BTC", "TRADE")
        assert quiet > busy

    def test_the_threshold_never_drops_below_the_floor(self) -> None:
        """A fast stream must not become twitchy enough to report every hiccup."""
        gaps = self.stream(interval=0.05)
        assert gaps.threshold_for("BTC", "TRADE") == timedelta(seconds=5)

    def test_the_threshold_never_rises_above_the_ceiling(self) -> None:
        """A stream that has gone slow must not become blind to an outage."""
        gaps = GapDetector(
            silence_threshold=timedelta(seconds=5), silence_ceiling=timedelta(seconds=60)
        )
        for i in range(60):
            gaps.observe(
                asset="BTC", event_type="TRADE", sequence=None, seen_at=NOW + timedelta(minutes=i)
            )
        assert gaps.threshold_for("BTC", "TRADE") == timedelta(seconds=60)

    def test_a_quiet_market_at_its_own_pace_is_not_a_gap(self) -> None:
        """The overnight false positives, stated as a test."""
        gaps = self.stream(interval=10.0)
        last = NOW + timedelta(seconds=39 * 10)
        assert gaps.check_silence(now=last + timedelta(seconds=35)) == ()

    def test_an_outage_ten_times_the_rhythm_still_reports(self) -> None:
        gaps = self.stream(interval=10.0)
        last = NOW + timedelta(seconds=39 * 10)
        reports = gaps.check_silence(now=last + timedelta(seconds=300))
        assert len(reports) == 1
        assert reports[0].kind is GapKind.SILENCE


class TestSilenceClosure:
    """An open gap says data is still missing. Most of them are not.

    Until this existed the monitor only ever opened silences. The registry
    filled with hundreds of open rows, and M4 decides a dataset's quality by
    whether any gap overlapping it is open — so every dataset built over that
    period would have been declared degraded on the strength of a stream being
    quiet for thirty-one seconds overnight.
    """

    def build(self) -> tuple[Monitor, ManualClock, GapDetector, list[GapReport]]:
        closed: list[GapReport] = []

        async def collect(gap: GapReport) -> None:
            closed.append(gap)

        monitor, clock, gaps, heartbeat, _ = build_monitor(silence=timedelta(seconds=10))
        monitor.on_resume = collect
        gaps.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        heartbeat.record_data(NOW)
        return monitor, clock, gaps, closed

    async def test_a_resumed_stream_closes_its_silence(self) -> None:
        monitor, clock, gaps, closed = self.build()
        clock.advance_seconds(30)
        await monitor.check()
        assert len(monitor.open_silences) == 1

        resumed_at = NOW + timedelta(seconds=40)
        gaps.observe(asset="BTC", event_type="TRADE", sequence=2, seen_at=resumed_at)
        clock.advance_seconds(5)
        await monitor.check()

        assert monitor.open_silences == {}
        assert len(closed) == 1
        assert closed[0].gap_end == resumed_at

    async def test_a_stream_still_quiet_keeps_its_gap_open(self) -> None:
        monitor, clock, _, closed = self.build()
        clock.advance_seconds(30)
        await monitor.check()
        clock.advance_seconds(30)
        await monitor.check()
        assert len(monitor.open_silences) == 1
        assert closed == []

    async def test_a_second_outage_on_the_same_stream_is_its_own_gap(self) -> None:
        monitor, clock, gaps, closed = self.build()
        clock.advance_seconds(30)
        await monitor.check()

        resumed_at = NOW + timedelta(seconds=40)
        gaps.observe(asset="BTC", event_type="TRADE", sequence=2, seen_at=resumed_at)
        clock.advance_seconds(5)
        await monitor.check()

        # Long enough to clear the threshold this stream has earned. Two
        # messages forty seconds apart is a slow rhythm, and the detector now
        # judges it against that rather than against the floor — which is the
        # whole point, and is why sixty seconds is no longer an outage here.
        clock.advance_seconds(350)
        second = await monitor.check()
        assert len(second.silence_gaps) == 1
        assert second.silence_gaps[0].gap_start == resumed_at
        assert len(closed) == 1

    async def test_the_registry_records_the_closure_as_recovered(self) -> None:
        """Recovered rather than unrecoverable: nothing was ever ours to lose."""
        sink = InMemorySink()
        registry = PersistingGapRegistry(sink=sink)
        monitor, clock, gaps, _ = self.build()
        monitor.on_gap = registry.register
        monitor.on_resume = registry.resume

        clock.advance_seconds(30)
        await monitor.check()
        gaps.observe(
            asset="BTC", event_type="TRADE", sequence=2, seen_at=NOW + timedelta(seconds=40)
        )
        clock.advance_seconds(5)
        await monitor.check()

        summary = await registry.summary()
        assert summary.total == 1
        assert summary.open_gaps == 0
        assert summary.recovered == 1
        assert not summary.has_missing_data
        # Opened and closed through the same sink, so the store sees both.
        assert len(sink.gaps) == 2
        assert sink.gaps[0].gap_end is None
        assert sink.gaps[1].gap_end is not None
