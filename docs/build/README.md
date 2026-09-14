# Implementation Program

The architecture program (Phases 1–10) is closed. This directory holds the
implementation program that succeeds it — Phase 10 §116 states explicitly that
the next program is not "Phase 11".

Documents are stored verbatim as delivered; status is carried by the filename and
this index.

| Document | Revision | Status |
|----------|----------|--------|
| [Build 0.1 Rev.2 — Lean BTC Quant MVP](build-0.1-rev2-lean-btc-quant-mvp.md) | Rev.2 | **Approved for Implementation** — the active plan |
| [Implementation Program — Build 0.1](build-0.1-rev1-implementation-program-superseded.md) | Rev.1 | Superseded by Rev.2, retained for historical traceability (Rev.2 §42) |

## What Rev.2 changed

Rev.2 narrows implementation scope **without changing the Phases 1–10
architecture**. The long-term design still supports BTC, ETH, SOL and BNB; the
first experimental pipeline does not.

| | Rev.1 | Rev.2 |
|---|-------|-------|
| Experimental asset | BTC / ETH / SOL / BNB | **BTC only** (§5) |
| Recorder subscriptions | all four assets (Rev.1 §25) | BTC (§19) |
| On-chain intelligence | in scope | deferred, off the critical path (§7) |
| Commercial data (Glassnode, CryptoQuant, Kaiko, Coin Metrics) | evaluated | deferred; no subscription required (§8) |
| AI/ML | deferred within Build 0.1 | removed from the critical path entirely — forward validation may run on a simple baseline (§14, §34) |
| Risk & Execution | M7–M8 | moved earlier; the capital-control boundary exists before AI (§17, §18) |
| Research horizon / strategy | unspecified | one horizon, one strategy family, chosen from observed BTC cost and execution behaviour (§15, §16) |

Both revisions keep real capital **prohibited** and mainnet execution
**hard-blocked**, and neither treats profitability as an acceptance criterion.

## Rev.2 implementation path

```
M0 Rev.2 Foundation → M1 Storage Foundation → M2 BTC Hyperliquid Live Recorder
→ M3 Data Integrity & Replay → M4 BTC Research Dataset → M5 Baseline Strategy Research
→ M6 Event-Driven Backtesting → M7 Risk & Execution Skeleton → M8 Hyperliquid Testnet
→ M9 Paper Trading → M10 Shadow Trading
→ ML research, only if justified → Limited Live, only after all gates pass
```

Immediate engineering target: **M0 Rev.2 → M1 → M2** (§41). Rev.1 §76 remains the
fuller milestone breakdown for the foundation work those milestones cover, and
Rev.1 §§45–78 still hold for detail Rev.2 does not restate (execution state
machine, audit events, correlation IDs, replay clock, evidence pack, CI and
branch protection, the Build 0.1 hard gate, and the Build 0.2–1.0 sequence).

## New rules these documents add

Beyond the twenty invariants in the [specification library](../README.md), the
implementation program introduces:

1. **`NO_EDGE_FOUND` is a valid project outcome.** If no strategy demonstrates
   durable positive expected value under the tested hypotheses, datasets, costs
   and validation methodology, that is a scientific result — not a failure to be
   engineered around by lowering standards, hiding costs, searching until a
   profitable backtest appears, raising leverage, cherry-picking periods, or
   substituting AI complexity for evidence. It triggers a formal decision tree
   that may legitimately end in `STOP TRADING RESEARCH`
   (Rev.2 §§30–32).
2. **No founder override, extended.** No founder, engineer, model or business
   objective may convert `NO_EDGE_FOUND` into "deploy anyway" (Rev.2 §33,
   carrying Phase 10 §104 forward).
3. **Speed to reliable evidence, not speed to feature completion** (Rev.2 §2).
   A feature without evidence is not complete (Rev.1 §2).
4. **Start the recorder early, as a formal engineering priority.** Historical
   datasets can be bought later; live microstructure that goes unrecorded today
   may be impossible to reconstruct tomorrow (Rev.2 §9).
5. **Expansion is evidence-driven, one dimension at a time.** A second asset, a
   model layer, a validation stage, or more capital — never several at once, or
   causal attribution is lost (Rev.2 §6, §36).
6. **Venue abstraction from day one.** Hyperliquid lives behind an
   `ExchangeAdapter`; a single-venue MVP must not become a single-venue
   architecture (Rev.2 §§12–13; Rev.1 §§43–44).
7. **Mainnet is structurally blocked, fail-closed.** Changing one URL must not be
   able to enable real-money trading, and a production credential detected in a
   development environment fails startup (Rev.2 §42; Rev.1 §46, §70).
8. **No direct orders, even on testnet.** Orders flow test scenario → execution
   intent → execution engine → exchange adapter, so the correct architecture is
   established before it carries capital (Rev.1 §48).
9. **Regulatory work is an independent track.** It does not block private
   testnet/paper research, and becomes mandatory before public launch, user
   offering, marketing, monetisation, builder fees, or jurisdiction expansion —
   technical readiness is not legal readiness (Rev.2 §37).
10. **Builder-fee monetisation stays disabled during research**, and if
    introduced may never reward the system for increasing trading volume
    (Rev.2 §38).

## Build 0.1 success definition

Rev.2 §39 — twelve provable statements about recording, preservation, quality,
gaps, reconnect, deterministic replay, dataset reproducibility, testnet
execution, non-bypassable risk controls, reconciliation, tested failure
scenarios, and auditability.

> Profitability is NOT a Build 0.1 acceptance criterion.

The first evidence milestone is a real BTC market event received from
Hyperliquid — preserved raw, timestamped, validated, normalised, persisted, and
deterministically reproducible.
