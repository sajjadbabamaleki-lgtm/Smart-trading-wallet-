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
| Infrastructure | Clean environment starts the stack | **M1 defined and verifiable** via `make stack-up` + `make stack-verify`; not yet run in CI |
| Infrastructure | Configuration is validated | **M0 done** |
| Infrastructure | Secrets absent from source | **M0 done** |
| Infrastructure | CI passes | **M0 done** |
| Data | Schemas and migrations exist for both stores | **M1 done** |
| Data | Recorder pipeline, raw retained, normalization, quality classification | **M2 code done**, unverified against the live venue |
| Data | Reconnect, gap detection, duplicates, freshness | **M2 implemented and tested against fixtures**; live behaviour is M3 |
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
| M1 — storage foundation | implemented, verification **not executed** | **NOT ACCEPTED** |
| M2 — BTC recorder | implemented, live verification **not executed** | **NOT ACCEPTED** |
| M3 — integrity and replay | implemented, unaccepted (inherits M1/M2) | **NOT ACCEPTED** |

The verification machinery exists and is tested
(`.github/workflows/acceptance-m1-m2.yml`,
`infrastructure/scripts/acceptance_m1_m2.py`, 60 verifier tests). It has not
produced a result: GitHub Actions has rejected every job ever queued in this
repository before execution, at zero billable milliseconds — ordinary CI
included. That is an account- or repository-level Actions restriction rather
than a defect here, and the attempt log records what the owner needs to check.

## Verification owed

Two milestones were written in an environment that could not execute their
final check. Both are recorded here rather than left implicit, because an
unverified claim that looks finished is worse than an open one.

**M1 — the stack was never started.** No Docker daemon was available. The
compose file is syntax-validated and 16 integration tests are written but
unrun. Owed:

```bash
make stack-up && make migrate && make test-integration
```

**M2 — the recorder has never seen the venue.** Message shapes come from
Hyperliquid's official SDK type definitions, not from a live connection, and
the fixtures are hand-written from them. Two divergences between those
definitions and the wire format are already known (`Trade` omits `tid` and
`users`; `sz` is typed as an integer where the API sends a decimal string),
which is reason enough to distrust the rest until tested. Owed:

```bash
python -m services.market_data.cli --dry-run --minutes 5 --capture session.jsonl
python infrastructure/scripts/verify_replay.py session.jsonl --out docs/evidence/build-0.1
```

That run answers three questions no fixture can: whether the frames parse,
whether `users` is present on trades (which decides whether trader-level
research is possible at all), and what the real source-to-receipt delay
distribution looks like. `--capture` turns it into a permanent fixture, and
`verify_replay.py` then produces the determinism, data-quality and
gap-detection artifacts from it.

Until a real capture exists, every fixture in the repository is hand-written
from the venue's SDK type definitions, and `synthetic_receipts` is true for all
but one of them — so no latency figure produced from them means anything.

Until both are done, M1 and M2 are **implemented but not accepted**.
