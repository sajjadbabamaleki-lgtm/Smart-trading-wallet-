# Build 0.1 Evidence Pack

Build 0.1 completion produces the artifacts listed in Build 0.1 Rev.1 §78:

```
infrastructure-report      data-quality-report        reconciliation-report
data-ingestion-report      reconnect-test             restart-recovery-report
replay-determinism-test    gap-detection-test         duplicate-order-test
testnet-order-report       kill-switch-test           security-scan-report
acceptance-matrix
```

Screenshots are not evidence (Rev.1 §36) — these are generated from automated
tests and logs, and become part of the project's permanent history.

**Status: not yet produced.** M0 is the repository foundation; the evidence pack
is assembled at M9, after the milestones it reports on have run. Generated
artifacts are git-ignored here; the acceptance matrix will be committed.

## Progress against the Build 0.1 hard gate (Rev.1 §77)

| Area | Requirement | State |
|------|-------------|-------|
| Infrastructure | Clean environment starts the stack | **Done** — a clean Contabo VPS ran `make accept` end to end on 2026-09-14; all four stores healthy, 16/16 integration tests |
| Infrastructure | Configuration is validated | **M0 done** |
| Infrastructure | Secrets absent from source | **M0 done** |
| Infrastructure | CI passes | **Done** — CI executed for the first time on 2026-09-14 once the repository became public; lint, types, 452 tests, gitleaks and the dependency audit all green |
| Data | Schemas and migrations exist for both stores | **M1 done** |
| Data | Recorder pipeline, raw retained, normalization, quality classification | **Done and live-verified** — 15 minutes of mainnet BTC, 8240 events across four channels, no schema deviation |
| Data | Reconnect, gap detection, duplicates, freshness | **Implemented**; gap detection corrected against live data — `tid` is a hash, not a sequence, and no longer produces false gaps |
| Data | Dataset manifests | M4 |
| Replay | Deterministic, independent of wall-clock time | **M3 done** — `verify_replay.py` replays each capture twice and compares; 53 replay tests |
| Replay | Capture format, sessions reloadable as fixtures | **M3 done** |
| Data | Freshness measured, silence detected on a timer | **M3 done** — the monitor loop drives what M2 could only detect on arrival |
| Data | Gap registry: register, attempt, close, summarise | **M3 done** (in-memory; PostgreSQL writer exists from M2's store sink) |
| Audit | Append-only audit table, correlation ids, gap registry, dataset manifests | **M1 schemas done**, writers in M2-M8 |
| Testnet | Account, order, cancel, fill, position, restart recovery | M6, M8 |
| Risk | Asset allowlist rejects unsupported assets | **M0 enforced in config**, M7 in engine |
| Risk | Oversized orders rejected | M7 |
| Risk | Expired intents rejected | M7 |
| Risk | Kill Switch blocks new exposure | **M0 flag exists**, M7 enforced |
| Risk | Mainnet execution structurally blocked | **M0 done** |
| Audit | Test order reconstructable intent → fill → position | M8 |
| Failure | Disconnect, timeout, database interruption, restart, duplicate order | M8 |

M0 closed the four infrastructure rows and the safety-configuration rows. M1
adds the storage schemas, the migration mechanism and the verification script.
The rest are open by design.

## Acceptance status

See **[acceptance-attempts.md](acceptance-attempts.md)** for the attempt log.

| Milestone | State | Decision |
|-----------|-------|----------|
| M1 — storage foundation | **verified against a real stack**, 2026-09-14 | **ACCEPTED** |
| M2 — BTC recorder | **verified against the live venue**, 2026-09-14 | **ACCEPTED** |
| M3 — integrity and replay | unblocked; its own acceptance still owed | pending |

Attempt 2 was the first acceptance run this project completed. It established
that `users` is present on public trades — the question that decided whether
trader-level research is possible at all — that no channel deviates from the
parser's expectations, and that data arrival latency has a floor near 300 ms
that is neither our clock nor our network. See the attempt log for the numbers
and for what they mean for TBIE Gate 0.

The verification machinery is
`infrastructure/scripts/accept_m1_m2.sh` — the single acceptance path, which
`make accept` and the CI workflow both call — together with
`infrastructure/scripts/acceptance_m1_m2.py` and 60 verifier tests. It no longer
depends on GitHub Actions, which had rejected every job ever queued in this
repository until the repository was made public on 2026-09-14. Both now work.

## What the live run established

Three claims moved from assumption to evidence, and one stayed honest.

**`users` is present on public trades.** This decided whether trader-level
research is possible at all (ADR-006, TBIE). It is.

**No schema deviation.** Every field the parser relies on was present across
all four channels, and no unknown field appeared. The hand-written fixtures had
the shape right; what they had wrong was the meaning of `tid`.

**Aggressor attribution remains unproven**, correctly. `users` is ordered
[buyer, seller] — direction — while `side` carries aggression. Joining them is
an inference the public trade frame cannot test, so no markout may be computed
from an assumed taker.

**Data arrival latency has a floor near 300 ms** that is neither our clock
(NTP-synchronised, 274 µs root dispersion) nor our network (28 ms one-way).
It is the interval between Hyperliquid stamping an event and publishing it to
subscribers, and therefore the observation floor for any consumer of this feed.
TBIE Gate 0's delay ladder starts below that floor and needs re-basing.

## Carried forward

**Subscription snapshots are classified as invalid.** On subscribing to
`trades` the venue replays recent history, and those frames carry venue
timestamps 30-35 s old. The quality engine calls them implausible, which is
right, but it cannot tell backfill from degraded live data, which is wrong.
They should be distinguished.

This also revises the open question recorded at attempt 2. The TRADE latency
tail is more likely the snapshot burst than this recorder's backpressure, which
means attempt 2's TRADE p99 and max may describe subscription behaviour rather
than transport. The ~300 ms floor at p50 is unaffected.
