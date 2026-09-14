# Smart Trading Wallet

An AI-powered automated trading platform for **BTC, ETH, SOL and BNB**, trading
perpetual futures with an independent risk-control authority over every position.

This repository currently holds the approved architecture specifications. No
trading, data, or model code has been implemented yet.

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

Wallet connectivity starts with **Phantom** and **Trust Wallet**. The user's seed
phrase or private key is never transmitted to or stored by backend
infrastructure, and wallet connectivity stays logically separate from the trading
core so a native non-custodial wallet can be added later without redesigning it.

## Decision pipeline

```
Market Data
  → Historical Intelligence Engine
  → Market Regime Detection
  → Strategy / AI Engine
  → Trading Signal
  → Risk Engine
  → Execution Engine
  → Trading Venue
```

The architectural rule behind that ordering: **the AI/Strategy Engine never has
direct authority to execute trades.** The Risk Engine decides whether capital may
be exposed, and neither a model nor a strategy may override system-level risk
limits.

## Specifications

See [`docs/`](docs/README.md) for the full library and the cross-cutting
invariants that govern implementation work.

| Phase | Document |
|-------|----------|
| 1 | [Master Product & Risk Specification](docs/phase-1-master-product-and-risk-specification.md) |
| 2 | [Data Research & Architecture](docs/phase-2-data-research-and-architecture.md) |
| 3 | [Historical Data Engine](docs/phase-3-historical-data-engine.md) |
| 4 | [Research & Backtesting Laboratory](docs/phase-4-research-and-backtesting-laboratory.md) |
| 5 | [Strategy Intelligence & AI/ML Architecture](docs/phase-5-strategy-intelligence-and-ai-ml-architecture.md) |

Phases 6–10 are pending; Phase 6 is **Risk Engine & Execution Architecture**.

## Development order

Phase 1 §18 fixes the build priority, from the trading intelligence outward:

```
Data Quality → Research Infrastructure → Strategy Intelligence → Risk Management
→ Execution Reliability → Live Validation → User Experience → Native Wallet Expansion
```

Interface quality is explicitly not a substitute for validated trading
performance.

## Status

| Area | State |
|------|-------|
| Specifications, phases 1–5 | Approved, in this repository |
| Specifications, phases 6–10 | Not yet written |
| Data, research, strategy, risk, execution code | Not started |
| Provider contracts, coverage, licensing, pricing | Unverified — required before procurement (Phase 3) |

No model training begins before the Historical Data Engine can guarantee dataset
lineage and point-in-time integrity.
