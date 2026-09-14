"""Tests for the acceptance verifier itself.

Task §15: the verifier must not become an untested source of false confidence.
These tests exist because a bug here does not produce a wrong number — it
produces a wrong *decision* about whether a milestone is accepted, which is
worse.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from services.market_data.acceptance import (
    AcceptanceReport,
    Decision,
    DeviationSeverity,
    MilestoneState,
    RoleAttribution,
    analyse_latency,
    analyse_schema,
    analyse_users,
    decide_m1,
    decide_m2,
)

CHANNELS = ("trades", "l2Book", "bbo", "activeAssetCtx")
NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)


def trade_frame(**overrides: object) -> tuple[str, dict[str, object]]:
    record: dict[str, object] = {
        "coin": "BTC",
        "side": "B",
        "px": "60000",
        "sz": "0.01",
        "time": 1789387199900,
        "hash": "0xaa",
        "tid": 1,
        "users": ["0xa", "0xb"],
    }
    record.update(overrides)
    return ("trades", {"channel": "trades", "data": [record]})


def bbo_frame() -> tuple[str, dict[str, object]]:
    return (
        "bbo",
        {
            "channel": "bbo",
            "data": {
                "coin": "BTC",
                "time": 1789387199900,
                "bbo": [{"px": "1", "sz": "1"}, {"px": "2", "sz": "1"}],
            },
        },
    )


def book_frame() -> tuple[str, dict[str, object]]:
    return (
        "l2Book",
        {
            "channel": "l2Book",
            "data": {"coin": "BTC", "time": 1789387199900, "levels": [[], []]},
        },
    )


def context_frame() -> tuple[str, dict[str, object]]:
    return ("activeAssetCtx", {"channel": "activeAssetCtx", "data": {"coin": "BTC", "ctx": {}}})


def all_channels() -> list[tuple[str, object]]:
    return [trade_frame(), bbo_frame(), book_frame(), context_frame()]


class TestLatencyStatistics:
    def test_percentiles_on_a_known_sample(self) -> None:
        report = analyse_latency({"TRADE": [float(n) for n in range(1, 101)]})
        stats = report.by_stream[0]
        assert stats.count == 100
        assert stats.min_ms == 1.0
        assert stats.max_ms == 100.0
        assert stats.p50_ms == pytest.approx(50.5)
        assert stats.p90_ms == pytest.approx(90.1)
        assert stats.p95_ms == pytest.approx(95.05)
        assert stats.p99_ms == pytest.approx(99.01)
        assert stats.mean_ms == pytest.approx(50.5)

    def test_a_single_observation_reports_no_standard_deviation(self) -> None:
        """Reporting 0.0 would imply a measured spread."""
        stats = analyse_latency({"TRADE": [12.5]}).by_stream[0]
        assert stats.count == 1
        assert stats.p50_ms == 12.5
        assert stats.stdev_ms is None

    def test_an_empty_stream_reports_nothing_rather_than_zero(self) -> None:
        stats = analyse_latency({"TRADE": []}).by_stream[0]
        assert stats.count == 0
        assert stats.p50_ms is None
        assert stats.mean_ms is None

    def test_no_streams_at_all_is_handled(self) -> None:
        report = analyse_latency({})
        assert report.by_stream == ()
        assert report.total_observations == 0

    def test_negative_observations_are_counted_not_clamped(self) -> None:
        """A venue timestamp ahead of receipt means clock disagreement."""
        stats = analyse_latency({"TRADE": [-5.0, 1.0, 2.0]}).by_stream[0]
        assert stats.negative_count == 1
        assert stats.min_ms == -5.0

    def test_streams_are_reported_separately(self) -> None:
        """Averaging incomparable timestamp semantics describes nothing."""
        report = analyse_latency({"TRADE": [1.0], "BBO": [100.0]})
        assert [s.stream for s in report.by_stream] == ["BBO", "TRADE"]
        assert report.total_observations == 2

    def test_the_measurement_is_labelled_as_arrival_not_execution(self) -> None:
        report = analyse_latency({"TRADE": [1.0]})
        assert "NOT execution latency" in report.measurement

    def test_streams_without_a_venue_timestamp_are_listed(self) -> None:
        report = analyse_latency({"TRADE": [1.0]}, streams_without_venue_timestamp=("FUNDING",))
        assert report.streams_without_venue_timestamp == ("FUNDING",)


class TestSchemaAnalysis:
    def test_a_conforming_sample_yields_no_deviations(self) -> None:
        report = analyse_schema(all_channels(), expected_channels=CHANNELS)
        assert report.deviations == ()
        assert report.missing_channels == ()
        assert report.assessed

    def test_a_missing_required_field_is_blocking(self) -> None:
        frames: list[tuple[str, object]] = [trade_frame()]
        del frames[0][1]["data"][0]["px"]  # type: ignore[index]
        report = analyse_schema(frames, expected_channels=CHANNELS)
        assert len(report.blocking) == 1
        assert report.blocking[0].field_name == "px"
        assert report.blocking[0].severity is DeviationSeverity.BLOCKING

    def test_an_unknown_field_is_informational_not_blocking(self) -> None:
        """Tolerating unknown fields is a design decision, not an oversight."""
        report = analyse_schema([trade_frame(brandNewField="x")], expected_channels=CHANNELS)
        assert report.blocking == ()
        assert len(report.deviations) == 1
        assert report.deviations[0].severity is DeviationSeverity.INFORMATIONAL
        assert report.deviations[0].field_name == "brandNewField"

    def test_occurrences_are_counted_per_record(self) -> None:
        """A field missing from 1 trade in 1000 must not be hidden by the 999."""
        good = trade_frame()
        bad = trade_frame()
        del bad[1]["data"][0]["sz"]  # type: ignore[index]
        report = analyse_schema([good, good, bad, bad, bad], expected_channels=CHANNELS)
        assert report.blocking[0].occurrences == 3

    def test_a_missing_channel_is_reported(self) -> None:
        report = analyse_schema([trade_frame()], expected_channels=CHANNELS)
        assert set(report.missing_channels) == {"l2Book", "bbo", "activeAssetCtx"}

    def test_an_empty_sample_is_not_assessed(self) -> None:
        """ "No deviations" over zero frames is the absence of observation."""
        report = analyse_schema([], expected_channels=CHANNELS)
        assert not report.assessed
        assert report.deviations == ()

    def test_an_unparseable_frame_does_not_crash_the_analysis(self) -> None:
        report = analyse_schema(
            [("<unparseable>", None), trade_frame()], expected_channels=CHANNELS
        )
        assert report.frames_by_channel["<unparseable>"] == 1
        assert report.blocking == ()

    def test_a_non_object_record_is_blocking(self) -> None:
        report = analyse_schema(
            [("trades", {"channel": "trades", "data": ["not an object"]})],
            expected_channels=CHANNELS,
        )
        assert report.blocking[0].field_name == "<record>"


class TestUsersAnalysis:
    def test_identity_is_observed_when_users_is_present(self) -> None:
        report = analyse_users([trade_frame(), trade_frame()])
        assert report.trades_seen == 2
        assert report.with_users == 2
        assert report.identity_observed
        assert report.presence_fraction == 1.0
        assert report.distinct_wallets == 2

    def test_role_attribution_is_never_proven_from_the_trade_stream(self) -> None:
        """Documentation says [buyer, seller]; that is direction, not aggression."""
        report = analyse_users([trade_frame()])
        # Compared by value: mypy narrows the first identity check and then
        # rejects the second as impossible, but stating both is the point —
        # DOCUMENTED_UNVERIFIED and PROVEN are the two claims task §6 separates.
        assert report.role_attribution.value == "DOCUMENTED_UNVERIFIED"
        assert report.role_attribution.value != RoleAttribution.PROVEN.value
        assert "aggressor" in report.role_attribution_note

    def test_a_missing_users_field_is_counted(self) -> None:
        frames: list[tuple[str, object]] = [trade_frame(), trade_frame()]
        del frames[1][1]["data"][0]["users"]  # type: ignore[index]
        report = analyse_users(frames)
        assert report.with_users == 1
        assert report.without_users == 1
        assert report.presence_fraction == 0.5

    def test_users_absent_from_every_trade_is_reported_plainly(self) -> None:
        """This materially affects TBIE feasibility; it must not be softened."""
        frames: list[tuple[str, object]] = [trade_frame()]
        del frames[0][1]["data"][0]["users"]  # type: ignore[index]
        report = analyse_users(frames)
        assert not report.identity_observed
        assert report.role_attribution is RoleAttribution.NOT_APPLICABLE
        assert "materially affects TBIE" in report.role_attribution_note

    @pytest.mark.parametrize("malformed", ["not a list", [1, 2], [None], {"a": "b"}, [["nested"]]])
    def test_a_malformed_users_value_is_counted_not_accepted(self, malformed: object) -> None:
        report = analyse_users([trade_frame(users=malformed)])
        assert report.malformed == 1
        assert report.with_users == 0
        assert not report.identity_observed

    def test_the_wallet_count_histogram_records_unexpected_shapes(self) -> None:
        report = analyse_users(
            [
                trade_frame(users=["0xa", "0xb"]),
                trade_frame(users=["0xc"]),
                trade_frame(users=["0xd", "0xe", "0xf"]),
            ]
        )
        assert report.wallet_count_histogram == {2: 1, 1: 1, 3: 1}

    def test_a_self_trade_is_counted(self) -> None:
        """Both entries equal would make counterparty degenerate."""
        report = analyse_users([trade_frame(users=["0xsame", "0xsame"])])
        assert report.self_trades == 1
        assert report.distinct_wallets == 1

    def test_no_trades_at_all_says_nothing_about_identity(self) -> None:
        report = analyse_users([bbo_frame()])
        assert report.trades_seen == 0
        assert report.role_attribution is RoleAttribution.NOT_APPLICABLE
        assert not report.identity_observed

    def test_sample_wallets_are_bounded(self) -> None:
        frames = [trade_frame(users=[f"0x{n}", f"0x{n + 100}"]) for n in range(50)]
        report = analyse_users(frames, sample_limit=3)
        assert len(report.sample_wallets) == 3
        assert report.distinct_wallets == 100


class TestM1Decision:
    def test_all_stores_healthy_and_tests_passing_is_accepted(self) -> None:
        verdict = decide_m1(
            store_results={
                "postgres": True,
                "clickhouse": True,
                "redis": True,
                "object_store": True,
            },
            integration_passed=True,
        )
        assert verdict.state is MilestoneState.VERIFIED
        assert verdict.decision is Decision.ACCEPTED
        assert verdict.blocking_failures == []

    @pytest.mark.parametrize("failing", ["postgres", "clickhouse", "redis", "object_store"])
    def test_any_failed_store_blocks_acceptance(self, failing: str) -> None:
        stores = dict.fromkeys(("postgres", "clickhouse", "redis", "object_store"), True)
        stores[failing] = False
        verdict = decide_m1(store_results=stores, integration_passed=True)
        assert verdict.state is MilestoneState.VERIFICATION_FAILED
        assert verdict.decision is Decision.NOT_ACCEPTED
        assert any(failing in failure for failure in verdict.blocking_failures)

    def test_integration_tests_not_run_blocks_acceptance(self) -> None:
        """Not run is not the same as passed."""
        verdict = decide_m1(
            store_results=dict.fromkeys(("postgres", "clickhouse", "redis", "object_store"), True),
            integration_passed=None,
        )
        assert verdict.decision is Decision.NOT_ACCEPTED
        assert "did not run" in " ".join(verdict.blocking_failures)

    def test_failing_integration_tests_block_acceptance(self) -> None:
        verdict = decide_m1(
            store_results=dict.fromkeys(("postgres", "clickhouse", "redis", "object_store"), True),
            integration_passed=False,
        )
        assert verdict.decision is Decision.NOT_ACCEPTED


def m2_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema": analyse_schema(all_channels() * 20, expected_channels=CHANNELS),
        "users": analyse_users([trade_frame()]),
        "latency": analyse_latency({"TRADE": [10.0, 20.0]}),
        "raw_first_proven": True,
        "replay_deterministic": True,
        "events_written": 80,
        "frames_received": 80,
        "persistence_failures": 0,
        "execution_enabled": False,
    }
    base.update(overrides)
    return base


class TestM2Decision:
    def test_a_complete_healthy_run_is_accepted(self) -> None:
        verdict = decide_m2(**m2_kwargs())  # type: ignore[arg-type]
        assert verdict.state is MilestoneState.LIVE_VERIFIED
        assert verdict.decision is Decision.ACCEPTED

    def test_execution_enabled_fails_outright(self) -> None:
        """A capital path invalidates the run whatever else it showed."""
        verdict = decide_m2(**m2_kwargs(execution_enabled=True))  # type: ignore[arg-type]
        assert verdict.state is MilestoneState.LIVE_VERIFICATION_FAILED
        assert verdict.decision is Decision.NOT_ACCEPTED
        assert "execution was enabled" in " ".join(verdict.blocking_failures)

    def test_no_frames_is_inconclusive_not_failed(self) -> None:
        """And the reason must be the connection, not a downstream symptom."""
        verdict = decide_m2(
            **m2_kwargs(frames_received=0, events_written=0, raw_first_proven=False)  # type: ignore[arg-type]
        )
        assert verdict.state is MilestoneState.LIVE_VERIFICATION_INCONCLUSIVE
        failures = " ".join(verdict.blocking_failures)
        assert "no frames were received" in failures
        assert "raw-before-interpretation" not in failures

    def test_a_thin_sample_is_inconclusive(self) -> None:
        verdict = decide_m2(**m2_kwargs(frames_received=3, events_written=3))  # type: ignore[arg-type]
        assert verdict.state is MilestoneState.LIVE_VERIFICATION_INCONCLUSIVE
        assert verdict.decision is Decision.NOT_ACCEPTED

    def test_frames_but_no_events_is_a_blocking_wire_format_failure(self) -> None:
        verdict = decide_m2(**m2_kwargs(events_written=0))  # type: ignore[arg-type]
        assert verdict.state is MilestoneState.LIVE_VERIFICATION_FAILED
        assert "does not match the parser" in " ".join(verdict.blocking_failures)

    def test_a_blocking_schema_deviation_fails(self) -> None:
        frames: list[tuple[str, object]] = all_channels() * 20
        broken = trade_frame()
        del broken[1]["data"][0]["px"]  # type: ignore[index]
        frames.append(broken)
        verdict = decide_m2(
            **m2_kwargs(schema=analyse_schema(frames, expected_channels=CHANNELS))  # type: ignore[arg-type]
        )
        assert verdict.state is MilestoneState.LIVE_VERIFICATION_FAILED

    def test_unproven_raw_first_ordering_fails(self) -> None:
        verdict = decide_m2(**m2_kwargs(raw_first_proven=False))  # type: ignore[arg-type]
        assert verdict.state is MilestoneState.LIVE_VERIFICATION_FAILED
        assert "raw-before-interpretation" in " ".join(verdict.blocking_failures)

    def test_nondeterministic_replay_fails(self) -> None:
        verdict = decide_m2(**m2_kwargs(replay_deterministic=False))  # type: ignore[arg-type]
        assert verdict.state is MilestoneState.LIVE_VERIFICATION_FAILED

    def test_unchecked_replay_is_inconclusive(self) -> None:
        verdict = decide_m2(**m2_kwargs(replay_deterministic=None))  # type: ignore[arg-type]
        assert verdict.state is MilestoneState.LIVE_VERIFICATION_INCONCLUSIVE

    def test_persistence_failures_fail(self) -> None:
        verdict = decide_m2(**m2_kwargs(persistence_failures=2))  # type: ignore[arg-type]
        assert verdict.state is MilestoneState.LIVE_VERIFICATION_FAILED

    def test_a_missing_channel_is_inconclusive_not_accepted(self) -> None:
        verdict = decide_m2(
            **m2_kwargs(  # type: ignore[arg-type]
                schema=analyse_schema([trade_frame()] * 80, expected_channels=CHANNELS)
            )
        )
        assert verdict.state is MilestoneState.LIVE_VERIFICATION_INCONCLUSIVE

    def test_missing_users_is_a_warning_not_a_failure(self) -> None:
        """TBIE's premise failing does not make the recorder wrong."""
        frames: list[tuple[str, object]] = [trade_frame()]
        del frames[0][1]["data"][0]["users"]  # type: ignore[index]
        verdict = decide_m2(**m2_kwargs(users=analyse_users(frames)))  # type: ignore[arg-type]
        assert verdict.decision is Decision.ACCEPTED
        assert any("`users`" in warning for warning in verdict.warnings)

    def test_unproven_attribution_is_warned_about_even_when_accepted(self) -> None:
        verdict = decide_m2(**m2_kwargs())  # type: ignore[arg-type]
        assert verdict.decision is Decision.ACCEPTED
        assert any("attribution remains unproven" in w for w in verdict.warnings)

    def test_clock_disagreement_is_warned_about(self) -> None:
        verdict = decide_m2(
            **m2_kwargs(latency=analyse_latency({"TRADE": [-10.0, 5.0]}))  # type: ignore[arg-type]
        )
        assert any("clock disagreement" in w for w in verdict.warnings)

    def test_connecting_alone_does_not_earn_acceptance(self) -> None:
        """Task §12: acceptance needs the pipeline to work, not just connect."""
        verdict = decide_m2(
            **m2_kwargs(frames_received=1, events_written=0, raw_first_proven=False)  # type: ignore[arg-type]
        )
        assert verdict.decision is Decision.NOT_ACCEPTED


class TestReportGeneration:
    def build(self, **overrides: object) -> AcceptanceReport:
        kwargs: dict[str, object] = {
            "commit_sha": "abc123",
            "workflow_run_id": "42",
            "started_at": NOW,
            "finished_at": NOW,
            "environment": {"execution": {"may_submit_orders": False}},
            "m1": decide_m1(
                store_results=dict.fromkeys(
                    ("postgres", "clickhouse", "redis", "object_store"), True
                ),
                integration_passed=True,
            ),
            "m2": decide_m2(**m2_kwargs()),  # type: ignore[arg-type]
            "schema": analyse_schema(all_channels() * 20, expected_channels=CHANNELS),
            "users": analyse_users([trade_frame()]),
            "latency": analyse_latency({"TRADE": [10.0, 20.0]}),
        }
        kwargs.update(overrides)
        return AcceptanceReport(**kwargs)  # type: ignore[arg-type]

    def test_the_json_is_valid_and_carries_the_required_keys(self) -> None:
        payload = json.loads(self.build().to_json())
        for key in (
            "acceptance",
            "environment",
            "m1",
            "m2",
            "storage",
            "migrations",
            "integration",
            "live_recording",
            "schema",
            "users_field",
            "latency",
            "replay",
            "fault_injection",
            "both_accepted",
        ):
            assert key in payload, key

    def test_the_acceptance_block_carries_provenance(self) -> None:
        payload = json.loads(self.build().to_json())["acceptance"]
        assert payload["commit_sha"] == "abc123"
        assert payload["workflow_run_id"] == "42"
        assert payload["started_at_utc"] == NOW.isoformat()

    def test_both_accepted_requires_both(self) -> None:
        assert self.build().both_accepted
        failed = self.build(
            m1=decide_m1(store_results={"postgres": False}, integration_passed=True)
        )
        assert not failed.both_accepted

    def test_the_markdown_leads_with_the_decision(self) -> None:
        markdown = self.build().to_markdown()
        assert "## Decision" in markdown
        assert markdown.index("## Decision") < markdown.index("## Safety")
        assert "ACCEPTED" in markdown

    def test_the_markdown_separates_identity_from_attribution(self) -> None:
        markdown = self.build().to_markdown()
        assert "**Identity observed**" in markdown
        assert "**Role/aggressor attribution**" in markdown

    def test_the_markdown_labels_latency_as_arrival_only(self) -> None:
        assert "NOT execution latency" in self.build().to_markdown()

    def test_an_unassessed_schema_is_not_reported_as_clean(self) -> None:
        report = self.build(schema=analyse_schema([], expected_channels=CHANNELS))
        assert "**Not assessed**" in report.to_markdown()

    def test_a_failed_run_renders_its_blockers(self) -> None:
        report = self.build(
            m2=decide_m2(**m2_kwargs(execution_enabled=True))  # type: ignore[arg-type]
        )
        markdown = report.to_markdown()
        assert "M2 blocking failures" in markdown
        assert "execution was enabled" in markdown

    def test_a_never_connected_run_says_so(self) -> None:
        report = self.build(
            live={
                "connected": False,
                "endpoint": "wss://example",
                "connection_attempts": 4,
                "successful_connections": 0,
                "last_connection_error": "HTTP 403",
            }
        )
        markdown = report.to_markdown()
        assert "Live connection never established" in markdown
        assert "HTTP 403" in markdown
        assert "untested rather than passing" in markdown
