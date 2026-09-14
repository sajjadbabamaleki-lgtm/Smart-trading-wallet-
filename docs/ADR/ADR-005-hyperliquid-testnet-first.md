# ADR-005 — Hyperliquid testnet as the first execution integration

**Status:** Accepted · **Date:** 2026-09-14 · **Build:** 0.1 (M0 Rev.2)

## Context

Build 0.1 Rev.2 names Hyperliquid as the execution venue and BTC perpetual
futures as the instrument, with execution confined to testnet, capital
simulated, and mainnet hard-blocked.

Two reasons to integrate the intended venue first rather than a convenient one:
the point is to learn the environment where fills would actually occur
(Rev.1 §23), and Hyperliquid is unusual in exposing persistent pseudonymous
wallet identity, which is what makes the TBIE question askable at all.

## Decision

Hyperliquid testnet is the first and only execution integration in Build 0.1,
behind the `ExchangeAdapter` contract (`libs/exchange/adapter.py`).

Three structural controls:

1. The endpoint is derived from `execution_environment`, never configured, so
   changing a URL cannot enable real-money trading (Rev.1 §46).
2. Only `DEVELOPMENT` and `TESTNET` pass configuration validation.
3. A dedicated testnet API wallet, never reused for production (Rev.1 §45).

`HyperliquidAdapter` will use official APIs and SDK rather than reimplementing
cryptographic signing without a demonstrated need (Rev.1 §44).

## Alternatives rejected

**Binance first.** Deeper liquidity, better historical archives, and the
aggregate price-discovery leader for BTC perpetuals (TBIE v1.1 §24). Rejected as
*first*: it exposes no persistent counterparty identity, so the research
question that differentiates this project cannot be asked there. Binance
history remains valuable as a cross-validation source (Phase 3 §36).

**A multi-venue abstraction validated across two venues immediately.**
Rejected: a single-venue MVP is acceptable for experimental validation provided
it does not become a single-venue *architecture* (Rev.2 §13), which the adapter
contract secures at far lower cost.

## Consequences

- Single-venue concentration is an accepted, recorded risk for Build 0.1.
- Testnet validates plumbing, never alpha: its liquidity, participants, depth
  and fill probability differ materially from production (Phase 7 §6).
- Venue-specific behaviour must stay behind the adapter; a Hyperliquid concept
  leaking into the Risk or Strategy layers is a defect.

## Revisit when

Gate 0 or the Phase 7 validation ladder shows venue characteristics materially
limiting the strategy, or a second venue becomes necessary for redundancy.
