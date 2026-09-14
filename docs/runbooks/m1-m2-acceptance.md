# Runbook — M1/M2 acceptance

How to produce the evidence that decides whether M1 (storage foundation) and M2
(BTC Hyperliquid recorder) are **accepted**. Until this runs, M1, M2 and M3 are
implemented and unaccepted, and nothing downstream may start: Build 0.1 Rev.2
§23 gates the first research dataset on recorder integrity passing.

This is the one procedure the project currently cannot run for itself. GitHub
Actions has rejected every job ever queued in this repository at zero billable
milliseconds, and the development sandbox has no Docker daemon and no route to
`api.hyperliquid.xyz`. It needs a machine with Docker and ordinary internet
access — a laptop is enough.

## What it does

```
preflight → provenance → stack up → migrate → verify stores
→ integration tests → assert execution guard → live recording
→ replay verification → container logs → verdict
```

One script holds all of it: `infrastructure/scripts/accept_m1_m2.sh`. `make
accept` and `.github/workflows/acceptance-m1-m2.yml` both call it, so a result
means the same thing wherever it was produced.

## What it is not

It reads public market data and **nothing else**. It loads no credential,
submits no order, and asserts the execution guard before opening any socket. A
configuration that could reach capital stops the run before the network is
touched.

It defaults to **mainnet** market data. That is deliberate and it is not a
capital risk: Hyperliquid's testnet book is thin and unrepresentative, so
testnet data cannot answer what the real venue sends, while reading a public
book risks nothing. ADR-009 separates market data from execution precisely so
this choice is available without widening the execution guard.

## Where to run it

A server, not a laptop. Two reasons, and only the first is about this run:

- **The acceptance's latency figures are relative to where they were measured.**
  The source-to-receipt delay is dominated by the physical distance between the
  recording host and the venue, so identical code produces different numbers in
  Singapore and in Frankfurt. The run records its own TCP connect and TLS
  handshake times to the venue in `provenance.txt` for exactly this reason — a
  latency distribution without that context cannot be compared against another
  run, and TBIE Gate 0 is a comparison.
- **From M2 onward the recorder wants to stay up.** A laptop sleeps, changes
  networks and gets closed. Each of those is a gap, and the gap registry will
  faithfully record every one.

Pick the region deliberately and keep it fixed across runs: changing it
silently changes every latency number. A small VPS — 2 vCPU, 4 GB RAM, 40 GB
disk — is enough for the stack plus a multi-hour capture.

### First-time setup on a fresh Ubuntu server

```bash
# Docker, from Docker's own repository rather than the distro's older package
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER" && newgrp docker

# uv, git, make
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt-get update && sudo apt-get install -y git make
source "$HOME/.local/bin/env"

git clone https://github.com/sajjadbabamaleki-lgtm/Smart-trading-wallet-.git
cd Smart-trading-wallet-
make setup
make accept
```

If `make accept` reaches `preflight passed`, the server qualifies. If it does
not, it names which check failed and why, before starting anything.

## Prerequisites

- Docker with the daemon running, and Docker Compose v2
- [uv](https://docs.astral.sh/uv/)
- Outbound HTTPS and WebSocket access to `api.hyperliquid.xyz`
- Ports free: 5432, 8123, 9009, 6379, 9000, 9001
- ~2 GB of disk for the stack, plus the capture

Preflight checks every one of these and stops before starting anything if any
fails, naming the remedy. It costs about ten seconds and is not skippable — a
blocked egress discovered fifteen minutes in looks like a venue outage.

## Running it

```bash
make setup          # once
make accept         # the whole acceptance
```

Options go through `ACCEPT_ARGS`, or call the script directly:

```bash
make accept ACCEPT_ARGS="--minutes 120"
bash infrastructure/scripts/accept_m1_m2.sh --minutes 120 --stop-stack
```

| Option | Default | Notes |
|---|---|---|
| `--minutes N` | `15` | Length of the live recording |
| `--market-data ENV` | `MAINNET_PUBLIC` | Or `TESTNET` |
| `--minimum-frames N` | `50` | Below this the live observation is `INCONCLUSIVE` |
| `--out DIR` | `docs/evidence/build-0.1/live` | Evidence destination (git-ignored) |
| `--stop-stack` | off | Stop the stack at the end; volumes are kept either way |
| `--health-timeout N` | `240` | Seconds to wait for the stores to become healthy |

**On the length.** Fifteen minutes answers "do the frames parse and is `users`
present". It does not produce a latency distribution worth quoting. For the
capture that becomes the project's permanent fixture, run `--minutes 120` or
more, and prefer a period with real activity — a quiet hour understates
throughput and overstates gap frequency.

## Reading the result

The script exits non-zero unless both milestones are `ACCEPTED`. The report is
`m1-m2-acceptance.md` in the evidence directory.

| Verdict | Meaning | Next step |
|---|---|---|
| `ACCEPTED` | Verified against the real stack and the real venue | Record it; M3 unblocks, then M4 |
| `NOT_ACCEPTED` | A check failed | The report names which; fix and re-run |
| `LIVE_VERIFICATION_INCONCLUSIVE` | Too little was observed to decide | Not a failure. Re-run longer, or at a busier time |

`INCONCLUSIVE` is a real outcome and must not be reported as either of the
others.

## Three questions the run answers that no fixture can

Every fixture in this repository is hand-written from Hyperliquid's SDK type
definitions, which are known to diverge from the wire format. The run replaces
assumption with observation on:

1. **Do the frames parse?** Against the real wire format, not the SDK's idea
   of it.
2. **Is `users` present on trades?** It decides whether trader-level research
   (ADR-006, TBIE) is possible at all. Third-party API documentation says
   `WsTrade` carries `users: [buyer, seller]` and `tid`; this repository has
   never seen it, and documentation is not evidence.
3. **What is the real source-to-receipt delay?** One hop of the path TBIE
   Gate 0 depends on. Note what it is *not*: receipt minus venue timestamp,
   over unsynchronised clocks, and not the end-to-end decision latency.

## After the run

**Record the attempt in
[`docs/evidence/build-0.1/acceptance-attempts.md`](../evidence/build-0.1/acceptance-attempts.md),
whatever happened.** A failed or inconclusive attempt is evidence, and the
attempt log is committed specifically so that the record of *why* acceptance
has not been granted does not expire. The evidence directory itself is
git-ignored; the attempt log is not.

If the verdict is `ACCEPTED`, also update the status tables in
`docs/evidence/build-0.1/README.md` and the root `README.md`, which currently
say M1–M3 are implemented and unaccepted.

Keep the capture. `live-btc-capture.jsonl` is the first real session this
project has ever held, it replays deterministically, and it becomes the fixture
every later component is tested against.

## Troubleshooting

| Preflight says | Cause | Remedy |
|---|---|---|
| `docker daemon is not running` | Docker not started | Start Docker Desktop, or `sudo systemctl start docker` |
| `port N is already in use` | Another service holds it | Stop it, or stop a previous stack with `make stack-down` |
| `api.hyperliquid.xyz is unreachable` | Egress filter, VPN or corporate proxy | Run from an unrestricted network. This is what blocks the sandbox |
| `.env exists` (warning) | A stale local config | The run's own settings override it, but an unknown key in it still fails startup — `extra="forbid"` |

| Later failure | Cause | Remedy |
|---|---|---|
| Services never become healthy | Slow first pull, or low memory | Re-run; `--health-timeout 600` on a slow link |
| `minio-init exited 1` | Bucket bootstrap failed | `make stack-down` then re-run; check `container-logs/minio-init.log` |
| Integration tests fail | A real M1 defect, or a half-migrated store | Read `integration.txt`; `make stack-down` and re-run applies migrations cleanly |
| Safety assertion fails | Configuration could reach capital | Do not work around it. Something widened the execution guard; that is the finding |

The stack is left running unless `--stop-stack` is given, so the recorded data
can be inspected in ClickHouse and PostgreSQL afterwards. `make stack-down`
stops it and keeps the volumes.
