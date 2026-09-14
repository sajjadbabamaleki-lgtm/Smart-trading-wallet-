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
    QualityImpact,
)
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
