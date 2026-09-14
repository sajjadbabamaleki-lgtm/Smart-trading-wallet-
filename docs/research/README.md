# Research Candidates

Component-level research and architecture specifications. These are **not**
approved production signals and **not** part of the Build 0.1 critical path.
Each carries its own promotion gate and its own valid negative outcome.

Documents are stored verbatim as delivered; status is carried by this index.

| Component | Status | Production authority | Build 0.1 critical path |
|-----------|--------|----------------------|-------------------------|
| [Trader Behavior Intelligence Engine (TBIE)](trader-behavior-intelligence-engine.md) | Research Candidate — High Priority | None | No — but it does affect recorder design |

## TBIE in one paragraph

Hyperliquid exposes persistent pseudonymous wallet identities, so it is possible
to ask whether *who* trades carries information beyond price, order book,
derivatives and anonymous order flow. TBIE would estimate the point-in-time,
context-dependent, time-varying informational quality of wallets and cohorts, and
emit that as research features. It is explicitly **not** copy trading: observed
trader behaviour is evidence, never an instruction, and TBIE holds no execution,
leverage, sizing, stop, risk-limit or kill-switch authority (§3, §62).

## What this changes today

Nothing on the critical path. The immediate sequence stays
M0 Rev.2 → M1 → M2 → M3 → BTC research dataset → baseline research, with the
trader-behaviour experiment after it (§66).

Two concrete effects:

1. **Recorder design (§51).** M2 stays the BTC market recorder, but must not
   discard trader-identity-linked event information that would later be expensive
   or impossible to reconstruct. Two raw streams — market events and trader
   events — sharing one time model. This is a *preservation* decision, not a
   requirement to implement TBIE during M2.
2. **An ADR (§50, §66).** Build 0.1 Rev.2 should record trader behaviour as an
   experimental feature family: architectural support preserved, status
   experimental, production authority none, validation requirement = point-in-time
   ablation against an anonymous baseline.

   *Open item:* the document asks for this as **ADR-004**, while Rev.1 §4 sketches
   ADR-004 as "why V1 begins as a modular monolith". Rev.1 presents its numbers as
   examples rather than an assigned registry, so the number needs settling once
   when `docs/ADR/` is created during M0.

## Why it is worth testing

The document cites 2026 empirical work on Hyperliquid as grounds for testing —
not as proof of profitability:

- wallet informativeness persisting across adjacent ten-day windows (rank
  correlation ≈ 0.52), and top-ranked wallet activity raising out-of-sample
  one-second return R² to ≈ 12.31%, a reported ≈ 13.2% improvement over an
  anonymous benchmark, checked against 200 activity-matched placebo cohorts (§5.1)
- Binance leading Hyperliquid at venue level while a minority of Hyperliquid
  wallets still showed persistent anticipatory behaviour — so venue-level and
  trader-level information leadership are different phenomena (§6)
- feasibility of reconstructing Level-4-style data from a non-validating node,
  including rejected orders and failed cancellations (§7)

**These citations are unverified in this repository.** They carry the whole
rationale, so confirming the papers, their numbers, and their methodology is
prerequisite work before any infrastructure spend — particularly before the
node-ingestion stages (§48 Stage 4–5, §49).

## The two risks that decide this

The document rates leakage risk and latency sensitivity **VERY HIGH** (§64), and
both are existential rather than incidental:

1. **Leakage (§18, §19, §45).** Ranking wallets with hindsight and backtesting
   the past with that ranking would manufacture an edge from nothing. Only
   point-in-time skill estimation, the historically observable population
   (no leaderboard survivorship), and placebo/future-leaked comparisons keep the
   experiment honest.
2. **Latency (§23, §42).** The cited evidence is strongest at one-second
   horizons. The question is never "did the trader predict the market" but
   "was the information still actionable after our observation, computation,
   transmission and execution latency". A signal that is real and unreachable is
   worth nothing.

Then capacity, crowding, reflexivity and concentration (§24, §25, §47): if the
edge vanishes when the single top wallet is removed, there is no edge.

## Outcome

`TBIE_NO_EDGE` is a valid result (§60). If trader identity fails incremental
ablation against the anonymous baseline, the component is archived or kept
research-only, and the trading architecture works without it. No narrative,
leaderboard, reputation, founder preference or AI complexity may override that
(§65).
