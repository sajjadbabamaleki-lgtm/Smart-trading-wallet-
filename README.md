# Smart Trading Wallet

An AI-powered automated trading platform for **BTC, ETH, SOL and BNB**, trading
perpetual futures with an independent risk-control authority over every position.

This repository holds the complete V1 architecture program — ten approved phase
specifications. No trading, data, or model code has been implemented yet.

## What the system is

Version 1 is defined in [Phase 1](docs/phase-1-master-product-and-risk-specification.md)
as a trading application that continuously analyses market conditions, identifies
Long and Short opportunities, and independently controls portfolio- and
position-level risk. Its objective is to **maximise risk-adjusted returns while
prioritising capital preservation** — not to maximise trading frequency.

Three operating modes are in scope:

- **Autopilot** — fully automated analysis, risk approval, execution and position management.
- **Copilot** — the same analysis, but a proposed trade requires user approval.
- **Research** — analytical transparency and strategy evaluation, no execution.

Wallet connectivity starts with **Phantom** and **Trust Wallet**, behind a
unified wallet adapter so the trading core stays wallet-agnostic. The user's seed
phrase or private key is never transmitted to or stored by backend
infrastructure; automation signs through an isolated execution credential
instead. Autopilot is **off by default** and requires explicit trading
authorization, which is a separate grant from logging in.

The initial execution venue is **Hyperliquid**, subject to final production
validation.

## Decision pipeline

```
Market Data
  → Historical Intelligence Engine
  → Market Regime Detection
  → Strategy / AI Engine
  → Trade Candidate
  → RISK ENGINE            (approve / modify / reject)
  → Execution Intent       (immutable, expiring, single-use)
  → Execution Engine
  → Trading Venue
  → Reconciliation → Continuous Risk Monitoring → Audit & Attribution
```

The architectural rule behind that ordering: **the AI/Strategy Engine never has
direct authority to execute trades.** The Risk Engine holds veto authority and
decides whether capital may be exposed; neither a model, a strategy, the
frontend, nor a user setting may exceed its hard limits. Surrounding the pipeline
are an independent kill switch, Safe Mode, security monitoring, and an immutable
audit trail.

## Specifications

See [`docs/`](docs/README.md) for the library and the twenty cross-cutting
invariants that govern implementation work.

| Phase | Document |
|-------|----------|
| 1 | [Master Product & Risk Specification](docs/phase-1-master-product-and-risk-specification.md) |
| 2 | [Data Research & Architecture](docs/phase-2-data-research-and-architecture.md) |
| 3 | [Historical Data Engine](docs/phase-3-historical-data-engine.md) |
| 4 | [Research & Backtesting Laboratory](docs/phase-4-research-and-backtesting-laboratory.md) |
| 5 | [Strategy Intelligence & AI/ML Architecture](docs/phase-5-strategy-intelligence-and-ai-ml-architecture.md) |
| 6 | [Risk Engine & Execution Architecture](docs/phase-6-risk-engine-and-execution-architecture.md) |
| 7 | [Testnet, Paper Trading & Shadow Validation](docs/phase-7-testnet-paper-trading-and-shadow-validation.md) |
| 8 | [Limited-Capital Live Trading & Production Qualification](docs/phase-8-limited-capital-live-trading-and-production-qualification.md) |
| 9 | [Product Interface, Wallet Integration & Human Control Layer](docs/phase-9-product-interface-wallet-integration-and-human-control-layer.md) |
| 10 | [Security Architecture, Independent Audit & Production Launch Gate](docs/phase-10-security-architecture-independent-audit-and-production-launch-gate.md) |

## Validation ladder

Capital is reached only through the full sequence, and each stage has its own
acceptance and rejection criteria:

```
Historical Backtest → Out-of-Sample → Walk-Forward → Stress Testing
→ Testnet → Paper Trading → Shadow Trading → Limited-Capital Live
→ Production Qualified
```

Passing one stage never implies passing the next. Production status is
reversible, and the unit that holds it is a specific trading configuration
(Strategy × Asset × Model × Risk × Execution), not the application as a whole.

## Implementation program

The architecture phase is closed. Phase 10 §116 names the successor — not
"Phase 11" — and the program documents live in [`docs/build/`](docs/build/README.md).

The active plan is **[Build 0.1 Rev.2 — Lean BTC Quant MVP](docs/build/build-0.1-rev2-lean-btc-quant-mvp.md)**,
which narrows the first implementation without changing the architecture above:
**BTC only**, Hyperliquid testnet, one horizon, one strategy family, on-chain and
commercial datasets deferred, and AI removed from the critical path so the
infrastructure can be proven before model complexity arrives. Risk and execution
move earlier, so the capital-control boundary exists before any AI does.

```
M0 Rev.2 Foundation → M1 Storage → M2 BTC Hyperliquid Live Recorder
→ M3 Data Integrity & Replay → M4 BTC Research Dataset → M5 Baseline Research
→ M6 Event-Driven Backtesting → M7 Risk & Execution Skeleton → M8 Testnet
→ M9 Paper → M10 Shadow → ML only if justified → Limited Live only after all gates
```

Immediate engineering target: **M0 Rev.2 → M1 → M2**. Real capital is prohibited
and mainnet execution is hard-blocked throughout; profitability is not a Build
0.1 acceptance criterion. `NO_EDGE_FOUND` is a valid outcome of this program and
may legitimately end the trading research rather than trigger weaker standards.

## Research candidates

Experimental component research lives in [`docs/research/`](docs/research/README.md) —
off the critical path, with no production authority, each carrying its own
promotion gate and its own valid negative outcome. Currently:
**[Trader Behavior Intelligence Engine](docs/research/trader-behavior-intelligence-engine.md)**
(v1.1, evidence-audited), which asks whether the point-in-time estimated skill of
pseudonymous Hyperliquid wallets carries predictive information beyond anonymous
market data. The audit finds the predictive information well supported and
executable profitability unproven, so latency viability becomes its Gate 0. It
constrains M0 clock design and M2 recorder scope — identity-linked events and
receipt timestamps discarded now may be impossible to reconstruct later.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
make setup             # create the virtualenv, install dependencies
make check             # lint, typecheck, tests — exactly what CI runs
make stack-up          # start PostgreSQL, ClickHouse, Redis, MinIO locally
make stack-verify      # check every store is reachable and correctly configured
make migrate           # verify, then apply pending migrations
make test-integration  # run integration tests against the running stack
make help              # all targets

# Record from the live testnet feed without writing anything
python -m services.market_data.cli --dry-run --minutes 5

# Replay a recorded session deterministically
python -m services.market_data.cli --replay tests/fixtures/hyperliquid/btc_session.jsonl
```

`make stack-verify` is how the storage claim is checked rather than asserted: it
reports each store's status, latency and configuration, and exits non-zero if
any is unusable. It also flags two silent failure modes — Redis with persistence
enabled (it must stay ephemeral, never capital state) and an unversioned archive
bucket (a rewritten key would destroy the original raw evidence).

Configuration comes from environment variables prefixed `STW_`; copy
`.env.example` to `.env` to start. Invalid configuration fails startup rather
than degrading at runtime.

Three safety guards are enforced in `libs/config/settings.py` and covered by
`tests/security/`:

- Only `DEVELOPMENT` and `TESTNET` execution environments pass validation.
  Anything beyond them is refused — real capital is prohibited and mainnet
  execution is hard-blocked at this build stage.
- The venue endpoint is **derived** from the environment, never configured, so
  changing a URL cannot enable real-money trading.
- A signing credential in a development environment, or a malformed one
  anywhere, refuses startup.

`STW_TRADING_ENABLED` defaults to `false` — Kill Switch 0.1 — and the tradable
asset allowlist defaults to BTC only.

## Status

| Area | State |
|------|-------|
| Specifications, phases 1–10 | Approved, in this repository |
| Implementation program | Build 0.1 Rev.2 approved; Rev.1 superseded, retained |
| Research candidates | TBIE v1.1 accepted as experimental feature family; predictive information supported, executable alpha unproven; no production authority |
| Implementation code | **M0 Rev.2, M1, M2 implemented** — foundation and safety configuration; storage, migrations, verification; BTC recorder with parsing, normalization, quality, dedup and gap detection. M1 and M2 await verification against a live stack and the live venue |
| Production | **Not approved.** Architecture approval is not production approval (Phase 10 §114) |
| Provider contracts, coverage, licensing, pricing | Unverified — required before procurement (Phase 3 §36) |
| Venue validation, security audit, penetration test, legal review | Outstanding (Phases 9, 10) |

No model training begins before the Historical Data Engine can guarantee dataset
lineage and point-in-time integrity. No real capital is introduced before the
Phase 6 and Phase 7 acceptance gates pass on implemented systems.
