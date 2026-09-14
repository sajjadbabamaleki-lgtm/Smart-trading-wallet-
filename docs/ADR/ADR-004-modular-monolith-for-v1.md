# ADR-004 — Modular monolith for V1, no Kubernetes

**Status:** Accepted · **Date:** 2026-09-14 · **Build:** 0.1 (M0 Rev.2)

## Context

The architecture defines service boundaries that must hold — the Risk Engine is
an independent authority over execution (Phase 6 §2), and the Risk Engine must
keep working when the AI service dies (Phase 6 §83). It is tempting to read
"independent" as "separately deployed".

Build 0.1 Rev.1 §3 and §10–11 and Rev.2 §11 say otherwise for V1: one monorepo,
Docker Compose, no Kubernetes, no premature microservices.

## Decision

One repository, one deployable, with enforced internal boundaries:

```
apps/          product interface (deferred to Build 0.6)
services/      market_data, feature_engine, strategy_engine,
               risk_engine, execution_engine, portfolio_engine
libs/          schemas, domain, exchange, config, observability, security
research/      notebooks, experiments, backtests, datasets
infrastructure/ docker, database, monitoring, scripts
tests/         unit, integration, replay, failure, security
```

Local infrastructure runs under Docker Compose: PostgreSQL, ClickHouse, Redis
and MinIO.

Boundaries are maintained in code rather than by network topology: services
depend on `libs`, never on each other's internals, and communicate through the
typed contracts in `libs/`. Crucially, the authority boundary is structural
already — an order cannot be constructed without an `intent_id`, so "the AI
cannot execute directly" holds in a single process.

## Alternatives rejected

**Microservices from the start.** Genuine process isolation for the Risk Engine,
matching the eventual architecture. Rejected: Rev.1 §11 lists the cost —
deployment, networking, security, observability and operational overhead — with
no corresponding need proven. Infrastructure complexity earns its place like any
other complexity.

**Kubernetes.** Same reasoning, more so. Build 0.1 has one developer and no
production traffic.

**No boundaries at all.** Fastest to write, and rejected: the directory
structure is what makes later extraction possible without rewriting the layers
above.

## Consequences

- A crash takes down everything, so Phase 6 §83's independence requirement is
  **not yet satisfied** — it is a Build 0.4 obligation, recorded here so it is
  not mistaken for done.
- Extraction later requires the boundaries to have been respected; a shortcut
  across them now is a debt paid with a rewrite.

## Revisit when

Build 0.4 implements complete risk and execution, where the Risk Engine's
survival independent of other components becomes a stated acceptance criterion.
