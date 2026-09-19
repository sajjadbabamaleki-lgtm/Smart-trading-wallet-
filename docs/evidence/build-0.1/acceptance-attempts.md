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

Email was chosen as the channel and is wired: one message when recording
stops, one when it resumes, and nothing on the checks in between. The
thirty-nine-hour outage would otherwise have been 468 identical messages, and
the 468th would be read as carefully as the third. A separate, disk-rate-limited
alert covers the watchdog being unable to run at all, which cannot be
deduplicated in PostgreSQL because being unable to reach PostgreSQL is one of
its causes.

`make watch-test-email` sends one on demand. An alerting path is only ever
exercised at the worst possible moment, and discovering then that the password
was wrong is discovering it too late.

The credential lives in `.env` and nowhere else. Nothing logs the recipient,
the sender or the password; the run report says only whether alerting is
configured.

---

## M4 — the first valid research dataset, 2026-09-18

**Result: VALID.** The first dataset this project has produced that it is
willing to train on.

| | |
|---|---|
| Dataset | `hyperliquid-btc-20260916T101500Z-20260917T001000Z-b2394b6bc775` |
| Range | 2026-09-16T10:15Z → 2026-09-17T00:10Z (13 h 55 m, continuous) |
| Rows | 44,694 — BBO 26,029, L2_SNAPSHOT 9,575, TRADE 9,090 |
| Quality | `VALID` |
| Point-in-time | `PIT_SAFE` |
| Gaps overlapping | 264, **0 open, 0 unrecovered** |
| Excluded by quality filter | 206 |
| Checksum | `b2394b6bc77599e04af01f1f1a8821cae1c06156befd13ab69180eb608cf7044` |

### What had to be true first

The same builder returned `NOT USABLE FOR TRAINING` earlier the same day, over
a 48-hour range, on 320 unrecovered gaps. Both answers were correct, and the
difference between them is the whole of what M4's gate is for.

**The 48-hour range genuinely contained a 40-hour hole.** Nothing had recorded
it: the recorder had exited and the watchdog did not yet exist. It is now in
`data_gaps`, found from the data itself, `UNRECOVERABLE` — so any dataset
spanning it is refused rather than quietly averaged across. Two older holes
were found the same way, including the 24-minute one that opened this whole
line of investigation on 15 September.

**The 320 open gaps were real detections that nobody had closed.** Routine
30-to-116-second silences, median 47 s, each of which resumed seconds later.
The monitor only learned to close a silence after they were written, so they
sat open, and an open gap is a claim that data is still missing. 376 were
closed retroactively against the event in the store that ended each one.

The window chosen here is the one that is continuous: 16 September 10:15 to
17 September 00:10, between two outages rather than across one.

### What this does not establish

Nothing about whether the data is *useful*. It is 14 hours of one asset,
spanning part of one day, and the cost measurement taken the same day says the
tradable horizon is minutes rather than milliseconds — which makes 14 hours a
small number of independent observations. A dataset being valid means it
declares what it contains, not that it contains enough.

---

## M5 — the maker question, answered, 2026-09-19

**Result: resting is roughly three times cheaper than crossing, even after
adverse selection.** The measurement that decides how this system should
execute.

| | |
|---|---|
| Sample | 45,219 rows over 24 h of BTC, of which 9,854 locatable passive fills |
| Markout horizon | 10 s |
| Mean markout | **−0.2033 bps** (adverse) |
| Median | **+0.0616 bps** (favourable) |
| p10 / p25 | −2.278 / −0.307 |
| p75 / p90 | +0.554 / +1.417 |
| Worst / best | −29.88 / +15.59 |
| Taker round trip | **9.98 bps** — 9.0 fees, 0.98 spread |
| Maker round trip | **3.41 bps** — 3.0 fees, 0.41 adverse selection |

### What it means

The fee saving survives. Crossing pays 4.5 bps a side in fees and the spread;
resting pays 1.5 and collects the spread, and gives back only a fifth of a
basis point per fill to adverse selection. Resting is cheaper by a factor of
about 2.9.

**The distribution matters more than the mean.** The median passive fill is
*favourable*. Most of the time nobody is picking you off; the mean is dragged
negative by a left tail — a tenth of fills lose 2.3 bps or worse, and the worst
in a day lost 29.9. That is the signature of adverse selection rather than an
argument against it: you are usually fine and occasionally run over, which is
why the mean is the right input to a cost model and the wrong input to a risk
limit.

### What this changes about the tradable horizon

The earlier reasoning stands but its arithmetic moves. Required move scales
with cost, and time to a given move scales with its square, so a cost of 3.41
instead of 9.98 divides the required horizon by about eight.

| | Taker, 9.98 bps | Maker, 3.41 bps |
|---|---|---|
| Horizon for a 1σ move ≈ cost | ≈ 60 s | ≈ 7 s |
| Horizon for 3× cost | ≈ 9 min | ≈ 1 min |

Seconds to minutes is reachable again. The conclusion that millisecond trading
is dead is unchanged — 322 ms still buys a 0.066 bps median move against a 3.41
bps floor — but the door that 9.98 bps closed on the seconds range is open at
3.41.

### What it does not establish, and both are load-bearing

**Fill probability is not modelled at all.** A resting order earns nothing if
nobody trades with it, and misses the move it was right about. Crossing costs
three times more and is certain. Nothing here prices that trade-off, and a
strategy that assumes it gets the maker fee whenever it wants one is assuming
the part that was not measured.

**This is a lower bound on adverse selection.** Queue position is unmodelled:
the measurement treats any aggressive trade at our level as filling us, while a
real queue fills hardest exactly as the level is cleared, which is the adverse
case. Real adverse selection is worse than 0.2033 bps by an amount this data
cannot bound. The cost model carries the figure with that stated, and
`CostModel.maker_round_trip_bps` documents the crossover: about 4 bps of
adverse selection would erase the advantage entirely, which is not far away.

Both are M6's to settle, against a specific strategy, in an execution-aware
backtest.

---

## M6 — the first baseline strategy, and the horizon it closed, 2026-09-19

Three strategies over the same 24 hours of recorded BTC, one control, one
comparison, one candidate. Entry on book imbalance above 0.30; the candidate
additionally required signed taker flow over a 10-second window to agree;
30-second timer exit; 0.001 BTC per trade; fills at the touch after the
measured 322 ms arrival delay.

| | trades | won | gross | fees | net | mean per trade |
|---|---|---|---|---|---|---|
| control (always flat) | 0 | — | 0 | 0 | 0 | — |
| imbalance only | 1,689 | 14 | −7.53 | 123.49 | −131.02 | **−9.549 bps** |
| imbalance + flow | 991 | 12 | −1.742 | 72.45 | −74.20 | **−9.216 bps** |

The control traded nothing, so the harness is not inventing fills.

### What the numbers say

Per trade, on a notional of about $76:

```
imbalance only:  gross -0.587 bps, fees +9.620, net -10.207
imbalance + flow: gross -0.231 bps, fees +9.620, net  -9.851
```

**The loss is the fee, not the signal.** Gross is approximately flat in both.
The flow filter earned its place — it halved the trade count and cut the gross
loss per trade by about 60% — and it made no difference to the outcome, because
the outcome was never about signal quality. Entry slippage was 0.053 and 0.139
bps against a 9.62 bps fee: latency is confirmed irrelevant at this scale, which
is the third independent measurement saying so.

### Correction to the M5 horizon estimate above

The M5 entry projected "≈ 60 s" for taker and "≈ 7 s" for maker by scaling the
322 ms measurement forward by the square root of time. **That extrapolation is
withdrawn.** It does not survive its own inputs:

```
sigma implied by the 322 ms median : 0.098 bps
sigma implied by the 322 ms p90    : 0.711 bps
                                     7.3x apart
  scaled from the median: taker cost reached at 55.7 min, maker at 6.5 min
  scaled from the p90   : taker cost reached at  1.1 min, maker at 0.1 min
```

Fifty times apart depending on which quantile is scaled. A distribution that
disagrees with itself by that much is nowhere near Gaussian, and the
square-root-of-time rule has nothing to stand on. The "≈ 7 s" figure was
reported to the product owner as a conclusion and was wrong by about two orders
of magnitude.

### Measured instead: the horizon ladder

`make ladder` measures each horizon independently, over 57,584 recorded quotes.
Unsigned median mid movement, against 3.41 bps resting and 9.98 bps crossing:

| horizon | count | p50 | p90 | p95 | p99 | clears |
|---------|-------|-----|-----|-----|-----|--------|
| 1 s | 46,447 | 0.00 | 0.98 | 1.48 | 3.30 | — |
| 5 s | 46,444 | 0.12 | 1.84 | 2.72 | 4.97 | — |
| 10 s | 46,440 | 0.31 | 2.61 | 3.69 | 6.27 | — |
| 30 s | 46,423 | 1.04 | 4.53 | 6.04 | 9.92 | — |
| 60 s | 46,408 | 1.85 | 6.41 | 8.27 | 13.48 | — |
| 300 s | 46,255 | 4.63 | 14.23 | 18.26 | 25.77 | resting |
| 900 s | 45,937 | 7.28 | 22.38 | 30.14 | 42.49 | resting |
| 1800 s | 45,380 | 10.36 | 28.25 | 37.32 | 52.21 | both |
| 3600 s | 44,515 | 13.82 | 37.15 | 47.31 | 70.80 | both |

The move is unsigned, so each figure is a **ceiling**: what a strategy that
called direction perfectly could have captured. At the 30-second hold the
baseline used, that ceiling is 1.04 bps against 9.62 bps of cost — a factor of
nine. No signal of any quality could have made that strategy profitable.

Crossing needs about 30 minutes. Resting turns viable somewhere between 1 and 5
minutes, and no rung was measured in between.

### Status

**M6 result: `NO_EDGE_FOUND` at the sub-minute horizon, for cost reasons that
no signal can overcome.** Recorded as a result, per Rev.2 §§30–32, not as a
failed attempt to be retried with a different threshold.

The branch is closed rather than explored further. **ADR-011** records why: the
horizon was never specified by any document — Rev.2 §3 says "one initial trading
horizon" and leaves the number open — and seconds were inherited from the tick
recorder rather than chosen. The product objective in Phase 1 §1 is a trader
that reads a chart, reads the news, studies one to two years of behaviour, and
decides long, short or nothing. At that horizon a round trip costs 0.1% against
daily moves measured in percent, and cost stops being the binding constraint.

What carries forward unchanged: the cost model, the calibration, the ladder, the
backtest engine's point-in-time discipline, the control-strategy harness, and
the finding that latency is irrelevant to this project. What changes is which
data the strategy reads.

---

## The first candle rule, and why its holdout was not spent, 2026-09-19

Textbook trend-following on stored candles, with the decision taken at a
close and filled at the next open. Sixteen runs: two assets, 4h and 1d, four
rule variants. The reserved 180 days were not evaluated.

### What the matrix found

**1d is not weak, it is inverted.** Every variant lost, gross profit per trade
ran from −26 to −312 bps, and shuffled orderings of the rule's own decisions
beat it up to 18 times in 20. Closed.

**4h carries a signal, and confirmation converts it.** Requiring a regime
change to hold for two candles before acting on it:

| 4h | trades | return | gross/trade | drawdown |
|----|--------|--------|-------------|----------|
| BTC, no confirmation | 155 | +0.1% | +10.86 | 2.3% |
| BTC, confirmed | 106 | **+2.6%** | **+34.76** | 1.9% |
| SOL, no confirmation | 150 | −0.1% | +9.17 | 4.5% |
| SOL, confirmed | 103 | **+1.4%** | **+23.54** | 4.4% |

Cost is 9.98 bps per trade throughout. Buy-and-hold returned +1.2% on BTC and
−3.9% on SOL over the same period, with drawdowns of 9.1% and 13.1%.

**The prediction recorded before the change was wrong in its reasoning.** The
`Confirmed` docstring predicted that the trade count and fee bill would fall
while gross per trade stayed roughly flat. Gross per trade roughly tripled.
Exposure was unchanged at 47%, so the removed flips were not merely paying
fees — they were cutting winning positions short. Average hold went from 10
candles to 15. The mechanism was right and the stated cause was not the main
one.

**The calm filter is rejected.** Standing aside in high volatility cut BTC to
−2.3%: it removed the periods where trends pay.

### Why the holdout was not spent

Two tests were run first, both on data already spent, and one failed.

Twenty shuffles cannot support a significance claim, so it was raised to 200.
And the training period was split in half, because a rule that earned
everything in one part of it found an episode rather than a regularity.

| 4h, confirmed | first half | second half | full |
|---------------|-----------|-------------|------|
| BTC | +1.3% (3/200) | +1.2% (0/200) | +2.6% (0/200) |
| SOL | **−1.2% (48/200)** | +2.6% (6/200) | +1.4% (9/200) |

BTC is consistent to an unusual degree: return positive in both halves,
drawdown 1.9% in all three periods, gross per trade between 31.60 and 35.09.

SOL is not. It lost in the first nine months, and 48 of 200 random orderings
of its own decisions did better there — no information at all in that half.
All of its profit came from the second half. Over the same nine months BTC
made +1.3% at 3/200 on a correlated asset, which is what makes this fragility
rather than a market that offered nothing.

The pass criterion was written before the numbers were seen: both halves
positive, and fewer than 10 of 200 shuffles matching over the full period. It
did not say whether "both halves" meant per asset or across assets. That
ambiguity is resolved by ADR-011 §5, written the previous day:

> A rule that works on one asset and not the other has demonstrated a property
> of that asset's recent past, not an edge.

So: **not ready for the holdout.** The 180 days remain unexamined.

### What was done instead

The test set was widened rather than the rule set. Trying further variants
until one passes is the overfitting this project's gates exist to prevent;
adding assets tunes nothing, leaves the rule untouched, and only exposes it to
more opportunities to fail.

Phase 1 §2 names BTC, ETH, SOL and BNB. History for ETH and BNB costs a
download, and four assets across two halves is eight tests rather than four.
ADR-011 §5's out-of-sample reasoning extends to them unchanged: this is
research, not the experimental trading pipeline Rev.2 §3 scopes to BTC.

### Rules evaluated so far, for the record

Phase 4's discipline needs this list to exist, because the holdout is spent
once and "how many things had already been tried" cannot be answered from
memory: `trend-following`, `trend-following-calm`, `trend-confirmed`
(confirm=2), `trend-confirmed-3`, each on 4h and 1d, on BTC and SOL.

---

## Trend-following: NO_EDGE_FOUND over six years, 2026-09-19

The 18-month Hyperliquid window said confirmation converted a marginal signal
into a small profit on BTC, consistently across both its halves. Six years of
4h candles from Binance, same unchanged rule, four assets, say it did not.

| 4h, confirmed | full 6y | first half | second half | gross/trade |
|---------------|---------|-----------|-------------|-------------|
| BTC | **−10.0%** | −7.6% | −2.4% | **−17.19** |
| ETH | **−8.1%** | −3.2% | −4.9% | **−12.33** |
| SOL | **−5.1%** | −5.7% | +0.6% | **−5.04** |
| BNB | **−1.8%** | −1.9% | +0.1% | +5.13 |

Win rates: 49.7%, 51.5%, 54.6%, 53.8%. A coin flip.

**Gross per trade is the column that settles it.** That is profit before fees,
and it is negative on three assets of four. The rule does not lose to costs;
it loses to being wrong. Two of twelve period-rows are positive and both are
under a percent.

And against buy-and-hold: −65, −58, −282, −234 points.

So the +34.76 bps per trade on BTC in the 18-month window was a property of
that window, not of the rule. Downloading six years was the right call and it
did the job it was for — it made the test harder and the rule failed it.

**Result: `NO_EDGE_FOUND` for the trend-following family** (Rev.2 §§30–32),
across `trend-following`, `trend-following-calm`, `trend-confirmed` and
`trend-confirmed-3`, on 1h, 4h and 1d, on four assets, on two venues' history.

**The 180-day holdout was never spent.** It remains unexamined, and for this
family it no longer needs to be.

### A method error this run exposed

BTC's full-period row reads `0/200` — no shuffled ordering of the rule's own
decisions did as well — next to a 10% loss. Both are true, and the
juxtaposition is the lesson: over a period where the market rose about 55%,
shuffling separates a long-biased rule's direction from the drift, so the
shuffles lose more than the rule does. `Shuffled` was measuring drift capture,
not timing, and the report said nothing about that.

Earlier conclusions leaned on that column. In the 18-month window the rule
also beat buy-and-hold, so nothing was concluded that the evidence did not
support — but the number I weighted was the weaker one, and `vsBH` at −65 was
the one that mattered.

`LongWhenActive` is the fix: the candidate's own positions with the direction
calls removed — LONG wherever it wanted a position of either sign, FLAT
wherever it wanted none. Same trades, same fees, same time in market, no
opinion about which way. A candidate that cannot beat it has short calls worth
nothing. The verdict no longer claims a shuffle win as evidence of timing
unless the candidate also beats this control.

### Next family: mean reversion

Chosen because the data proposed it rather than for symmetry. On daily candles
the trend rule's gross per trade ran −26 to −312 bps, which is not a weak
signal but an inverted one, and a signal that is reliably wrong is a signal.

`MeanReversion` acts only in a range, because in a trend "far from the
average" is where price belongs and betting against it is how this family
loses everything in one move. That requirement also makes the two families
complementary by construction — tested, not hoped: wherever the trend rule
holds a position, the reversion rule is flat.

The null hypothesis is unchanged: it loses money net of cost, and less than
buy-and-hold earns.

### Rules evaluated, cumulative

`trend-following`, `trend-following-calm`, `trend-confirmed`,
`trend-confirmed-3` — on 1h/4h/1d, BTC/ETH/SOL/BNB, Hyperliquid 2y and
Binance 6y. Now adding `mean-reversion` and `reversion-confirmed`.

---

## Funding extremes: the edge existed and stopped, 2026-09-20

Positioning rather than pattern: `FundingExtreme` shorts when funding sits in
the top tenth of its own month — the long side paying unusually hard to stay
long — and buys the opposite extreme. Six years, four assets, 200 shuffles,
funding charged to every position from measured history.

| 4h | first half | second half | full | gross/trade |
|----|-----------|-------------|------|-------------|
| BTC | **+9.8%** (0/200) | −1.6% | +8.2% | +20.75 |
| BNB | **+12.4%** (0/200) | −3.7% | +8.7% | +18.98 |
| ETH | **+1.1%** (8/200) | −8.5% | −7.4% | −4.00 |
| SOL | −8.9% (103/200) | −3.8% | −12.7% | −19.59 |

The criterion was written before the numbers: three of four assets positive in
both halves. **Zero of four.** The holdout stays unexamined.

### What charging funding changed

The previous run charged none, and this rule sits systematically on the
receiving side — it shorts when funding is highest, which is when shorts are
paid most. Charging it helped every period, by 0.3 to 4.6 points, and it
changed one verdict outright: BTC's first half went from −5.7 against
buy-and-hold to **+12.3**, the first and so far only `SURVIVED` in this
project with funding included.

BNB moved the other way against buy-and-hold, from −229 to −234, and the
reason is in the data: shorts paid in 75% of BNB's settlements, so charging
funding credited a long-only control there. The asset is the exception to the
other three and worth remembering.

The code that charges it was written and pushed before this result arrived,
which is the only thing that makes re-running legitimate rather than a second
attempt at a number that had already been seen.

### What the first halves say

BTC's first half is what a real edge looks like: +41.00 bps of gross profit
per trade against 10.00 of cost, 288 trades, no shuffled ordering of its own
decisions doing as well in two hundred attempts, and 12.3 points better than
holding. BNB's is the same shape. On three of four assets the first half was
profitable.

**It is gone.** In the second half all four assets lost.

### Two rule families, one pattern

| | 2020–2023 | 2023–2026 |
|---|-----------|-----------|
| trend-following | mixed | mixed, negative overall |
| funding-extreme | **3 of 4 positive** | **0 of 4 positive** |

Two unrelated mechanisms — one reading price, one reading positioning —
worked in the earlier period and stopped in the later one. That is the most
informative result this project has produced, and it is not a result about
either rule.

### The explanation is not yet established, and there are two

**Efficiency.** Crypto perpetuals in 2020–2022 were retail-dominated and
heavily levered, funding extremes preceded liquidation cascades, and the
pattern was exploitable. Institutional participation arbitraged it away. If
this is right, simple rules of this kind are finished permanently.

**Regime.** The second period was a sustained trend, and a contrarian rule
loses in a trend regardless of how efficient the market is. If this is right,
the rule returns when the regime does.

Six years cannot separate these, because the split has one boundary and both
stories predict the same thing on either side of it. Nine can: BTC, ETH and
BNB list on Binance from 2017, which adds the 2018 bear market and the
2019 recovery. A rule that worked in 2017–2020 *and* 2020–2023 and not after
points at efficiency; one that worked only in 2020–2023 points at regime.

`--periods N` splits the training period into any number of equal parts rather
than two, because "did it work throughout" and "when did it stop" are
different questions and two parts can only answer the first. Each part carries
its warmup backwards into data already known, so no part decides on a candle
belonging to the next.

### Rules evaluated, cumulative

`trend-following`, `trend-following-calm`, `trend-confirmed`,
`trend-confirmed-3`, `mean-reversion`, `reversion-confirmed`,
`funding-extreme`, `funding-with-trend` — on 1h/4h/1d, BTC/ETH/SOL/BNB,
Hyperliquid 2y and Binance 6y, with and without funding charged. The 180-day
holdout has never been evaluated.

---

## The funding edge decayed: nine years, four periods, 2026-09-20

The six-year run could not separate two explanations for a rule that worked
before 2023 and not after — markets became more efficient, or the regime
changed — because a single split has one boundary and both stories predict the
same thing either side of it. Nine years of BTC, ETH and BNB with the training
period split four ways can.

### A data fact that limited the question

Binance perpetual futures launched in September 2019, so funding history begins
there regardless of how far the candles reach:

| asset | funding from | settlements |
|-------|--------------|-------------|
| BTC | 2019-09-10 | 7,700 |
| ETH | 2019-11-27 | 7,466 |
| BNB | 2020-02-10 | 7,241 |

The first quarter of the nine-year candle range therefore has no funding at
all, the rule correctly stayed flat through it, and BTC made 7 trades there
while ETH and BNB made none. That period is not evidence either way, and the
question cannot be pushed further back at this venue.

The candle archive also has eight holes, the largest about a day in February
2018 — declared by the loader, not filled.

### Three usable periods

| period | BTC | ETH | BNB |
|--------|-----|-----|-----|
| ~2019–2021 | +7.9% | −3.9% | +13.9% |
| **~2021–2023** | **+2.1%** (vsBH **+4.2**) | **+4.0%** (vsBH **+8.8**) | **+0.8%** (vsBH **+2.2**) |
| ~2023–2026 | −0.2% | −9.9% | −3.9% |

The middle period — which contains the 2022 collapse — is profitable on all
three assets *and* beats buy-and-hold on all three, at 0/200, 1/200 and 3/200
shuffles. BTC's row there is the project's second `SURVIVED`.

The most recent period is negative on all three.

### What settles efficiency against regime

Gross profit per trade, in time order:

```
BTC:  +43.35  →  +18.34  →   +8.58
BNB:  +66.80  →   +7.51  →  −13.78
ETH:  −17.77  →  +25.82  →  −25.74
```

Two of three decay monotonically. A regime explanation predicts oscillation —
a contrarian rule should do badly in trends and well in ranges, and those
alternate. Monotonic decay across three consecutive multi-year periods is what
an edge being competed away looks like.

ETH does not decay monotonically, so this is a weight of evidence rather than
a proof. But the direction is consistent, it holds on the two assets with the
cleanest data, and no period after 2023 is positive on any asset.

### The result

**`NO_EDGE_FOUND` for the funding family in the current market**, and the
reason is specific rather than a shrug: the edge was real, it beat
buy-and-hold on three assets across the 2021–2023 period at better than 1-in-50
against its own shuffles, and it has decayed to nothing.

**The holdout has still never been evaluated.** Eight rules have now been
tested and none reached it.

### What this implies beyond the rule

Both families tested so far take inputs that anyone can compute from public
data: candles through standard indicators, and a funding rate the venue
publishes. One of them demonstrably worked and was competed away over four
years. That is the mechanism by which any publicly computable signal ends, and
it is a reason to stop looking for more of them rather than to try a ninth.

What is left is inputs that are not uniformly available:

1. **News and its interpretation.** A language model's reading of an event is
   not a statistic everyone derives identically from the same series, which is
   the property every failed signal here lacked. It is also the product owner's
   original requirement.
2. **This project's own recorded microstructure.** The tick recorder holds
   order-book and trade data at a grain nobody else has in this exact form, and
   ADR-011 §6 already assigns it to cost and execution rather than signal.
3. **Execution quality.** Not an edge in direction, but a real and measurable
   saving, and Phase 8 requires the slippage model be recalibrated against
   observation anyway.

### A reporting artifact worth naming

Periods where the rule made no trades report `200/200` shuffles and a 0.0%
return. That is arithmetically correct — every shuffle of an all-FLAT decision
sequence also returns zero — and it reads like a catastrophic failure rather
than an absence of data. The zero-trade rows above should be read as "no
funding history", which the settlement dates confirm.

### Rules evaluated, cumulative

`trend-following`, `trend-following-calm`, `trend-confirmed`,
`trend-confirmed-3`, `mean-reversion`, `reversion-confirmed`,
`funding-extreme`, `funding-with-trend` — on 1h/4h/1d, BTC/ETH/SOL/BNB,
Hyperliquid 2y, Binance 6y and 9y, with and without funding charged, split in
two and in four.
