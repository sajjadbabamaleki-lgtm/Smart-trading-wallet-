"""Replay determinism over captured sessions.

Build 0.1 Rev.1 §77 requires two things of replay, and this is where they are
checked rather than assumed: recorded events replay deterministically, and
replay does not depend on real wall-clock time.

Determinism is a property of the whole pipeline. No component's own test
establishes it — only running the pipeline twice and comparing does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from services.market_data.capture import CapturedSession, load_session
from services.market_data.replay import (
    VOLATILE_FIELDS,
    ReplayEngine,
    ReplayReport,
    _first_difference,
    verify_determinism,
)

pytestmark = pytest.mark.replay

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/hyperliquid"
ALL_CAPTURES = (
    "btc_capture.jsonl",
    "btc_session.jsonl",
    "btc_duplicates.jsonl",
    "btc_sequence_gap.jsonl",
    "btc_malformed.jsonl",
)


class TestDeterminism:
    @pytest.mark.parametrize("name", ALL_CAPTURES)
    async def test_every_fixture_replays_deterministically(self, name: str) -> None:
        comparison = await verify_determinism(load_session(FIXTURES / name))
        assert comparison.identical, comparison.render()

    async def test_a_capture_with_real_receipts_replays_deterministically(self) -> None:
        comparison = await verify_determinism(load_session(FIXTURES / "btc_capture.jsonl"))
        assert comparison.identical
        assert comparison.first_count > 0

    async def test_metrics_are_identical_across_runs(self) -> None:
        session = load_session(FIXTURES / "btc_capture.jsonl")
        engine = ReplayEngine(session)
        first = await engine.run()
        second = await engine.run()
        assert first.metrics.as_dict() == second.metrics.as_dict()

    async def test_only_event_ids_and_raw_references_differ(self) -> None:
        """Which is why the comparison excludes exactly those two fields."""
        session = load_session(FIXTURES / "btc_capture.jsonl")
        engine = ReplayEngine(session)
        first = await engine.run()
        second = await engine.run()

        left = first.market_events[0].model_dump(mode="json")
        right = second.market_events[0].model_dump(mode="json")
        differing = {key for key in left if left[key] != right[key]}
        assert differing <= VOLATILE_FIELDS


class TestIndependenceFromWallClock:
    async def test_replay_reports_the_session_time_not_today(self) -> None:
        session = load_session(FIXTURES / "btc_capture.jsonl")
        result = await ReplayEngine(session).run()
        span = session.span
        assert span is not None
        for event in result.market_events:
            assert span[0] <= event.timestamps.local_receive_time <= span[1]

    async def test_events_carry_the_captured_receipt_times(self) -> None:
        session = load_session(FIXTURES / "btc_capture.jsonl")
        result = await ReplayEngine(session).run()
        captured = {frame.receipt.local_receive_time for frame in session.frames}
        for event in result.market_events:
            assert event.timestamps.local_receive_time in captured

    async def test_a_years_old_session_replays_without_quality_complaints(self) -> None:
        """The verdict must come from the session's own timing, not from today."""
        session = load_session(FIXTURES / "btc_capture.jsonl")
        result = await ReplayEngine(session).run()
        assert result.metrics.quality_invalid == 0

    async def test_monotonic_readings_are_preserved_as_captured(self) -> None:
        session = load_session(FIXTURES / "btc_capture.jsonl")
        result = await ReplayEngine(session).run()
        assert any(
            event.timestamps.local_receive_monotonic_ns > 0 for event in result.market_events
        )


class TestReplayFindings:
    async def test_the_capture_header_reaches_the_report(self) -> None:
        session = load_session(FIXTURES / "btc_capture.jsonl")
        report = ReplayReport(result=await ReplayEngine(session).run())
        header = report.as_dict()["capture"]["header"]
        assert header is not None
        assert header["venue"] == "hyperliquid"
        assert header["assets"] == ["BTC"]

    async def test_a_headerless_fixture_reports_no_header(self) -> None:
        session = load_session(FIXTURES / "btc_session.jsonl")
        report = ReplayReport(result=await ReplayEngine(session).run())
        assert report.as_dict()["capture"]["header"] is None

    async def test_malformed_lines_are_surfaced_in_the_report(self) -> None:
        session = load_session(FIXTURES / "btc_malformed.jsonl")
        report = ReplayReport(result=await ReplayEngine(session).run())
        assert report.as_dict()["capture"]["malformed_lines"] == [1]

    async def test_the_gap_in_the_capture_is_detected_on_replay(self) -> None:
        session = load_session(FIXTURES / "btc_capture.jsonl")
        result = await ReplayEngine(session).run()
        # tid jumps 5002 -> 5006.
        assert len(result.gaps) == 1
        assert result.gaps[0].expected_sequence == 5003
        assert result.gaps[0].actual_sequence == 5006

    async def test_the_comparison_renders_a_verdict(self) -> None:
        comparison = await verify_determinism(load_session(FIXTURES / "btc_capture.jsonl"))
        assert "deterministic" in comparison.render()


class TestEmptySessions:
    async def test_replaying_a_session_with_no_frames_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="contains no frames"):
            await ReplayEngine(load_session(path)).run()


class TestDivergenceReporting:
    async def test_a_divergence_is_located_precisely(self) -> None:
        """A determinism failure must be diagnosable, not just reported."""
        left = [{"price": "1", "asset": "BTC"}, {"price": "2", "asset": "BTC"}]
        right = [{"price": "1", "asset": "BTC"}, {"price": "3", "asset": "BTC"}]
        message = _first_difference(left, right)
        assert message is not None
        assert "event 1" in message
        assert "price" in message

    async def test_a_count_mismatch_is_reported(self) -> None:
        message = _first_difference([{"a": 1}], [{"a": 1}, {"a": 2}])
        assert message is not None
        assert "count differs" in message

    async def test_identical_input_reports_no_difference(self) -> None:
        assert _first_difference([{"a": 1}], [{"a": 1}]) is None


class TestSessionSpan:
    def test_span_and_duration_agree(self) -> None:
        session = load_session(FIXTURES / "btc_capture.jsonl")
        span = session.span
        assert span is not None
        assert session.duration_seconds == pytest.approx((span[1] - span[0]).total_seconds())

    def test_an_empty_session_has_no_span(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        session = load_session(path)
        assert session.span is None
        assert session.duration_seconds == 0.0

    def test_the_capture_span_matches_its_header(self) -> None:
        session = load_session(FIXTURES / "btc_capture.jsonl")
        assert session.header is not None
        started = datetime.fromisoformat(session.header.started_at)
        span = session.span
        assert span is not None
        # The header is written when the session opens, before the first frame.
        assert started <= span[0]
        assert span[1] - started < timedelta(seconds=5)


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


class TestCapturedSessionShape:
    def test_frames_stay_in_file_order(self) -> None:
        """Sorting would hide a recorder that delivered frames out of order."""
        session: CapturedSession = load_session(FIXTURES / "btc_capture.jsonl")
        times = [frame.receipt.local_receive_time for frame in session.frames]
        assert times == sorted(times)
        assert times[0] == _utc("2026-09-14T11:59:59.912000+00:00")
