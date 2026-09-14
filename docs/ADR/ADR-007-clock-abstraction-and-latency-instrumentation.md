# ADR-007 — Clock abstraction and receipt-time latency instrumentation

**Status:** Accepted · **Date:** 2026-09-14 · **Build:** 0.1 (M0 Rev.2)

## Context

Build 0.1 Rev.1 §67 calls a clock abstraction a "tiny architectural choice" that
saves enormous pain in backtesting. Two later requirements make it more than
that.

Deterministic replay (Rev.2 §22) requires that the same recorded input and code
version produce the same ordered event stream. Any component reading wall-clock
time directly breaks that, because the output then depends on when the replay
ran.

And TBIE v1.1 §42–43 makes receipt-time plus monotonic instrumentation a
precondition for its Gate 0. The cited research indexes time by venue consensus
timestamps, so it cannot say whether our own observe → decode → feature →
inference → risk → submit → fill path completes before a fast-decaying signal is
gone (§18). That question is unanswerable retroactively: measurements never
taken cannot be recovered from stored data.

## Decision

**No component reads wall-clock time directly.** Every component receives a
`Clock` (`libs/domain/clock.py`), injected explicitly.

Three implementations:

- `SystemClock` — production.
- `ManualClock` — advanced explicitly by tests, so a test asserts on a duration
  without sleeping.
- `ReplayClock` — driven by the event stream, reporting historical event time
  from `now()`. It refuses to move backwards: out-of-order replay is a defect in
  the recording or the replay engine, not something to absorb silently.

**Two notions of time, deliberately separated.** `now()` returns timezone-aware
UTC for audit, persistence and synchronisation. `monotonic_ns()` returns a
monotonic counter for durations. Wall-clock time can jump backwards when the
host clock is corrected, so it is never used to measure an interval — and
ruff's `DTZ` rules reject a naive datetime anywhere in the codebase.

**Every event carries both a venue timestamp and our own receipt.**
`EventTimestamps` makes `local_receive_time` and `local_receive_monotonic_ns`
mandatory — the two we always control — while venue-supplied fields
(`consensus_time`, `exchange_time`, `block_time`, `provider_time`) stay
optional, because a source that does not provide one must leave it empty rather
than have a value invented (Rev.1 §32).

`source_to_receive_seconds` returns the measured delay **including negative
values**. Clock skew is a condition to monitor and alert on (Phase 6 §62), not
to clamp away.

`LatencyBreakdown` records per-stage nanosecond deltas, and returns `None`
rather than a partial sum when a stage was not measured: an understated delay is
precisely the error this instrumentation exists to prevent. Distributions are
reported at p50/p90/p95/p99/p99.9 rather than as averages, because trading
systems fail in the tail (TBIE v1.1 §63).

## Alternatives rejected

**Read `datetime.now()` where needed.** Simplest, and rejected: it makes
deterministic replay impossible and forces tests to sleep.

**A single timestamp per event.** Rejected by Rev.1 §17–18 and by the Gate 0
requirement — one timestamp cannot distinguish when the venue acted from when we
found out.

**Wall-clock differences for latency.** Rejected: an NTP correction mid-
measurement produces a plausible, wrong number, and the wrongness is invisible.

**Add instrumentation when Gate 0 begins.** Rejected: Gate 0 needs measurements
of events recorded *before* it starts. Instrumenting later means waiting again.

## Consequences

- Every component takes a `Clock` parameter, which is mild ceremony bought for
  determinism and testability.
- Storage carries several timestamp columns per event, which is cheap relative
  to the event payload.
- Gate 0 becomes answerable from data the recorder collects from its first day
  (M2), rather than requiring a new collection campaign.

## Revisit when

Latency measurement shows the instrumentation itself is a material cost in the
hot path, or a venue exposes a timing source that changes what is worth
recording.
