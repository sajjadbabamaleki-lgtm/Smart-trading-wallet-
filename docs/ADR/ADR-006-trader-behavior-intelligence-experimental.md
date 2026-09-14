# ADR-006 — Trader behaviour intelligence as an experimental feature family

**Status:** Accepted · **Date:** 2026-09-14 · **Build:** 0.1 (M0 Rev.2)

Requested by TBIE v1.0 §50 and §66; number resolved per TBIE v1.1 §73.

## Context

Hyperliquid exposes persistent pseudonymous wallet identity, so it is possible
to ask whether *who* trades carries information beyond anonymous market data.
TBIE v1.1's evidence audit finds the underlying research well supported: wallet
informativeness persists across adjacent ten-day windows (ρ = 0.52), and adding
top-ranked wallet activity to an anonymous microstructure benchmark raises
one-second out-of-sample R² from 10.88% to 12.31%, against 200 activity-matched
placebo cohorts. BTC is the largest market in that sample.

The audit is equally clear about what is *not* established: executable
profitability, receipt-to-fill viability, and profitable copy trading are all
unverified, and the study itself places an execution model out of scope
(TBIE v1.1 §19, §36).

## Decision

Trader behaviour is accepted as a **high-priority experimental feature family**
with **no production authority**. Concretely, at M0:

1. **Research status registered** — `docs/research/`, documents stored with
   their status, v1.0 retained as superseded.
2. **Schemas preserve identity-linked fields** — `libs/schemas/trader_event.py`
   carries `wallet`, `counterparty`, `order_id`, `client_order_id`, `twap_id`,
   `start_position`, `end_position`, all optional. A source that does not supply
   a field leaves it empty rather than having a value invented.
3. **Clock architecture supports latency measurement** — see ADR-007.
4. **No production dependency.** Nothing in `services/` imports a TBIE concept,
   and TBIE is not on the Build 0.1 critical path (TBIE v1.1 §57).

What this decision *is*: preserving optionality. Bounded API history — 2,000
fills per response, only the 10,000 most recent — and an archive that uploads
roughly monthly with no completeness guarantee mean identity-linked information
discarded today may be unreconstructable later (TBIE v1.1 §32–33, §56).
Recording a nullable column is nearly free; recreating lost history is not
possible at any price.

What it is **not**: an endorsement. The engine, the scoring, the cohorts and the
consensus weighting are all unbuilt, and Gate 0 (latency viability) precedes
them all.

## Alternatives rejected

**Build TBIE now.** The evidence is genuinely interesting and this is the
project's clearest potential differentiator. Rejected: the signal decays fast
(+18.7% relative gain at 200 ms falling to +3.0% at 30 s), the cited study
indexes time by venue consensus timestamps rather than an audited local receipt
clock, and therefore nothing in it shows our own observe-to-fill path completes
in time (TBIE v1.1 §17–18). Building the engine before measuring that is
building on an untested premise — and it would derail the Lean BTC MVP, which
Rev.2 §57 explicitly forbids.

**Ignore trader identity in M2 and add it later.** Rejected: this is the one
irreversible choice in the set. Everything else about TBIE can be deferred at no
cost; the data cannot.

**Run a Level-4 node now to capture everything.** Rejected on economics:
Hyperliquid's own documentation puts default node operation at ≈100 GB of logs
per day — roughly 36.5 TB/year uncompressed before replication or derived
datasets. The node is a formal economic gate (TBIE v1.1 §58–59), not a default.

## Consequences

- `TraderEvent` exists with no consumer, which is intentional and recorded here
  so it is not mistaken for dead code.
- Four outcomes are possible, not two: `TBIE_ALPHA_VALIDATED`,
  `TBIE_RISK_ONLY`, `TBIE_RESEARCH_ONLY`, `TBIE_NO_EDGE`. A feature can fail as
  alpha and still succeed as adverse-selection or execution-risk intelligence
  (TBIE v1.1 §45–46).
- The kill rule binds: if point-in-time-correct experiments repeatedly show the
  information does not survive realistic execution, cannot survive costs,
  depends on a few wallets, or fails outside the original period, alpha
  development stops. No founder override, and no model-complexity rescue without
  a new falsifiable hypothesis (TBIE v1.1 §78).

## Revisit when

M2 and M3 pass — recorder, integrity and replay — which is the trigger for
TBIE Experiment 0, latency viability (TBIE v1.1 §77).
