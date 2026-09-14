# ADR-002 — ClickHouse for high-frequency historical data

**Status:** Accepted · **Date:** 2026-09-14 · **Build:** 0.1 (M0 Rev.2)

## Context

Two workloads with incompatible shapes: transactional application state
(small, frequently updated, correctness-critical) and analytical market history
(billions of append-only rows, scanned by column over time ranges).

Phase 2 §10 and Build 0.1 Rev.1 §13 assign the analytical workload to
ClickHouse. The scale is not hypothetical — TBIE v1.1 §4 cites 17.1 billion
Level-4 messages in one month across ten markets, of which ≈9.75 billion are
BTC alone.

## Decision

ClickHouse holds append-only analytical event data: trades, order-book events,
quotes, funding, open interest, market context, and later feature, prediction
and execution history.

## Alternatives rejected

**PostgreSQL with TimescaleDB.** One fewer system to operate. Rejected on
scale: row-oriented storage and index maintenance make billion-row columnar
scans far more expensive, and the recorder's write path would compete with
transactional traffic.

**Parquet files only.** Effectively free and excellent for archival — and
retained for exactly that in object storage (ADR pending for M1). Rejected as
the query layer: ad-hoc research queries over long ranges need an engine with
indexes and a query planner.

**DuckDB.** Strong for single-node research and may still be used inside the
research layer. Rejected as the shared store: the recorder needs concurrent
ingestion from a long-running process.

## Consequences

- Two stores must be kept consistent in meaning, which is why the source-of-
  truth hierarchy is written down (Build 0.1 Rev.1 §16).
- ClickHouse's eventual-consistency and deduplication semantics are not
  transactional; nothing capital-critical may depend on them.
- Storage growth is a first-class cost, feeding the node economic gate
  (TBIE v1.1 §58–59).

## Revisit when

M1 benchmarks show ingestion or query performance failing to meet the
recorder's needs, or the retained volume makes the cost disproportionate.
