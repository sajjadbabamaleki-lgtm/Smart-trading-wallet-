# Specification Library

Phase specifications for the Smart Trading Wallet platform. Each document is the
approved architecture record for its phase and is stored verbatim as delivered.

| Phase | Document | Status | Core subject |
|-------|----------|--------|--------------|
| 1 | [Master Product & Risk Specification](phase-1-master-product-and-risk-specification.md) | Approved Foundation Specification | Product definition, operating modes, risk constitution, validation pipeline |
| 2 | [Data Research & Architecture](phase-2-data-research-and-architecture.md) | Architecture Defined — Data Source Selection Pending | Intelligence layers, Bronze/Silver/Gold storage, point-in-time correctness |
| 3 | [Historical Data Engine](phase-3-historical-data-engine.md) | Approved for Implementation Design | Historical domains, PIT classification, gap registry, continuous recorder |
| 4 | [Research & Backtesting Laboratory](phase-4-research-and-backtesting-laboratory.md) | Approved as Research Architecture | Hypothesis/experiment registries, cost & execution simulation, PBO/DSR, promotion gates |
| 5 | [Strategy Intelligence & AI/ML Architecture](phase-5-strategy-intelligence-and-ai-ml-architecture.md) | Approved as AI/ML Research Architecture | Regime engine, strategy families, meta-labeling, calibration, uncertainty, model registry |

## Pending phases

Phase 5 names **Phase 6 — Risk Engine & Execution Architecture** as the next
deliverable. Phases 6–10 are not yet part of this repository.

## Cross-cutting invariants

These constraints are stated across multiple phase documents and govern any
implementation work in this repository:

1. **Risk Engine > AI.** The AI/Strategy Engine has no authority to execute
   trades. Every proposed transaction passes through the independent Risk Engine
   before reaching the Execution Engine (Phase 1 §6, §8; Phase 5 §54).
2. **Capital preservation > trading frequency.** `NO TRADE` is a first-class,
   potentially optimal output; trading frequency is never an optimisation
   objective (Phase 1 §12, §15; Phase 5 §48).
3. **Point-in-time correctness.** At decision time `T`, only information genuinely
   available at or before `T` may be used, in research and in production alike
   (Phase 2 §12; Phase 3 §7, §31; Phase 4 §9, §10; Phase 5 §23).
4. **Live evidence > backtest performance.** No strategy or model reaches
   production capital on historical backtest results alone; it must clear every
   validation gate in sequence (Phase 1 §14, §15; Phase 4 §57; Phase 5 §62).
5. **Data quality gates trading.** Stale, inconsistent, or unavailable critical
   data must be able to force `NO TRADE` or `SAFE MODE` (Phase 2 §3.5, §11;
   Phase 5 §44).
6. **Reproducibility.** Every dataset, feature set, experiment, and model carries
   a version and lineage; no anonymous model enters production (Phase 2 §13, §14;
   Phase 3 §18; Phase 4 §43; Phase 5 §36).
7. **Complexity must earn its place.** Simpler strategies and models win on equal
   validated evidence; every data family and feature must justify itself through
   ablation (Phase 3 §26; Phase 4 §34, §35; Phase 5 §69).
