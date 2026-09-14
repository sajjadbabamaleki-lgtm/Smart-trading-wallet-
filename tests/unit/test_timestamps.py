"""Timestamp and latency models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from libs.domain.timestamps import EventTimestamps, LatencyBreakdown

AWARE = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)


def test_receive_fields_are_mandatory() -> None:
    with pytest.raises(ValidationError):
        EventTimestamps(local_receive_time=AWARE)  # type: ignore[call-arg]


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EventTimestamps(
            local_receive_time=datetime(2026, 9, 14, 12, 0, 0),
            local_receive_monotonic_ns=0,
        )


def test_venue_fields_stay_empty_rather_than_invented() -> None:
    stamps = EventTimestamps(local_receive_time=AWARE, local_receive_monotonic_ns=0)
    assert stamps.consensus_time is None
    assert stamps.exchange_time is None
    assert stamps.source_to_receive_seconds is None


def test_best_event_time_prefers_consensus_then_falls_back() -> None:
    consensus = AWARE - timedelta(milliseconds=40)
    exchange = AWARE - timedelta(milliseconds=20)

    both = EventTimestamps(
        local_receive_time=AWARE,
        local_receive_monotonic_ns=0,
        consensus_time=consensus,
        exchange_time=exchange,
    )
    assert both.best_event_time == consensus

    exchange_only = EventTimestamps(
        local_receive_time=AWARE, local_receive_monotonic_ns=0, exchange_time=exchange
    )
    assert exchange_only.best_event_time == exchange

    neither = EventTimestamps(local_receive_time=AWARE, local_receive_monotonic_ns=0)
    assert neither.best_event_time == AWARE


def test_source_to_receive_delay_is_measured() -> None:
    stamps = EventTimestamps(
        local_receive_time=AWARE,
        local_receive_monotonic_ns=0,
        consensus_time=AWARE - timedelta(milliseconds=250),
    )
    assert stamps.source_to_receive_seconds == pytest.approx(0.25)


def test_negative_delay_is_reported_not_clamped() -> None:
    """Clock skew is a condition to monitor, not to hide."""
    stamps = EventTimestamps(
        local_receive_time=AWARE,
        local_receive_monotonic_ns=0,
        exchange_time=AWARE + timedelta(milliseconds=100),
    )
    assert stamps.source_to_receive_seconds == pytest.approx(-0.1)


def test_timestamps_are_immutable() -> None:
    stamps = EventTimestamps(local_receive_time=AWARE, local_receive_monotonic_ns=0)
    with pytest.raises(ValidationError):
        stamps.local_receive_monotonic_ns = 5  # type: ignore[misc]


def test_latency_sums_controlled_stages() -> None:
    breakdown = LatencyBreakdown(
        correlation_id="cor_test",
        receive_to_feature_ns=1_000,
        feature_to_decision_ns=2_000,
        decision_to_order_ns=3_000,
        order_to_ack_ns=90_000,
    )
    assert breakdown.receive_to_order_ns == 6_000


def test_partial_latency_is_none_rather_than_understated() -> None:
    """A partial sum would understate delay — the error this exists to prevent."""
    breakdown = LatencyBreakdown(
        correlation_id="cor_test",
        receive_to_feature_ns=1_000,
        decision_to_order_ns=3_000,
    )
    assert breakdown.receive_to_order_ns is None
