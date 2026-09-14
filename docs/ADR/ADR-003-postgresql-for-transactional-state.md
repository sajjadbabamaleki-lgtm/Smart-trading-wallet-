# ADR-003 — PostgreSQL for transactional state, separate from analytics

**Status:** Accepted · **Date:** 2026-09-14 · **Build:** 0.1 (M0 Rev.2)

## Context

Execution intents, risk decisions, orders, positions, configuration versions and
audit records need transactional guarantees: a partially written order record or
a lost risk decision is a capital-safety failure, not a data-quality nuisance.
Phase 2 §10 and Build 0.1 Rev.1 §12 assign this to PostgreSQL, explicitly not as
the raw tick warehouse.

## Decision

PostgreSQL holds transactional and application state: users, wallet mappings,
trading accounts, strategy and model registries, risk configurations, execution
intents, orders, positions, incidents and configuration versions.

The source-of-truth hierarchy (Build 0.1 Rev.1 §16) is binding: the **venue** is
authoritative for actual exposure, PostgreSQL for our record of it, the raw
archive plus ClickHouse for market history, Redis for ephemeral cache only.
No single store is authoritative for everything.

Application roles receive least privilege — the trading service does not get
database-administrator rights (Phase 10 §59).

## Alternatives rejected

**One database for everything.** Simpler to operate, and rejected in both
directions: PostgreSQL alone cannot carry the analytical volume (ADR-002), and
ClickHouse alone cannot give transactional guarantees to capital-critical state.

**Redis as primary state.** Rejected by Rev.1 §15: Redis must never become the
authoritative source of capital state. Durability guarantees are unsuitable for
a record that must survive a crash intact.

## Consequences

- Migrations become part of the build (M1), with schema changes reviewed.
- Reconciliation logic must treat venue state as authoritative and our own
  records as a claim to be checked (Phase 6 §45).

## Revisit when

Transactional volume outgrows a single primary, which would be a scaling
problem well beyond Build 0.1.
