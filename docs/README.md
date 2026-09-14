# Specification Library

The complete V1 architecture program for the Smart Trading Wallet platform: ten
phase specifications, each the approved architecture record for its phase,
stored verbatim as delivered.

The architecture program is complete. Phase 10 closes it with
**ARCHITECTURE APPROVED / PRODUCTION NOT YET APPROVED**, and names the next
program **Implementation Program — Build 0.1**, which lives in
[`docs/build/`](build/README.md).

| Phase | Document | Status | Core subject |
|-------|----------|--------|--------------|
| 1 | [Master Product & Risk Specification](phase-1-master-product-and-risk-specification.md) | Approved Foundation Specification | Product definition, operating modes, risk constitution, validation pipeline |
| 2 | [Data Research & Architecture](phase-2-data-research-and-architecture.md) | Architecture Defined — Data Source Selection Pending | Intelligence layers, Bronze/Silver/Gold storage, point-in-time correctness |
| 3 | [Historical Data Engine](phase-3-historical-data-engine.md) | Approved for Implementation Design | Historical domains, PIT classification, gap registry, continuous recorder |
| 4 | [Research & Backtesting Laboratory](phase-4-research-and-backtesting-laboratory.md) | Approved as Research Architecture | Hypothesis/experiment registries, cost & execution simulation, PBO/DSR, promotion gates |
| 5 | [Strategy Intelligence & AI/ML Architecture](phase-5-strategy-intelligence-and-ai-ml-architecture.md) | Approved as AI/ML Research Architecture | Regime engine, strategy families, meta-labeling, calibration, uncertainty, model registry |
| 6 | [Risk Engine & Execution Architecture](phase-6-risk-engine-and-execution-architecture.md) | Approved as Risk & Execution Architecture | Risk layers, position sizing, leverage & liquidation safety, execution intents, kill switch, reconciliation |
| 7 | [Testnet, Paper Trading & Shadow Validation](phase-7-testnet-paper-trading-and-shadow-validation.md) | Approved as Pre-Capital Validation Architecture | Testnet execution matrix, paper engine, shadow trading, drift & calibration monitors, backtest-to-live gap |
| 8 | [Limited-Capital Live Trading & Production Qualification](phase-8-limited-capital-live-trading-and-production-qualification.md) | Approved as Limited-Capital Live Validation Architecture | Shadow Twin, execution reality gap, real fee/funding/slippage truth, capital ladder, qualification gate |
| 9 | [Product Interface, Wallet Integration & Human Control Layer](phase-9-product-interface-wallet-integration-and-human-control-layer.md) | Approved as Product & Wallet Architecture | Three-layer account model, wallet adapter, authentication vs authorization, explanation panels, emergency controls |
| 10 | [Security Architecture, Independent Audit & Production Launch Gate](phase-10-security-architecture-independent-audit-and-production-launch-gate.md) | Architecture Approved — Production Not Approved | Crown jewels, trust boundaries, credential isolation, supply chain, audit & penetration testing, launch gate |

## Cross-cutting invariants

These constraints are stated across multiple phase documents and govern any
implementation work in this repository. Where documents disagree in wording, the
phase that owns the subject is normative.

### Authority

1. **Risk Engine > AI.** The AI/Strategy Engine has no authority to execute
   trades. Every proposed transaction passes through the independent Risk Engine,
   which may approve, reduce, or reject it, and whose decision the AI cannot
   reverse (Phase 1 §6, §8; Phase 5 §54; Phase 6 §2, §31).
2. **Execution requires a valid Risk intent.** The Execution Engine acts only on
   an immutable, expiring, single-use execution intent issued by the Risk Engine,
   and independently re-validates it; a consumed or expired intent cannot open a
   position (Phase 6 §32, §33; Phase 10 §22–24).
3. **Hard ceilings sit outside AI and UI reach.** Maximum leverage, portfolio
   risk, daily loss, and kill-switch authority cannot be changed by the AI, the
   frontend, or a user setting — user limits may only narrow them
   (Phase 6 §79; Phase 9 §74; Phase 10 §21).
4. **Backend is the source of truth.** The frontend is not an authorization
   boundary and never infers critical state locally (Phase 9 §103, §118;
   Phase 10 §17, §28).

### Capital safety

5. **Capital preservation > trading frequency.** `NO TRADE` is a first-class,
   potentially optimal output; trading frequency is never an optimisation
   objective (Phase 1 §12, §15; Phase 5 §48; Phase 9 §80).
6. **Every position has defined downside.** No position opens without entry,
   size, stop, exit logic, and a maximum permitted loss — and a stop price is
   never assumed to be the maximum loss (Phase 1 §9; Phase 6 §3, §12;
   Phase 8 §27).
7. **Unknown is dangerous.** When critical state is unknown — position, order
   status, feed health, margin — the response is no new risk, not continuation
   (Phase 6 §82; Phase 8 §54; Phase 10 §69).
8. **Exchange state is authoritative.** Internal state reconciles against the
   venue continuously; unexplained mismatch is a critical event
   (Phase 6 §45, §46; Phase 7 §9; Phase 8 §53).
9. **Data quality gates trading.** Stale, inconsistent, or unavailable critical
   data must be able to force `NO TRADE` or `SAFE MODE` (Phase 2 §3.5, §11;
   Phase 5 §44; Phase 10 §78).

### Evidence

10. **Point-in-time correctness.** At decision time `T`, only information
    genuinely available at or before `T` may be used, in research and in
    production alike (Phase 2 §12; Phase 3 §7, §31; Phase 4 §9, §10;
    Phase 5 §23).
11. **Live evidence > backtest performance.** No strategy or model reaches
    production capital on historical results alone; it clears every validation
    gate in sequence, and no phase is bypassed under launch pressure
    (Phase 1 §14, §15; Phase 4 §57; Phase 7 §56; Phase 10 §101).
12. **Frozen versions during forward validation.** Model, strategy, feature,
    risk, and execution versions freeze before a formal validation run; a
    material change creates a new version and restarts the cycle rather than
    continuing the same period (Phase 7 §42, §43; Phase 8 §10, §47).
13. **Qualification belongs to a configuration, not the application.** The unit
    that earns or loses production status is
    Strategy × Asset × Model × Risk configuration × Execution policy, and status
    is never inherited by a new asset or a new model version
    (Phase 8 §37–39, §94).
14. **Capital follows evidence.** Capital and leverage rise only on statistical,
    execution, and reliability evidence under governed approval — never on recent
    P&L, confidence, or excitement — and the AI may never scale its own
    allocation (Phase 5 §54; Phase 8 §9, §77, §99).
15. **Reproducibility.** Every dataset, feature set, experiment, and model
    carries a version and lineage; no anonymous model enters production, and
    failed experiments stay recorded (Phase 2 §13, §14; Phase 3 §18;
    Phase 4 §5, §43; Phase 5 §36; Phase 10 §76).
16. **Complexity must earn its place.** Simpler strategies and models win on
    equal validated evidence; every data family and feature justifies itself
    through ablation (Phase 3 §26; Phase 4 §34, §35; Phase 5 §69).

### Security and honesty

17. **Assume compromise.** A compromised AI service, frontend, research
    environment, or credential must not become compromised capital; blast radius
    is bounded by design (Phase 10 §2, §27–29).
18. **Primary wallet keys never reach the backend.** Seed phrases and private
    keys stay in the user's wallet environment; automation signs through an
    isolated, rotatable execution credential (Phase 1 §5; Phase 6 §63;
    Phase 9 §4; Phase 10 §6, §7).
19. **Capital security outranks availability and profit.** A system temporarily
    unable to trade is preferable to one trading with unknown authorization
    integrity, and business urgency cannot override a failed critical security
    gate (Phase 10 §104, §109, §110).
20. **Honest uncertainty.** Confidence is presented only as calibration
    supports, never as a guarantee and never mapped to leverage; historical
    decision records are immutable and confidence is never recomputed after the
    outcome (Phase 1 §7; Phase 5 §26; Phase 9 §35, §36, §82–84).

## Build order

Phase 1 §18 fixes the priority, from the trading intelligence outward:

```
Data Quality → Research Infrastructure → Strategy Intelligence → Risk Management
→ Execution Reliability → Live Validation → User Experience → Native Wallet Expansion
```

Phase 10 §116 names the successor program and its opening sequence:

```
IMPLEMENTATION PROGRAM — BUILD 0.1

Foundation Infrastructure
  → Historical Data Recorder
  → Research Environment
  → Backtesting Engine
  → Risk & Execution Skeleton
  → Testnet Integration
```

That program lives in [`docs/build/`](build/README.md). The active plan is
**Build 0.1 Rev.2 — Lean BTC Quant MVP**, which narrows the first implementation
to BTC only without changing the architecture defined here.

Interface quality is explicitly not a substitute for validated trading
performance, and the architecture phase is closed — the next program is not
"Phase 11".
