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

---

## Attempt 2 — 2026-09-14, commit `61a7595`

**Result: EXECUTED.** The first acceptance run this project has ever completed.

| | |
|---|---|
| Run | `local-20260914T213630Z` |
| Host | Contabo VPS, Europe/Berlin |
| Window (UTC) | 2026-09-14T21:36:31 → 21:51:35 (15 min 4 s) |
| Market data | `MAINNET_PUBLIC`, `api.hyperliquid.xyz` |
| Execution | `DEVELOPMENT`, no credential, order submission disabled |

| Milestone | State | Decision |
|-----------|-------|----------|
| **M1** — storage foundation | `VERIFICATION_FAILED` | **NOT ACCEPTED** |
| **M2** — BTC recorder | `LIVE_VERIFIED` | **ACCEPTED** |

M1's only blocking failure was `integration tests failed` — the object-store
health check called without credentials, fixed at `2c8c4c0`, after which the
same suite passed 16/16 on the same machine. M1 is owed one further run on the
current commit; nothing about its storage behaviour is in doubt.

### What the run established that no fixture could

**`users` is present on public trades.** Identity observed: true. This was the
open question that decided whether trader-level research is possible at all
(ADR-006, TBIE). It is.

**No schema deviation.** Every field the parser relies on was present and no
unknown field appeared, across all four channels. The hand-written fixtures,
built from the venue's SDK type definitions, were right about shape.

**Aggressor attribution stays unproven**, and correctly so. `users` is ordered
[buyer, seller] — direction, not aggression — while `side` carries the
aggressor. Joining them is an inference the public trade frame cannot test:
proving it needs node data with `startPosition`. Until then no markout may be
computed from an assumed taker.

### Data arrival latency, and what it is not

`local_receipt - venue_event_timestamp`; one hop, not execution latency.

| Stream | n | p50 | p90 | p95 | p99 | max | negative |
|--------|---|-----|-----|-----|-----|-----|----------|
| BBO | 5725 | 322.5 | 401.8 | 452.4 | 551.3 | 903.1 | 0 |
| L2_SNAPSHOT | 168 | 385.5 | 447.6 | 514.9 | 594.6 | 640.4 | 0 |
| TRADE | 2347 | 340.1 | 484.5 | 563.1 | 4716.2 | 18968.1 | 0 |

Zero negative observations in 8240 samples suggested a clock offset rather than
real transit. It is not one, and the run carries the evidence to say so:

- **Network.** TCP connect to the venue 56.95 ms, TLS established at 85.69 ms.
  One-way transport is therefore ≈ 28 ms.
- **Clock.** systemd-timesyncd synchronised, stratum 2, root delay 6.546 ms,
  **root dispersion 274 µs**, jitter 6.324 ms over 166 packets. The host clock
  is accurate to roughly 10 ms, not 300.

So the ~300 ms floor is neither our clock nor our network. It is the interval
between the timestamp Hyperliquid puts on an event and the moment that event
reaches a public WebSocket subscriber — a property of the venue, and therefore
the observation floor for *any* consumer of this feed.

**This bears directly on TBIE Gate 0.** Its delay ladder begins at 0, 50, 100
and 250 ms. Every one of those rungs is below the floor measured here, before
any decoding, feature computation, inference, risk check or order transmission
is counted. The ladder should be re-based on what is reachable rather than on
what would be desirable, and Gate 0's question restated accordingly.

### An open question this run raises

The tails differ by channel far more than transport can explain: BBO tops out
at 903 ms while TRADE reaches 18968 ms over the same socket in the same window.
Network transport does not discriminate by channel; per-frame work does, and a
trade is the heaviest frame we handle — one market event plus a trader event
per party.

The likely explanation is therefore our own backpressure, not the venue, which
would mean part of the TRADE distribution measures this recorder rather than
Hyperliquid. It is untested either way. Separating socket-read time from
receipt-stamp time would answer it, and until it is answered the TRADE tail
must not be quoted as a venue property.

### Acceptance states after attempt 2

| Milestone | State | Decision |
|-----------|-------|----------|
| **M1** — storage foundation | implemented; verification failed on a since-fixed defect | **NOT ACCEPTED** |
| **M2** — BTC recorder | verified against the live venue | **ACCEPTED** |
| **M3** — integrity and replay | inherits M1 | **NOT ACCEPTED** |

Five defects were found by running this, none of which any test in the
repository had caught: the withdrawn MinIO images, the ClickHouse healthcheck
addressing ::1, a nullable sorting key, `tid` read as a sequence number, and
`**kwargs: Any` hiding two required credentials from mypy. Two of the five were
detectable without a database and are now covered by tests that were confirmed
to fail against the original code.

Closed by attempt 3.

---

## Attempt 3 — 2026-09-14, commit `d31da57`

**Result: BOTH ACCEPTED.**

| | |
|---|---|
| Run | `local-20260914T221934Z` |
| Window (UTC) | 2026-09-14T22:19:34 → 22:21:35 (2 min 1 s) |
| Market data | `MAINNET_PUBLIC`, `api.hyperliquid.xyz` |

| Milestone | State | Decision |
|-----------|-------|----------|
| **M1** — storage foundation | `VERIFIED` | **ACCEPTED** |
| **M2** — BTC recorder | `LIVE_VERIFIED` | **ACCEPTED** |

Two minutes rather than fifteen, deliberately. M2 was already accepted on the
full-length run at attempt 2 and the latency distribution came from there; what
attempt 3 was owed was M1, whose evidence is the stack, the migrations and the
integration suite, none of which get truer with more recording.

The M1 failure at attempt 2 is closed: the object-store health check called
without credentials, fixed at `2c8c4c0`, with the defect's whole class now
caught by mypy rather than by a run.

The one M2 warning is unchanged and is not a defect: wallet identity is
observed, aggressor attribution stays unproven.

### Acceptance states after attempt 3

| Milestone | State | Decision |
|-----------|-------|----------|
| **M1** — storage foundation | verified against a real stack | **ACCEPTED** |
| **M2** — BTC recorder | verified against the live venue | **ACCEPTED** |
| **M3** — integrity and replay | unblocked; its own acceptance is still owed | pending |

M1 and M2 are the first milestones this project has accepted on evidence rather
than on code review. M3's code has been in the repository since `2d94c7c` and
its dependencies are now met.

### Carried forward, unresolved

**The TRADE latency tail is probably the subscription snapshot, not this
recorder.** Attempt 2 recorded the tail as an open question and guessed at
backpressure. Attempt 3's logs point elsewhere: on subscribing to `trades` the
venue sends recent history, and those frames arrive with venue timestamps 30-35
seconds old, five of them inside one millisecond. The quality engine correctly
calls them implausible and, just as correctly, does not know they are backfill
rather than degraded live data.

Two consequences, neither addressed here. Snapshot frames should be
distinguished from live ones so they are not classified as invalid; and the
attempt 2 latency distribution may be contaminated by them, which would mean
its TRADE p99 and max describe subscription behaviour rather than transport.
The ~300 ms floor at p50 is unaffected — a median is not moved by a burst at
subscribe time — and the reasoning that it is neither our clock nor our network
stands.

---

## M8 — first signed request the venue answered, 2026-09-16, commit `1e29db8`

**Result: the signature is verified. The account is not yet set up.**

| | |
|---|---|
| Host | Contabo VPS |
| Environment | `TESTNET`, `api.hyperliquid-testnet.xyz` |
| Chain | proposal → Risk Engine → intent → Execution Engine → adapter |
| Decision | `APPROVED`, $20 requested, $20 approved |
| Order | BUY 0.00026 BTC, market, `stw-int_90f7daa988a2420ea9ddb3f71dbcb2c1` |
| Venue answer | `REJECTED` — "User or API Wallet 0x2d0e0f299…ae66f99a does not exist." |

### What this establishes

**The signing scheme is right.** The address in the venue's rejection is the
API wallet's own, which means the venue recovered it from our signature. Every
step between an order and that recovery had to be correct for the right address
to come back: the MessagePack encoding, the field order inside the action, the
nonce and vault bytes appended to the hash, the phantom-agent EIP-712 structure,
and the testnet source byte. A mistake in any one of them recovers a different
address, and the venue would have named that one instead.

This was the open question the commit that introduced the adapter recorded as
unanswered: the signature recovered to the signing address locally, but no
request from this repository had ever been accepted by Hyperliquid. One has now
been read, understood and answered.

**The whole chain ran end to end for the first time.** `--check` produced a
priced order without sending it, and the submitting run carried the same intent
through re-validation to the venue. No step was bypassed.

### What it does not establish

Nothing about fills, positions, cancellation, or reconciliation against venue
state. The rejection came before any of that could be exercised, and the order
book was only read, never joined.

### What is actually blocking

The API wallet exists locally and was never registered with the venue: the
"Authorize API Wallet" step in the testnet UI did not complete. The testnet
faucet is a second, related blocker — it drips only to wallets that have
deposited on mainnet, and this account has not.

Neither is a defect in this repository. Both are account setup at the venue.


---

## The recorder stopped for 39 hours, 2026-09-17 → 2026-09-18

**Cause: two purposes sharing one `.env`. Not a defect in the guard that
stopped it.**

| | |
|---|---|
| Last event recorded | 2026-09-17T00:15:17Z |
| Noticed | 2026-09-18T16:13Z, by `make report` |
| Silent for | ~39 h |
| Events held either side | 248,280, from 2026-09-15T04:22Z |

### What happened

`STW_EXECUTION_ENVIRONMENT=TESTNET`, `STW_TRADING_ENABLED=true` and a testnet
API wallet key were written into `.env` so that an order could be placed by
hand. The recorder reads the same file. `market_data_is_read_only` is false
whenever the process could submit an order, and the recorder refuses to start
when it is false, so it refused — correctly. systemd retried on
`Restart=always`, exhausted `StartLimitBurst`, and stopped trying.

Every component did what it was designed to do, and the outcome was 39 hours of
nothing.

### What this says about the design

**The guard was right and stays unchanged.** A process that can reach capital
is not a process whose market-data read is provably risk-free, and weakening
that to keep a recorder running would trade the invariant for uptime.

**The configuration was wrong.** One `.env` was being asked to describe two
processes with opposite requirements. The systemd unit now pins the recorder's
own execution configuration — `DEVELOPMENT`, kill switch engaged, no credential
— which overrides `.env` because environment variables take precedence. The
guard now passes because it is true of that process, not because it was
bypassed. `STW_MARKET_DATA_ENVIRONMENT` is deliberately not pinned: what the
recorder reads stays the operator's choice.

**The refusal was unactionable.** It said what was wrong and not what to
change, which is part of why it stayed unfixed for 39 hours rather than 39
seconds. It now names the three settings and the command that applies them.

### What is still unaddressed

Nothing announced the silence. `Restart=always` is not detection, the gap
registry cannot record a gap from inside a process that never started, and the
freshness monitor dies with the recorder. This was found by a person running a
report two days later.

An alarm that fires when the store stops growing is a different mechanism from
everything M2 and M3 built, because all of those observe the recorder from
inside it. Recorded here as the open item it is.

**Closed the same day** by `services/market_data/watchdog.py` and
`infrastructure/scripts/watch_recording.py`, run every five minutes by
`stw-watchdog.timer`. It asks ClickHouse when it last received anything, and a
recorder that is dead, wedged or refusing to start all look identical from
there: the number stops moving. The outage is written to `data_gaps` against
the traded asset, so M4 reads it through the query it already uses and cannot
call the range clean; the recorder is restarted once, not once per check; and
the outage is closed when data resumes, with the moment it resumed rather than
the moment the timer happened to look.

Worst-case detection is now fifteen minutes — a five-minute period against a
ten-minute staleness limit. It was thirty-nine hours, and it was a person.

What it still does not do is tell anyone. Exit 1 and a journal line are visible
to someone who looks; nothing reaches a phone. That needs an external channel
and a decision about which, so it stays open.
