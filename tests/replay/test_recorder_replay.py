"""Recorder replay against recorded fixtures.

Build 0.1 Rev.1 §64 states the standard these tests are written to: a bad test
asserts "BTC should rise"; a good test asserts "given this recorded sequence of
messages, normalization must produce exactly these events."

Every test here drives the full pipeline — archive, parse, validate,
deduplicate, detect gaps, normalize, persist — with a `ManualClock` and an
in-memory sink, so the outcome depends on nothing but the input.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest

from libs.domain.clock import ManualClock
from libs.schemas.enums import DataQualityStatus, MarketEventType
from services.market_data.recorder import Recorder
from services.market_data.sinks import FailingSink, InMemorySink
from services.market_data.source import FixtureSource
from services.market_data.state import RecorderState

pytestmark = pytest.mark.replay

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/hyperliquid"
START = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)


async def record(fixture: str, sink: InMemorySink | FailingSink | None = None):  # type: ignore[no-untyped-def]
    clock = ManualClock(START)
    target = sink if sink is not None else InMemorySink()
    recorder = Recorder(
        source=FixtureSource(FIXTURES / fixture, clock),
        sink=target,
        clock=clock,
    )
    metrics = await recorder.run()
    return recorder, target, metrics


class TestWellFormedSession:
    async def test_every_frame_is_archived_raw(self) -> None:
        """Raw first, always — a normalization defect must not lose evidence."""
        _, sink, metrics = await record("btc_session.jsonl")
        assert metrics.messages_received == 8
        assert metrics.messages_archived == 8
        assert len(sink.raw) == 8

    async def test_raw_precedes_the_events_derived_from_it(self) -> None:
        _, sink, _ = await record("btc_session.jsonl")
        first_raw = sink.order.index(f"raw:{sink.raw[0].raw_id}")
        first_market = next(
            index for index, entry in enumerate(sink.order) if entry.startswith("market:")
        )
        assert first_raw < first_market

    async def test_control_frames_produce_no_market_data(self) -> None:
        _, _sink, metrics = await record("btc_session.jsonl")
        # A subscription acknowledgement and a pong.
        assert metrics.control_frames == 2

    async def test_all_four_channels_normalize(self) -> None:
        _, sink, _ = await record("btc_session.jsonl")
        types = {event.event_type for event in sink.market_events}
        assert MarketEventType.TRADE in types
        assert MarketEventType.BBO in types
        assert MarketEventType.L2_SNAPSHOT in types
        assert MarketEventType.FUNDING in types
        assert MarketEventType.OPEN_INTEREST in types
        assert MarketEventType.MARK_PRICE in types

    async def test_identified_trades_produce_trader_events(self) -> None:
        _, sink, metrics = await record("btc_session.jsonl")
        # Three trades, each with two wallets.
        assert metrics.trader_events_written == 6
        assert {event.wallet for event in sink.trader_events} == {
            "0xwallet_a",
            "0xwallet_b",
            "0xwallet_c",
            "0xwallet_d",
        }

    async def test_every_event_references_its_raw_frame(self) -> None:
        """Which is what makes re-derivation possible."""
        _, sink, _ = await record("btc_session.jsonl")
        archived = {frame.raw_id for frame in sink.raw}
        for event in sink.market_events:
            assert event.raw_reference in archived
        for trader_event in sink.trader_events:
            assert trader_event.raw_reference in archived

    async def test_events_are_classified_rather_than_left_unknown(self) -> None:
        """Unknown quality must never silently become valid research data."""
        _, sink, _ = await record("btc_session.jsonl")
        assert all(
            event.quality_status is not DataQualityStatus.UNKNOWN for event in sink.market_events
        )

    async def test_prices_survive_the_pipeline_exactly(self) -> None:
        _, sink, _ = await record("btc_session.jsonl")
        trades = [
            event for event in sink.market_events if event.event_type is MarketEventType.TRADE
        ]
        assert trades[0].price == Decimal("60000.5")
        assert trades[0].quantity == Decimal("0.01")

    async def test_the_recorder_ends_healthy(self) -> None:
        recorder, _, _ = await record("btc_session.jsonl")
        assert recorder.machine.state is RecorderState.HEALTHY

    async def test_the_state_path_is_recorded(self) -> None:
        recorder, _, _ = await record("btc_session.jsonl")
        assert [t.current for t in recorder.machine.history] == [
            RecorderState.CONNECTING,
            RecorderState.CONNECTED,
            RecorderState.SUBSCRIBING,
            RecorderState.HEALTHY,
        ]

    async def test_the_sink_is_flushed_at_the_end(self) -> None:
        _, sink, _ = await record("btc_session.jsonl")
        assert sink.flushes == 1


class TestDeterminism:
    async def test_two_runs_produce_identical_output(self) -> None:
        """The core replay guarantee (Build 0.1 Rev.2 §22)."""
        _, first, first_metrics = await record("btc_session.jsonl")
        _, second, second_metrics = await record("btc_session.jsonl")

        assert first_metrics.as_dict() == second_metrics.as_dict()

        def comparable(events: Sequence[Any]) -> list[dict[str, Any]]:
            return [event.model_dump(exclude={"event_id", "raw_reference"}) for event in events]

        assert comparable(first.market_events) == comparable(second.market_events)
        assert comparable(first.trader_events) == comparable(second.trader_events)

    async def test_raw_payloads_are_byte_identical_across_runs(self) -> None:
        _, first, _ = await record("btc_session.jsonl")
        _, second, _ = await record("btc_session.jsonl")
        assert [frame.payload for frame in first.raw] == [frame.payload for frame in second.raw]
        assert [frame.payload_sha256 for frame in first.raw] == [
            frame.payload_sha256 for frame in second.raw
        ]

    async def test_replay_does_not_depend_on_the_wall_clock(self) -> None:
        """A replay run tomorrow must produce today's timestamps."""
        _, sink, _ = await record("btc_session.jsonl")
        assert all(event.timestamps.local_receive_time == START for event in sink.market_events)


class TestMalformedFrames:
    async def test_bad_frames_are_counted_not_fatal(self) -> None:
        """One malformed message must not become a total outage."""
        recorder, _sink, metrics = await record("btc_malformed.jsonl")
        assert metrics.messages_received == 10
        assert metrics.messages_invalid > 0
        assert recorder.machine.state.is_recording

    async def test_unparseable_frames_are_still_archived(self) -> None:
        """An unparseable frame is evidence, and the only copy."""
        _, sink, metrics = await record("btc_malformed.jsonl")
        assert metrics.messages_archived == 10
        assert any(frame.payload == "not json at all" for frame in sink.raw)

    async def test_an_unparseable_frame_is_archived_as_unknown_channel(self) -> None:
        _, sink, _ = await record("btc_malformed.jsonl")
        unknown = [frame for frame in sink.raw if frame.channel == "unknown"]
        assert unknown

    async def test_the_one_valid_frame_in_the_file_is_recorded(self) -> None:
        """Tolerance is specific: unknown fields pass, bad values do not."""
        _, sink, _ = await record("btc_malformed.jsonl")
        assert len(sink.market_events) == 1
        assert sink.market_events[0].venue_event_id == "9001"

    async def test_no_partial_events_are_written_for_rejected_frames(self) -> None:
        _, sink, metrics = await record("btc_malformed.jsonl")
        assert metrics.market_events_written == len(sink.market_events)


class TestDuplicates:
    async def test_a_redelivered_frame_is_dropped(self) -> None:
        _, _sink, metrics = await record("btc_duplicates.jsonl")
        assert metrics.duplicates_dropped == 2

    async def test_identical_trades_with_distinct_ids_are_both_kept(self) -> None:
        """Understating volume would be an invisible corruption."""
        _, sink, _ = await record("btc_duplicates.jsonl")
        trades = [
            event for event in sink.market_events if event.event_type is MarketEventType.TRADE
        ]
        assert [event.venue_event_id for event in trades] == ["2001", "2002"]

    async def test_duplicates_are_still_archived_raw(self) -> None:
        """Dedup is a normalization decision, not a reason to lose the frame."""
        _, _sink, metrics = await record("btc_duplicates.jsonl")
        assert metrics.messages_archived == 5


class TestGapDetection:
    """A jump in `tid` is not a gap, and this is where that is enforced.

    These tests previously asserted the opposite, on a fixture whose `tid`s were
    invented as consecutive integers. The real venue never sends those:
    Hyperliquid documents `tid` as a 50-bit hash of the buyer's and seller's
    order ids. The first live BTC recording reported gaps of ten trillion
    messages, several times a minute, because the distance between two hashes
    was being read as a count of missing messages.

    Sequence-gap detection itself is unchanged and still covered, driven
    directly with a real sequence in `tests/unit/test_recorder_components.py`.
    What changed is that the Hyperliquid trade channel no longer claims to
    publish one, because it does not.
    """

    async def test_a_jump_in_tid_is_not_reported_as_a_gap(self) -> None:
        _, sink, metrics = await record("btc_tid_jump.jsonl")
        assert metrics.gaps_detected == 0
        assert sink.gaps == []

    async def test_the_trades_either_side_of_the_jump_are_all_recorded(self) -> None:
        """A false gap must not come at the cost of dropping real trades."""
        recorder, sink, metrics = await record("btc_tid_jump.jsonl")
        assert metrics.market_events_written == 4
        assert [event.venue_event_id for event in sink.market_events] == [
            "3001",
            "3002",
            "3007",
            "3008",
        ]
        assert recorder.machine.state.is_recording

    async def test_the_jump_still_leaves_each_trade_distinctly_identified(self) -> None:
        """Identity survives; only the ordering claim was withdrawn."""
        _, sink, _ = await record("btc_tid_jump.jsonl")
        ids = [event.venue_event_id for event in sink.market_events]
        assert len(set(ids)) == len(ids)
        assert all(event.sequence is None for event in sink.market_events)


class TestPersistenceFailure:
    async def test_a_failed_raw_write_degrades_the_recorder(self) -> None:
        """Losing data silently on a store rejection is the failure to catch."""
        sink = FailingSink(fail_raw_after=2)
        recorder, _, metrics = await record("btc_session.jsonl", sink)
        assert metrics.persist_failures > 0
        assert recorder.machine.state is RecorderState.DEGRADED

    async def test_no_orphan_events_are_written_without_their_raw_frame(self) -> None:
        sink = FailingSink(fail_raw_after=2)
        _, _wrapper, metrics = await record("btc_session.jsonl", sink)
        assert metrics.messages_archived == 2
        # Every written event must trace to one of the two archived frames.
        archived = {frame.raw_id for frame in sink.inner.raw}
        for event in sink.inner.market_events:
            assert event.raw_reference in archived

    async def test_an_event_store_failure_is_recorded_and_survived(self) -> None:
        sink = FailingSink(fail_events_after=1)
        recorder, _, metrics = await record("btc_session.jsonl", sink)
        assert metrics.persist_failures > 0
        assert recorder.machine.state is RecorderState.DEGRADED
        # Archiving continues even when the normalized store is refusing.
        assert metrics.messages_archived == 8


class TestFixtureIntegrity:
    """Fixtures are test input; a broken one weakens every test that uses it.

    Two lines in `btc_malformed.jsonl` are deliberately unparseable, because
    that file exists to prove the recorder survives them. Everything else must
    be valid JSON — during development a missing brace in `btc_session.jsonl`
    silently reduced the well-formed session to a malformed one, and the tests
    that noticed reported a confusing downstream symptom rather than the cause.
    """

    INTENTIONALLY_INVALID: ClassVar[set[tuple[str, int]]] = {("btc_malformed.jsonl", 1)}

    def test_fixture_lines_are_valid_json_except_where_documented(self) -> None:
        unexpected: list[str] = []
        for path in sorted(FIXTURES.glob("*.jsonl")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    json.loads(line)
                except json.JSONDecodeError as exc:
                    if (path.name, number) not in self.INTENTIONALLY_INVALID:
                        unexpected.append(f"{path.name}:{number}: {exc}")
        assert unexpected == [], "\n".join(unexpected)

    def test_every_fixture_is_documented(self) -> None:
        readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
        for path in sorted(FIXTURES.glob("*.jsonl")):
            assert path.name in readme, f"{path.name} is not described in the README"

    def test_session_fixture_timestamps_precede_the_replay_clock(self) -> None:
        """Otherwise the quality engine correctly rejects them as skewed,
        and the fixture tests a failure path while appearing to test success."""

        start_ms = int(START.timestamp() * 1000)
        for line in (FIXTURES / "btc_session.jsonl").read_text().splitlines():
            frame = json.loads(line)
            data = frame.get("data")
            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                if isinstance(entry, dict) and "time" in entry:
                    assert entry["time"] <= start_ms, f"{entry['time']} is after the clock"
