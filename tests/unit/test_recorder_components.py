"""State machine, quality engine, gap detection, dedup and heartbeat."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from libs.domain.timestamps import EventTimestamps
from libs.schemas.enums import DataQualityStatus, MarketEventType, Side
from libs.schemas.market_event import MarketEvent
from services.market_data.dedup import DuplicateDetector
from services.market_data.gaps import GapDetector, GapKind, Heartbeat
from services.market_data.quality import QualityEngine
from services.market_data.state import RecorderState, StateMachine, TransitionError

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)


def event(
    *,
    event_type: MarketEventType = MarketEventType.TRADE,
    received_at: datetime = NOW,
    exchange_time: datetime | None = NOW,
    sequence: int | None = None,
    price: Decimal | None = Decimal(60000),
    quantity: Decimal | None = Decimal("0.01"),
    bid: Decimal | None = None,
    ask: Decimal | None = None,
    asset: str = "BTC",
) -> MarketEvent:
    return MarketEvent(
        event_id=f"evt_{sequence or 0}_{received_at.timestamp()}",
        source="test",
        venue="hyperliquid",
        asset=asset,
        instrument=f"{asset}-PERP",
        event_type=event_type,
        timestamps=EventTimestamps(
            local_receive_time=received_at,
            local_receive_monotonic_ns=0,
            exchange_time=exchange_time,
        ),
        sequence=sequence,
        price=price if event_type is MarketEventType.TRADE else None,
        quantity=quantity if event_type is MarketEventType.TRADE else None,
        side=Side.BUY if event_type is MarketEventType.TRADE else None,
        bid_price=bid,
        ask_price=ask,
    )


class TestStateMachine:
    def test_the_happy_path_reaches_healthy(self) -> None:
        machine = StateMachine()
        for target in (
            RecorderState.CONNECTING,
            RecorderState.CONNECTED,
            RecorderState.SUBSCRIBING,
            RecorderState.HEALTHY,
        ):
            machine.transition(target, at=NOW, reason="test")
        assert machine.state is RecorderState.HEALTHY
        assert machine.is_recording

    def test_an_undeclared_transition_raises(self) -> None:
        """No hidden reconnect behaviour (Build 0.1 Rev.1 §27)."""
        machine = StateMachine()
        with pytest.raises(TransitionError, match="not a declared transition"):
            machine.transition(RecorderState.HEALTHY, at=NOW, reason="skip ahead")

    def test_reconnecting_cannot_jump_straight_to_healthy(self) -> None:
        """A restored socket still has to resubscribe."""
        machine = StateMachine(state=RecorderState.RECONNECTING)
        assert not machine.can_transition(RecorderState.HEALTHY)
        assert machine.can_transition(RecorderState.CONNECTING)

    def test_failed_is_terminal(self) -> None:
        machine = StateMachine(state=RecorderState.HEALTHY)
        machine.transition(RecorderState.FAILED, at=NOW, reason="fatal")
        assert machine.state.is_terminal
        for state in RecorderState:
            assert not machine.can_transition(state)

    def test_degraded_still_counts_as_recording(self) -> None:
        """Data is still flowing; something about it is wrong."""
        assert RecorderState.DEGRADED.is_recording
        assert not RecorderState.RECONNECTING.is_recording

    def test_history_records_every_transition(self) -> None:
        machine = StateMachine()
        machine.transition(RecorderState.CONNECTING, at=NOW, reason="one")
        machine.transition(RecorderState.CONNECTED, at=NOW, reason="two")
        assert [t.reason for t in machine.history] == ["one", "two"]
        assert machine.history[0].previous is RecorderState.STARTING

    def test_history_is_bounded(self) -> None:
        """A recorder reconnecting for a week must not grow without bound."""
        machine = StateMachine(state=RecorderState.HEALTHY, history_limit=4)
        for index in range(20):
            target = RecorderState.DEGRADED if index % 2 == 0 else RecorderState.HEALTHY
            machine.transition(target, at=NOW, reason=str(index))
        assert len(machine.history) == 4
        assert machine.history[-1].reason == "19"

    def test_a_callback_observes_transitions(self) -> None:
        seen: list[str] = []
        machine = StateMachine(on_transition=lambda t: seen.append(t.current.value))
        machine.transition(RecorderState.CONNECTING, at=NOW, reason="test")
        assert seen == ["CONNECTING"]


class TestQualityEngine:
    def test_a_clean_event_is_valid(self) -> None:
        verdict = QualityEngine().validate(event(), now=NOW)
        assert verdict.status is DataQualityStatus.VALID
        assert verdict.findings == ()

    def test_an_implausible_source_delay_is_invalid(self) -> None:
        verdict = QualityEngine().validate(event(exchange_time=NOW - timedelta(minutes=5)), now=NOW)
        assert verdict.status is DataQualityStatus.INVALID
        assert any("source_delay" in finding for finding in verdict.findings)

    def test_clock_skew_is_a_warning_not_a_rejection(self) -> None:
        """Skew must be visible; it invalidates latency measurement."""
        verdict = QualityEngine().validate(
            event(exchange_time=NOW + timedelta(seconds=10)), now=NOW
        )
        assert verdict.status is DataQualityStatus.WARNING
        assert any("clock_skew" in finding for finding in verdict.findings)

    def test_small_skew_within_tolerance_is_clean(self) -> None:
        verdict = QualityEngine().validate(
            event(exchange_time=NOW + timedelta(milliseconds=500)), now=NOW
        )
        assert verdict.status is DataQualityStatus.VALID

    def test_a_receive_time_in_the_future_is_invalid(self) -> None:
        verdict = QualityEngine().validate(
            event(received_at=NOW + timedelta(seconds=5), exchange_time=None), now=NOW
        )
        assert verdict.status is DataQualityStatus.INVALID

    def test_an_implausible_spread_is_flagged_not_dropped(self) -> None:
        """It may be a real liquidity event; research must be able to find it."""
        verdict = QualityEngine().validate(
            event(
                event_type=MarketEventType.BBO,
                bid=Decimal(50000),
                ask=Decimal(70000),
            ),
            now=NOW,
        )
        assert verdict.status is DataQualityStatus.WARNING
        assert any("spread" in finding for finding in verdict.findings)

    def test_a_normal_spread_passes(self) -> None:
        verdict = QualityEngine().validate(
            event(
                event_type=MarketEventType.BBO,
                bid=Decimal("59999.5"),
                ask=Decimal("60000.5"),
            ),
            now=NOW,
        )
        assert verdict.status is DataQualityStatus.VALID

    def test_an_event_without_a_venue_timestamp_is_not_penalised(self) -> None:
        """activeAssetCtx supplies none; absence is not a defect."""
        verdict = QualityEngine().validate(event(exchange_time=None), now=NOW)
        assert verdict.status is DataQualityStatus.VALID

    def test_the_verdict_is_reproducible_from_the_event_alone(self) -> None:
        """Which is what makes a replay's verdicts match the live ones."""
        subject = event(exchange_time=NOW - timedelta(minutes=5))
        engine = QualityEngine()
        assert engine.validate(subject, now=NOW) == engine.validate(subject, now=NOW)


class TestDuplicateDetector:
    def test_the_same_venue_id_twice_is_a_duplicate(self) -> None:
        detector = DuplicateDetector()
        assert not detector.is_duplicate(event(sequence=1))
        assert detector.is_duplicate(event(sequence=1))

    def test_different_venue_ids_are_distinct(self) -> None:
        detector = DuplicateDetector()
        assert not detector.is_duplicate(event(sequence=1))
        assert not detector.is_duplicate(event(sequence=2))

    def test_identical_trades_with_distinct_ids_are_not_duplicates(self) -> None:
        """Two equal trades in one millisecond are ordinary market activity."""
        detector = DuplicateDetector()
        assert not detector.is_duplicate(event(sequence=1, price=Decimal(60000)))
        assert not detector.is_duplicate(event(sequence=2, price=Decimal(60000)))
        assert detector.stats.duplicates == 0

    def test_content_identity_is_used_when_no_venue_id_exists(self) -> None:
        detector = DuplicateDetector()
        quote = event(event_type=MarketEventType.BBO, bid=Decimal(99), ask=Decimal(101))
        assert not detector.is_duplicate(quote)
        assert detector.is_duplicate(quote)

    def test_different_event_types_do_not_collide(self) -> None:
        detector = DuplicateDetector()
        bbo = event(event_type=MarketEventType.BBO, bid=Decimal(99), ask=Decimal(101))
        snapshot = event(event_type=MarketEventType.L2_SNAPSHOT, bid=Decimal(99), ask=Decimal(101))
        assert not detector.is_duplicate(bbo)
        assert not detector.is_duplicate(snapshot)

    def test_different_assets_do_not_collide(self) -> None:
        detector = DuplicateDetector()
        assert not detector.is_duplicate(event(sequence=1, asset="BTC"))
        assert not detector.is_duplicate(event(sequence=1, asset="ETH"))

    def test_keys_expire_after_the_window(self) -> None:
        detector = DuplicateDetector(window=timedelta(seconds=10))
        assert not detector.is_duplicate(event(sequence=1, received_at=NOW))
        later = event(sequence=1, received_at=NOW + timedelta(seconds=30))
        assert not detector.is_duplicate(later)

    def test_expiry_follows_event_time_not_the_wall_clock(self) -> None:
        """So a replay evicts at the same points the live run did."""
        detector = DuplicateDetector(window=timedelta(seconds=10))
        detector.is_duplicate(event(sequence=1, received_at=NOW))
        detector.is_duplicate(event(sequence=2, received_at=NOW + timedelta(seconds=5)))
        assert detector.tracked == 2

    def test_capacity_is_bounded(self) -> None:
        detector = DuplicateDetector(capacity=10)
        for index in range(50):
            detector.is_duplicate(event(sequence=index))
        assert detector.tracked == 10
        assert detector.stats.evicted == 40

    def test_zero_capacity_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            DuplicateDetector(capacity=0)

    def test_stats_report_the_duplicate_fraction(self) -> None:
        detector = DuplicateDetector()
        detector.is_duplicate(event(sequence=1))
        detector.is_duplicate(event(sequence=1))
        assert detector.stats.seen == 2
        assert detector.stats.duplicate_fraction == 0.5


class TestGapDetector:
    def test_contiguous_sequences_produce_no_gap(self) -> None:
        detector = GapDetector()
        assert detector.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW) is None
        assert detector.observe(asset="BTC", event_type="TRADE", sequence=2, seen_at=NOW) is None

    def test_a_forward_jump_reports_a_definite_gap(self) -> None:
        detector = GapDetector()
        detector.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        gap = detector.observe(asset="BTC", event_type="TRADE", sequence=5, seen_at=NOW)
        assert gap is not None
        assert gap.kind is GapKind.SEQUENCE
        assert gap.expected_sequence == 2
        assert gap.actual_sequence == 5
        assert gap.missing_count == 3
        assert not gap.suspected

    def test_an_out_of_order_sequence_is_not_a_gap(self) -> None:
        """Delivery order is a different question from absence."""
        detector = GapDetector()
        detector.observe(asset="BTC", event_type="TRADE", sequence=5, seen_at=NOW)
        assert detector.observe(asset="BTC", event_type="TRADE", sequence=3, seen_at=NOW) is None

    def test_a_repeated_sequence_is_not_a_gap(self) -> None:
        detector = GapDetector()
        detector.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        assert detector.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW) is None

    def test_streams_are_tracked_independently(self) -> None:
        detector = GapDetector()
        detector.observe(asset="BTC", event_type="TRADE", sequence=10, seen_at=NOW)
        assert detector.observe(asset="BTC", event_type="BBO", sequence=1, seen_at=NOW) is None
        assert detector.observe(asset="ETH", event_type="TRADE", sequence=1, seen_at=NOW) is None

    def test_events_without_sequences_produce_no_gaps(self) -> None:
        detector = GapDetector()
        for _ in range(3):
            assert (
                detector.observe(asset="BTC", event_type="BBO", sequence=None, seen_at=NOW) is None
            )

    def test_silence_is_reported_as_suspected(self) -> None:
        """A quiet market and a broken socket look identical from inside."""
        detector = GapDetector(silence_threshold=timedelta(seconds=10))
        detector.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        reports = detector.check_silence(now=NOW + timedelta(seconds=60))
        assert len(reports) == 1
        assert reports[0].kind is GapKind.SILENCE
        assert reports[0].suspected
        assert reports[0].gap_end is None

    def test_a_recently_active_stream_is_not_reported(self) -> None:
        detector = GapDetector(silence_threshold=timedelta(seconds=30))
        detector.observe(asset="BTC", event_type="TRADE", sequence=1, seen_at=NOW)
        assert detector.check_silence(now=NOW + timedelta(seconds=5)) == ()

    def test_a_disconnect_gap_is_definite_and_open(self) -> None:
        detector = GapDetector()
        gap = detector.report_disconnect(
            asset="BTC", event_type="TRADE", disconnected_at=NOW, reason="socket closed"
        )
        assert gap.kind is GapKind.DISCONNECT
        assert not gap.suspected
        assert gap.gap_end is None


class TestHeartbeat:
    def test_a_connection_with_no_data_yet_is_not_silent(self) -> None:
        """Nothing has arrived, so nothing has stopped."""
        assert not Heartbeat().is_silent(now=NOW)

    def test_silence_is_detected_after_the_threshold(self) -> None:
        heartbeat = Heartbeat(threshold=timedelta(seconds=10))
        heartbeat.record_data(NOW)
        assert not heartbeat.is_silent(now=NOW + timedelta(seconds=5))
        assert heartbeat.is_silent(now=NOW + timedelta(seconds=15))

    def test_silence_duration_is_reported(self) -> None:
        heartbeat = Heartbeat()
        heartbeat.record_data(NOW)
        assert heartbeat.silence_seconds(now=NOW + timedelta(seconds=42)) == 42.0

    def test_reset_clears_liveness_but_keeps_the_count(self) -> None:
        heartbeat = Heartbeat()
        heartbeat.record_data(NOW)
        heartbeat.reset()
        assert heartbeat.last_data_at is None
        assert heartbeat.messages == 1
