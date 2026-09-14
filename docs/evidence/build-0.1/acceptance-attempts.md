# M1/M2 Acceptance — attempt log

Every attempt to execute the M1/M2 acceptance verification, with its outcome.
Committed rather than left as a workflow artifact, because a record of *why*
acceptance has not been granted is the part that must not expire.

Verification machinery: `infrastructure/scripts/accept_m1_m2.sh` (the one
acceptance path — `make accept` and `.github/workflows/acceptance-m1-m2.yml`
both call it), `infrastructure/scripts/acceptance_m1_m2.py`,
`services/market_data/acceptance.py`.

Procedure: [`docs/runbooks/m1-m2-acceptance.md`](../../runbooks/m1-m2-acceptance.md).

---

## Attempt 1 — 2026-09-14, commit `43fe3d3`

**Result: NOT EXECUTED.** GitHub Actions rejected the job before it started.

| | |
|---|---|
| Workflow run | [34846504753](https://github.com/sajjadbabamaleki-lgtm/Smart-trading-wallet-/actions/runs/34846504753) |
| Trigger | `workflow_dispatch`, `minutes=5`, `market_data_environment=MAINNET_PUBLIC` |
| Run duration | 5 s (orchestration only) |
| Job | `M1 storage + M2 live venue` — conclusion `failure`, 3 s |
| Steps executed | **0** |
| Billable time | **0 ms** |
| Logs | HTTP 404 — none produced |

### This is not a defect in the workflow

The same signature is present in **every** workflow run in this repository's
history, including the very first one, which predates the acceptance workflow
entirely:

| Run | Commit | Workflow | Jobs | Billable | Steps |
|-----|--------|----------|------|----------|-------|
| 34827372034 | `73b05ed` (M0) | CI | 3 | **0 ms** | 0 |
| 34828620491 | `1749753` (M1) | CI | 3 | **0 ms** | 0 |
| 34830301710 | `ae76237` (M2) | CI | 3 | **0 ms** | 0 |
| 34832054390 | `2d94c7c` (M3) | CI | 3 | **0 ms** | 0 |
| 34846491954 | `43fe3d3` | CI | 3 | **0 ms** | 0 |
| 34846504753 | `43fe3d3` | Acceptance | 1 | **0 ms** | 0 |

Zero billable milliseconds with zero steps and no logs means the runner never
started the job. GitHub accepted the queue request and then declined to execute
it. **Ordinary CI has therefore never passed in this repository either** — a gap
in earlier reporting, which claimed CI was configured on the strength of local
checks without confirming it executed remotely.

### What was ruled out

- **Workflow syntax.** The YAML parses, every `run:` block passes `bash -n`,
  and the job definition is well-formed. A syntax error would still produce a
  started job with a failing step and logs.
- **Repository code.** The failure predates the acceptance work by four commits
  and affects a workflow that only runs lint, types and tests.
- **The live venue and Docker.** Neither was reached; the job never began.

### Probable cause

An account- or repository-level Actions restriction — most commonly exhausted
Actions minutes for a private repository, a spending limit, or an Actions policy
that blocks execution. All are outside this repository and cannot be changed
from a development sandbox.

### What the repository owner needs to check

1. **Settings → Billing and plans → Actions minutes.** A private repository on a
   free plan stops executing jobs once the included minutes are used, and every
   job then fails instantly with zero billable time — exactly this signature.
2. **Settings → Actions → General.** Confirm Actions is enabled and that no
   policy restricts the workflows or actions used
   (`actions/checkout`, `astral-sh/setup-uv`, `actions/upload-artifact`,
   `gitleaks/gitleaks-action`).
3. Re-run [CI](https://github.com/sajjadbabamaleki-lgtm/Smart-trading-wallet-/actions/workflows/ci.yml)
   first. Until CI executes, the acceptance workflow cannot either — and CI is
   the cheaper test of whether Actions works at all.

Once a CI run shows non-zero billable time, re-dispatch the acceptance workflow:

```
Actions → "Acceptance — M1/M2" → Run workflow
  minutes: 5
  market_data_environment: MAINNET_PUBLIC
```

### Local verification that *was* completed at this commit

These were run in the development sandbox and passed. None of them substitutes
for the acceptance run.

| Check | Result |
|-------|--------|
| `ruff format --check` | pass |
| `ruff check` | pass |
| `mypy --strict` (75 files) | pass |
| Unit, replay, security, acceptance-verifier tests | **425 passed**, 16 integration deselected |
| `pip-audit` on the locked set | no known vulnerabilities |
| Docker Compose config syntax | valid |
| Workflow shell scripts (`bash -n`) | 18/18 valid |
| Acceptance verifier against a no-connection run | correctly reported `LIVE_VERIFICATION_INCONCLUSIVE` |

The sandbox cannot perform either half of the acceptance run: no Docker daemon,
and `api.hyperliquid.xyz:443` is refused by the egress gateway with HTTP 403.
The verifier recorded that itself — 4 connection attempts, 0 successes,
`InvalidProxyStatus: proxy rejected connection: HTTP 403` — which is why its
verdict was inconclusive rather than passing.

---

## Acceptance states after attempt 1

| Milestone | State | Decision |
|-----------|-------|----------|
| **M1** — storage foundation | `IMPLEMENTED` · verification **NOT EXECUTED** | **NOT ACCEPTED** |
| **M2** — BTC recorder | `IMPLEMENTED` · live verification **NOT EXECUTED** | **NOT ACCEPTED** |

Neither milestone has been verified against a real storage stack or the real
venue. No claim about the live wire format, the `users` field, or data arrival
latency is supported by evidence at this commit.

**M3 remains blocked**, and M3's own code — already committed at `2d94c7c` —
inherits the same status: implemented, unaccepted.

---

## After attempt 1 — acceptance no longer depends on GitHub Actions

No second attempt has been made. What changed is that one is now possible
without the blocker being fixed first.

Attempt 1 could not run because the only acceptance path was a GitHub Actions
workflow, and Actions does not execute in this repository. That made an
external billing or policy setting a precondition for verifying this project's
own code, which is the wrong dependency for the one procedure that decides
whether three milestones are real.

The steps now live in `infrastructure/scripts/accept_m1_m2.sh`. `make accept`
runs them on any machine with Docker and unrestricted internet, and the
workflow calls the same script rather than restating it — so the two cannot
drift, and an acceptance result means the same thing wherever it was produced.
A preflight stage checks the Docker daemon, the ports and the route to the
venue before starting anything, because the sandbox's own failures (no daemon,
HTTP 403 to `api.hyperliquid.xyz`) both previously surfaced late and disguised
as something else.

The verification itself is unchanged, and so is its status. **M1, M2 and M3
remain NOT ACCEPTED.** Machinery that can run is still not a run.

Next attempt: `make accept` on a machine that passes preflight, then an entry
above recording what it found.
