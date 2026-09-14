"""Acceptance analysis for Build 0.1 Rev.2 milestones M1 and M2.

This module turns a live recording into an acceptance decision. It exists
because the alternative — reading the code and declaring it correct — is
exactly what left M1 and M2 "implemented but not accepted".

Four analyses, each answering a question a fixture cannot:

`analyse_schema`
    Did the venue send the fields the parser relies on? Unknown extra fields
    are tolerated by design and reported as informational; a missing *required*
    field is a blocking deviation.

`analyse_users`
    Do live BTC trades carry `users`? This decides whether trader-level
    research is possible at all (ADR-006). The analysis separates two claims
    that are routinely conflated: **identity observed** (these wallets were
    party to this trade) and **role attribution proven** (which one was the
    aggressor). Documentation describing `users` as `[buyer, seller]` — even if
    correct — establishes direction, not aggression, and TBIE's markout depends
    on aggression. So role attribution is reported as UNPROVEN unless evidence
    that could establish it is present, and no such evidence exists in the
    public trade stream.

`analyse_latency`
    What is the distribution of `receipt - venue timestamp`? This is **data
    arrival latency only** — one hop of the path in TBIE v1.1 §38. Calling it
    execution latency would overstate it by every stage that does not yet
    exist.

`decide`
    Produces an explicit state per milestone. Never a bare pass/fail: a run can
    be INCONCLUSIVE, which is a different and honest outcome from failure.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

# Fields the parser requires per channel. Taken from the parser itself
# (`libs/exchange/hyperliquid/messages.py`), so a change there that this list
# does not follow shows up as a test failure rather than a silent gap.
REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "trades": frozenset({"coin", "side", "px", "sz", "time"}),
    "bbo": frozenset({"coin", "time", "bbo"}),
    "l2Book": frozenset({"coin", "time", "levels"}),
    "activeAssetCtx": frozenset({"coin", "ctx"}),
}

# Fields the parser reads when present but does not require.
OPTIONAL_FIELDS: dict[str, frozenset[str]] = {
    "trades": frozenset({"hash", "tid", "users"}),
    "bbo": frozenset(),
    "l2Book": frozenset(),
    "activeAssetCtx": frozenset(),
}

EXPECTED_WALLETS_PER_TRADE = 2
"""How many wallets a `users` array is documented to carry.

Documented as `[buyer, seller]`. Observing two is consistent with that and does
not establish which is which.
"""


class MilestoneState(StrEnum):
    """Explicit acceptance states (task §12)."""

    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"
    LIVE_VERIFIED = "LIVE_VERIFIED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    LIVE_VERIFICATION_FAILED = "LIVE_VERIFICATION_FAILED"
    LIVE_VERIFICATION_INCONCLUSIVE = "LIVE_VERIFICATION_INCONCLUSIVE"
    NOT_RUN = "NOT_RUN"


class Decision(StrEnum):
    ACCEPTED = "ACCEPTED"
    NOT_ACCEPTED = "NOT_ACCEPTED"


class RoleAttribution(StrEnum):
    """How well the aggressor side can be tied to a specific wallet."""

    PROVEN = "PROVEN"
    DOCUMENTED_UNVERIFIED = "DOCUMENTED_UNVERIFIED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DeviationSeverity(StrEnum):
    BLOCKING = "BLOCKING"
    """A field the parser requires is missing or unreadable."""

    INFORMATIONAL = "INFORMATIONAL"
    """An unknown extra field. Tolerated by design; recorded so the schema
    drifts visibly rather than silently."""


@dataclass(frozen=True, slots=True)
class SchemaDeviation:
    channel: str
    field_name: str
    severity: DeviationSeverity
    detail: str
    occurrences: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "field": self.field_name,
            "severity": self.severity.value,
            "detail": self.detail,
            "occurrences": self.occurrences,
        }


@dataclass(frozen=True, slots=True)
class SchemaReport:
    channels_observed: tuple[str, ...]
    channels_expected: tuple[str, ...]
    frames_by_channel: dict[str, int]
    deviations: tuple[SchemaDeviation, ...]

    @property
    def blocking(self) -> tuple[SchemaDeviation, ...]:
        return tuple(d for d in self.deviations if d.severity is DeviationSeverity.BLOCKING)

    @property
    def assessed(self) -> bool:
        """Whether any frame was inspected.

        Distinct from "no deviations found": a report over zero frames has
        found nothing because it looked at nothing, and presenting that as a
        clean result would be the same category of error as a fabricated
        latency figure.
        """
        return sum(self.frames_by_channel.values()) > 0

    @property
    def missing_channels(self) -> tuple[str, ...]:
        return tuple(
            channel for channel in self.channels_expected if channel not in self.channels_observed
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "assessed": self.assessed,
            "channels_expected": list(self.channels_expected),
            "channels_observed": list(self.channels_observed),
            "channels_missing": list(self.missing_channels),
            "frames_by_channel": dict(sorted(self.frames_by_channel.items())),
            "deviations": [d.as_dict() for d in self.deviations],
            "blocking_count": len(self.blocking),
        }


@dataclass(frozen=True, slots=True)
class UsersReport:
    """Observations about the `users` field on live trades."""

    trades_seen: int
    with_users: int
    without_users: int
    malformed: int
    wallet_count_histogram: dict[int, int]
    distinct_wallets: int
    self_trades: int
    """Trades where both entries are the same wallet. Counted because it would
    make `counterparty` degenerate, and because a wash-trade pattern is worth
    seeing rather than averaging away."""

    sample_wallets: tuple[str, ...]
    role_attribution: RoleAttribution
    role_attribution_note: str

    @property
    def presence_fraction(self) -> float:
        return self.with_users / self.trades_seen if self.trades_seen else 0.0

    @property
    def identity_observed(self) -> bool:
        """Whether wallet identity was actually seen on live trades.

        Distinct from role attribution, which is the whole point of separating
        them (task §6).
        """
        return self.with_users > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "trades_seen": self.trades_seen,
            "with_users": self.with_users,
            "without_users": self.without_users,
            "malformed": self.malformed,
            "presence_fraction": round(self.presence_fraction, 6),
            "wallet_count_histogram": {
                str(k): v for k, v in sorted(self.wallet_count_histogram.items())
            },
            "distinct_wallets": self.distinct_wallets,
            "self_trades": self.self_trades,
            "sample_wallets": list(self.sample_wallets),
            "identity_observed": self.identity_observed,
            "role_attribution": self.role_attribution.value,
            "role_attribution_note": self.role_attribution_note,
        }


@dataclass(frozen=True, slots=True)
class LatencyStats:
    """Data arrival latency for one stream.

    `receipt - venue timestamp`, in milliseconds. Not execution latency: it
    covers one hop of the path in TBIE v1.1 §38 and omits parse, normalize,
    feature, decision, risk, send, acknowledge and fill.
    """

    stream: str
    count: int
    min_ms: float | None
    p50_ms: float | None
    p90_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    max_ms: float | None
    mean_ms: float | None
    stdev_ms: float | None
    negative_count: int
    """Observations where the venue timestamp is ahead of our receipt.

    Reported, never clamped: it means clock disagreement between the venue and
    the runner, which invalidates the measurement rather than being noise
    (ADR-007).
    """

    def as_dict(self) -> dict[str, Any]:
        return {
            "stream": self.stream,
            "count": self.count,
            "min_ms": self.min_ms,
            "p50_ms": self.p50_ms,
            "p90_ms": self.p90_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "max_ms": self.max_ms,
            "mean_ms": self.mean_ms,
            "stdev_ms": self.stdev_ms,
            "negative_count": self.negative_count,
        }


@dataclass(frozen=True, slots=True)
class LatencyReport:
    measurement: str
    by_stream: tuple[LatencyStats, ...]
    clock_note: str
    streams_without_venue_timestamp: tuple[str, ...]

    @property
    def total_observations(self) -> int:
        return sum(stats.count for stats in self.by_stream)

    def as_dict(self) -> dict[str, Any]:
        return {
            "measurement": self.measurement,
            "clock_note": self.clock_note,
            "total_observations": self.total_observations,
            "streams_without_venue_timestamp": list(self.streams_without_venue_timestamp),
            "by_stream": [stats.as_dict() for stats in self.by_stream],
        }


@dataclass
class MilestoneVerdict:
    milestone: str
    state: MilestoneState
    decision: Decision
    blocking_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "milestone": self.milestone,
            "state": self.state.value,
            "decision": self.decision.value,
            "blocking_failures": list(self.blocking_failures),
            "warnings": list(self.warnings),
            "checks": dict(sorted(self.checks.items())),
        }


def _percentile(values: list[float], fraction: float) -> float:
    """Percentile by linear interpolation on the sorted sample.

    Written out rather than taken from `statistics.quantiles`, which needs at
    least two points and buckets rather than interpolating — awkward for the
    small samples a short run produces, and this way a one-observation stream
    still reports a number instead of nothing.
    """
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def analyse_latency(
    samples: dict[str, list[float]],
    *,
    streams_without_venue_timestamp: tuple[str, ...] = (),
    clock_note: str = "",
) -> LatencyReport:
    """Summarise data arrival latency per stream.

    Streams are kept separate rather than pooled: `activeAssetCtx` publishes no
    timestamp at all while `trades` does, and averaging incomparable quantities
    would produce a number that describes nothing (task §8).
    """
    stats: list[LatencyStats] = []
    for stream in sorted(samples):
        values = samples[stream]
        if not values:
            stats.append(
                LatencyStats(
                    stream=stream,
                    count=0,
                    min_ms=None,
                    p50_ms=None,
                    p90_ms=None,
                    p95_ms=None,
                    p99_ms=None,
                    max_ms=None,
                    mean_ms=None,
                    stdev_ms=None,
                    negative_count=0,
                )
            )
            continue
        stats.append(
            LatencyStats(
                stream=stream,
                count=len(values),
                min_ms=round(min(values), 3),
                p50_ms=round(_percentile(values, 0.50), 3),
                p90_ms=round(_percentile(values, 0.90), 3),
                p95_ms=round(_percentile(values, 0.95), 3),
                p99_ms=round(_percentile(values, 0.99), 3),
                max_ms=round(max(values), 3),
                mean_ms=round(statistics.fmean(values), 3),
                # A single observation has no spread. Reporting 0.0 would imply
                # a measured one.
                stdev_ms=round(statistics.stdev(values), 3) if len(values) > 1 else None,
                negative_count=sum(1 for value in values if value < 0),
            )
        )
    return LatencyReport(
        measurement=(
            "data_arrival_latency_ms = local_receipt_timestamp - venue_event_timestamp; "
            "one hop only, NOT execution latency"
        ),
        by_stream=tuple(stats),
        clock_note=clock_note,
        streams_without_venue_timestamp=streams_without_venue_timestamp,
    )


def analyse_schema(
    frames: list[tuple[str, Any]], *, expected_channels: tuple[str, ...]
) -> SchemaReport:
    """Compare live payloads against what the parser relies on.

    `frames` is `(channel, decoded payload)`. Records are inspected
    per-occurrence so that a field missing from one trade in a thousand is
    counted rather than hidden by a field present in the other 999.
    """
    frames_by_channel: Counter[str] = Counter()
    missing: Counter[tuple[str, str]] = Counter()
    unknown: Counter[tuple[str, str]] = Counter()

    for channel, payload in frames:
        frames_by_channel[channel] += 1
        if channel not in REQUIRED_FIELDS:
            continue
        for record in _records_for(channel, payload):
            if not isinstance(record, dict):
                missing[(channel, "<record>")] += 1
                continue
            present = set(record)
            for name in REQUIRED_FIELDS[channel] - present:
                missing[(channel, name)] += 1
            known = REQUIRED_FIELDS[channel] | OPTIONAL_FIELDS[channel]
            for name in present - known:
                unknown[(channel, name)] += 1

    deviations = [
        SchemaDeviation(
            channel=channel,
            field_name=name,
            severity=DeviationSeverity.BLOCKING,
            detail="required field absent from the live payload",
            occurrences=count,
        )
        for (channel, name), count in sorted(missing.items())
    ]
    deviations += [
        SchemaDeviation(
            channel=channel,
            field_name=name,
            severity=DeviationSeverity.INFORMATIONAL,
            detail="field present on the wire but not read by the parser",
            occurrences=count,
        )
        for (channel, name), count in sorted(unknown.items())
    ]

    return SchemaReport(
        channels_observed=tuple(sorted(frames_by_channel)),
        channels_expected=expected_channels,
        frames_by_channel=dict(frames_by_channel),
        deviations=tuple(deviations),
    )


def _records_for(channel: str, payload: Any) -> list[Any]:
    """The per-record objects inside one frame's `data`."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if channel == "trades":
        return list(data) if isinstance(data, list) else [data]
    return [data]


def analyse_users(frames: list[tuple[str, Any]], *, sample_limit: int = 5) -> UsersReport:
    """Determine whether live BTC trades carry wallet identity.

    Role attribution is reported separately and conservatively. Public trade
    frames carry the aggressor's side and the two parties, but nothing that ties
    one to the other: `side` says a buyer was the aggressor, `users` says who
    the parties were, and joining them requires knowing which entry is the
    buyer. Documentation asserts `[buyer, seller]`; that is `DOCUMENTED_
    UNVERIFIED`, because an inverted assumption would flip the sign of every
    markout while looking entirely plausible (ADR-006).
    """
    trades_seen = 0
    with_users = 0
    malformed = 0
    self_trades = 0
    histogram: Counter[int] = Counter()
    wallets: set[str] = set()
    samples: list[str] = []

    for channel, payload in frames:
        if channel != "trades":
            continue
        for record in _records_for("trades", payload):
            if not isinstance(record, dict):
                continue
            trades_seen += 1
            if "users" not in record:
                continue
            value = record["users"]
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                malformed += 1
                continue
            with_users += 1
            histogram[len(value)] += 1
            for wallet in value:
                wallets.add(wallet)
                if len(samples) < sample_limit and wallet not in samples:
                    samples.append(wallet)
            if len(value) == EXPECTED_WALLETS_PER_TRADE and value[0] == value[1]:
                self_trades += 1

    if trades_seen == 0:
        attribution = RoleAttribution.NOT_APPLICABLE
        note = "no live trades were observed, so nothing can be said about identity"
    elif with_users == 0:
        attribution = RoleAttribution.NOT_APPLICABLE
        note = (
            "no live trade carried `users`; trader-level research is not "
            "possible from this stream, which materially affects TBIE feasibility"
        )
    else:
        attribution = RoleAttribution.DOCUMENTED_UNVERIFIED
        note = (
            "identity observed. Ordering is documented as [buyer, seller], which "
            "is direction, not aggression; `side` carries the aggressor. Tying "
            "the two together is an inference this run cannot test, because the "
            "public trade frame contains no position delta. Proving it needs "
            "Level-4 node data with startPosition. Until then no markout may be "
            "computed from an assumed taker."
        )

    return UsersReport(
        trades_seen=trades_seen,
        with_users=with_users,
        without_users=trades_seen - with_users - malformed,
        malformed=malformed,
        wallet_count_histogram=dict(histogram),
        distinct_wallets=len(wallets),
        self_trades=self_trades,
        sample_wallets=tuple(samples),
        role_attribution=attribution,
        role_attribution_note=note,
    )


def decide_m1(
    *, store_results: dict[str, bool], integration_passed: bool | None
) -> MilestoneVerdict:
    """M1's verdict: every required store healthy, migrations applied, tests pass."""
    verdict = MilestoneVerdict(
        milestone="M1",
        state=MilestoneState.IMPLEMENTED,
        decision=Decision.NOT_ACCEPTED,
        checks=dict(store_results),
    )
    verdict.checks["integration_tests_passed"] = bool(integration_passed)

    for name, ok in sorted(store_results.items()):
        if not ok:
            verdict.blocking_failures.append(f"{name} did not pass verification")
    if integration_passed is None:
        verdict.blocking_failures.append("integration tests did not run")
    elif not integration_passed:
        verdict.blocking_failures.append("integration tests failed")

    if verdict.blocking_failures:
        verdict.state = MilestoneState.VERIFICATION_FAILED
        return verdict

    verdict.state = MilestoneState.VERIFIED
    verdict.decision = Decision.ACCEPTED
    return verdict


def decide_m2(
    *,
    schema: SchemaReport,
    users: UsersReport,
    latency: LatencyReport,
    raw_first_proven: bool,
    replay_deterministic: bool | None,
    events_written: int,
    frames_received: int,
    persistence_failures: int,
    execution_enabled: bool,
    minimum_frames: int = 50,
) -> MilestoneVerdict:
    """M2's verdict.

    Connecting is not acceptance. The pipeline has to demonstrate the behaviour
    it claims: raw preserved before interpretation, required fields present,
    events produced, replay deterministic, and no capital path opened.

    A run that simply saw too little is INCONCLUSIVE rather than failed — an
    honest third outcome, because a thin sample says nothing either way.
    """
    verdict = MilestoneVerdict(
        milestone="M2",
        state=MilestoneState.IMPLEMENTED,
        decision=Decision.NOT_ACCEPTED,
    )
    verdict.checks = {
        "frames_received": frames_received > 0,
        "sufficient_sample": frames_received >= minimum_frames,
        "all_expected_channels_observed": not schema.missing_channels,
        "no_blocking_schema_deviation": not schema.blocking,
        "events_written": events_written > 0,
        "raw_first_proven": raw_first_proven,
        "replay_deterministic": bool(replay_deterministic),
        "no_persistence_failures": persistence_failures == 0,
        "execution_remained_disabled": not execution_enabled,
        "latency_measured": latency.total_observations > 0,
    }

    # Safety first: an open capital path invalidates the run outright,
    # whatever else it showed.
    if execution_enabled:
        verdict.blocking_failures.append(
            "execution was enabled during a market-data verification run"
        )
        verdict.state = MilestoneState.LIVE_VERIFICATION_FAILED
        return verdict

    # No frames means most checks are untestable rather than failed, and
    # reporting them as failures buries the actual cause. An early run of this
    # verifier blamed "raw-first ordering not demonstrated" for what was simply
    # a blocked connection — a true statement that pointed at the wrong thing.
    if frames_received == 0:
        verdict.state = MilestoneState.LIVE_VERIFICATION_INCONCLUSIVE
        verdict.blocking_failures.append(
            "no frames were received from the venue, so the live pipeline was "
            "not exercised; every downstream check is untested rather than failed"
        )
        verdict.checks = {
            "frames_received": False,
            "execution_remained_disabled": True,
        }
        return verdict

    if schema.blocking:
        for deviation in schema.blocking:
            verdict.blocking_failures.append(
                f"{deviation.channel}.{deviation.field_name}: {deviation.detail} "
                f"({deviation.occurrences} occurrence(s))"
            )
    if frames_received > 0 and events_written == 0:
        verdict.blocking_failures.append(
            "frames were received but no events were written — the live wire "
            "format does not match the parser"
        )
    if persistence_failures:
        verdict.blocking_failures.append(f"{persistence_failures} persistence failure(s)")
    if not raw_first_proven:
        verdict.blocking_failures.append("raw-before-interpretation ordering was not demonstrated")
    if replay_deterministic is False:
        verdict.blocking_failures.append("replay of the captured session was not deterministic")

    if verdict.blocking_failures:
        verdict.state = MilestoneState.LIVE_VERIFICATION_FAILED
        return verdict

    # Nothing failed. Decide between inconclusive and accepted on sample size
    # and coverage.
    if frames_received < minimum_frames:
        verdict.state = MilestoneState.LIVE_VERIFICATION_INCONCLUSIVE
        verdict.warnings.append(
            f"only {frames_received} frame(s) received; at least {minimum_frames} "
            f"are needed before the observation means anything"
        )
        return verdict
    if schema.missing_channels:
        verdict.state = MilestoneState.LIVE_VERIFICATION_INCONCLUSIVE
        verdict.warnings.append(f"no data on channel(s): {', '.join(schema.missing_channels)}")
        return verdict
    if replay_deterministic is None:
        verdict.state = MilestoneState.LIVE_VERIFICATION_INCONCLUSIVE
        verdict.warnings.append("replay determinism was not checked")
        return verdict

    if not users.identity_observed:
        verdict.warnings.append(
            "live trades carried no `users` field; TBIE's premise is not supported by this stream"
        )
    if users.role_attribution is RoleAttribution.DOCUMENTED_UNVERIFIED:
        verdict.warnings.append(
            "wallet identity observed but aggressor attribution remains unproven"
        )
    for stats in latency.by_stream:
        if stats.negative_count:
            verdict.warnings.append(
                f"{stats.stream}: {stats.negative_count} observation(s) with the "
                f"venue timestamp ahead of receipt — clock disagreement"
            )
    for deviation in schema.deviations:
        if deviation.severity is DeviationSeverity.INFORMATIONAL:
            verdict.warnings.append(
                f"{deviation.channel}.{deviation.field_name} is on the wire but "
                f"unread by the parser ({deviation.occurrences} occurrence(s))"
            )

    verdict.state = MilestoneState.LIVE_VERIFIED
    verdict.decision = Decision.ACCEPTED
    return verdict


@dataclass
class AcceptanceReport:
    """The full evidence document."""

    commit_sha: str
    workflow_run_id: str | None
    started_at: datetime
    finished_at: datetime
    environment: dict[str, Any]
    m1: MilestoneVerdict
    m2: MilestoneVerdict
    storage: dict[str, Any] = field(default_factory=dict)
    migrations: dict[str, Any] = field(default_factory=dict)
    integration: dict[str, Any] = field(default_factory=dict)
    live: dict[str, Any] = field(default_factory=dict)
    schema: SchemaReport | None = None
    users: UsersReport | None = None
    latency: LatencyReport | None = None
    replay: dict[str, Any] = field(default_factory=dict)
    fault_injection: dict[str, Any] = field(default_factory=dict)

    @property
    def both_accepted(self) -> bool:
        return self.m1.decision is Decision.ACCEPTED and self.m2.decision is Decision.ACCEPTED

    def as_dict(self) -> dict[str, Any]:
        return {
            "acceptance": {
                "build": "0.1 Rev.2",
                "milestones": ["M1", "M2"],
                "commit_sha": self.commit_sha,
                "workflow_run_id": self.workflow_run_id,
                "started_at_utc": self.started_at.isoformat(),
                "finished_at_utc": self.finished_at.isoformat(),
                "duration_seconds": round((self.finished_at - self.started_at).total_seconds(), 3),
            },
            "environment": self.environment,
            "m1": self.m1.as_dict(),
            "m2": self.m2.as_dict(),
            "storage": self.storage,
            "migrations": self.migrations,
            "integration": self.integration,
            "live_recording": self.live,
            "schema": None if self.schema is None else self.schema.as_dict(),
            "users_field": None if self.users is None else self.users.as_dict(),
            "latency": None if self.latency is None else self.latency.as_dict(),
            "replay": self.replay,
            "fault_injection": self.fault_injection,
            "both_accepted": self.both_accepted,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=False)

    def to_markdown(self) -> str:
        """Human-readable summary.

        Leads with the decision and the blockers, because a reader wants to
        know whether this passed and why before anything else.
        """
        lines = [
            "# Build 0.1 Rev.2 — M1/M2 Acceptance Report",
            "",
            f"- **Commit**: `{self.commit_sha}`",
            f"- **Workflow run**: {self.workflow_run_id or 'not run in CI'}",
            f"- **Window (UTC)**: {self.started_at.isoformat()} → {self.finished_at.isoformat()}",
            "",
            "## Decision",
            "",
            "| Milestone | State | Decision |",
            "|-----------|-------|----------|",
            f"| M1 — storage foundation | `{self.m1.state.value}` | **{self.m1.decision.value}** |",
            f"| M2 — BTC recorder | `{self.m2.state.value}` | **{self.m2.decision.value}** |",
            "",
        ]

        for verdict in (self.m1, self.m2):
            if verdict.blocking_failures:
                lines += [f"### {verdict.milestone} blocking failures", ""]
                lines += [f"- {failure}" for failure in verdict.blocking_failures]
                lines.append("")

        for verdict in (self.m1, self.m2):
            if verdict.warnings:
                lines += [f"### {verdict.milestone} warnings", ""]
                lines += [f"- {warning}" for warning in verdict.warnings]
                lines.append("")

        if self.live.get("connected") is False:
            lines += [
                "## Live connection never established",
                "",
                f"- endpoint: `{self.live.get('endpoint', 'unknown')}`",
                f"- connection attempts: {self.live.get('connection_attempts', 'unknown')}",
                f"- successful connections: {self.live.get('successful_connections', 0)}",
                f"- last error: `{
                    self.live.get('last_connection_error')
                    or self.live.get('error')
                    or 'none recorded'
                }`",
                "",
                "No live evidence was collected. Every downstream observation in "
                "this report is untested rather than passing.",
                "",
            ]

        lines += ["## Safety", ""]
        execution = self.environment.get("execution", {})
        lines += [
            f"- execution environment: `{execution.get('execution_environment', 'unknown')}`",
            f"- market-data environment: `{execution.get('market_data_environment', 'unknown')}`",
            f"- execution enabled: **{execution.get('may_submit_orders', 'unknown')}**",
            f"- credential configured: {execution.get('credential_configured', 'unknown')}",
            "",
        ]

        if self.users is not None:
            users = self.users
            lines += [
                "## `users` field — TBIE feasibility",
                "",
                f"- trades observed: {users.trades_seen}",
                f"- carrying `users`: {users.with_users} ({users.presence_fraction:.1%})",
                f"- malformed: {users.malformed}",
                f"- distinct wallets: {users.distinct_wallets}",
                f"- self-trades: {users.self_trades}",
                "",
                f"**Identity observed**: {users.identity_observed}",
                "",
                f"**Role/aggressor attribution**: `{users.role_attribution.value}`",
                "",
                f"> {users.role_attribution_note}",
                "",
            ]

        if self.latency is not None and self.latency.by_stream:
            lines += [
                "## Data arrival latency",
                "",
                f"_{self.latency.measurement}_",
                "",
                "| Stream | n | p50 | p90 | p95 | p99 | max | negative |",
                "|--------|---|-----|-----|-----|-----|-----|----------|",
            ]
            for stats in self.latency.by_stream:
                lines.append(
                    f"| {stats.stream} | {stats.count} | {stats.p50_ms} | "
                    f"{stats.p90_ms} | {stats.p95_ms} | {stats.p99_ms} | "
                    f"{stats.max_ms} | {stats.negative_count} |"
                )
            lines += ["", f"Clock: {self.latency.clock_note}", ""]

        if self.schema is not None:
            lines += ["## Schema deviations", ""]
            if not self.schema.assessed:
                lines += [
                    "**Not assessed** — no frames were inspected, so this section "
                    "reports the absence of observation, not the absence of "
                    "deviations.",
                    "",
                ]
            elif not self.schema.deviations:
                lines += [
                    "None. Every required field was present and no unknown field appeared.",
                    "",
                ]
            else:
                lines += [
                    "| Channel | Field | Severity | Occurrences | Detail |",
                    "|---|---|---|---|---|",
                ]
                for deviation in self.schema.deviations:
                    lines.append(
                        f"| {deviation.channel} | `{deviation.field_name}` | "
                        f"{deviation.severity.value} | {deviation.occurrences} | "
                        f"{deviation.detail} |"
                    )
                lines.append("")

        return "\n".join(lines)
