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
| Data | Streams record, raw retained, normalized queryable | M2 |
| Data | Reconnect, gaps, duplicates, freshness, manifests | M3 |
| Replay | Deterministic, independent of wall-clock time | M3 (clock foundation **M0 done**) |
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

M1's verification could not be executed in the environment where it was
written — no Docker daemon was available — so the compose file is
syntax-validated and the integration tests are written but unrun. Running
`make stack-up && make migrate && make test-integration` on a machine with
Docker is the first task of M2, and its output is the M1 evidence artifact.
