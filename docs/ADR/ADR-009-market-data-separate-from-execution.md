# ADR-009 — Market-data environment separate from execution environment

**Status:** Accepted · **Date:** 2026-09-14 · **Build:** 0.1 (M1/M2 acceptance)

## Context

One setting, `execution_environment`, governed both where orders could go and
where market data was read from. That conflation blocked the acceptance
verification of M2.

M2's open question is whether the recorder's assumptions match what Hyperliquid
actually sends — specifically whether trades carry `users`, which decides
whether trader-level research is possible at all (ADR-006), and what the real
source-to-receipt delay looks like, which is the input to TBIE's Gate 0. Only
mainnet has the activity to answer either. Testnet is thin enough that a
five-minute run could plausibly observe no trades and report nothing.

The single setting left two options, both bad. Read testnet data and learn
little about the real venue. Or widen the execution guard to reach mainnet data
and put real capital one configuration edit away — which is the specific failure
Build 0.1 Rev.1 §46 exists to prevent.

## Decision

Two independent settings.

`execution_environment`
    Unchanged. Only `DEVELOPMENT` and `TESTNET` pass validation; the endpoint is
    derived from it; a credential in development refuses startup. Nothing in
    this ADR relaxes any of it.

`market_data_environment`
    New. `DEVELOPMENT` | `TESTNET` | `MAINNET_PUBLIC`, defaulting to `TESTNET`,
    with its endpoint derived from `MARKET_DATA_ENDPOINTS` — a mapping consumed
    only by the recorder and never by the Execution Engine.

The safety property is that the two mappings are separate objects with separate
consumers, so a mainnet entry in one cannot become an execution path through the
other. `Settings.market_data_is_read_only` asserts it as a real conjunction over
the execution environment and order-submission state, not as a constant, so it
fails if the execution guard is ever widened. `tests/security/` proves that
mainnet market data leaves `venue_endpoint` as `None` and `may_submit_orders`
false, and that combining mainnet data with a production execution environment
is still refused.

## Alternatives rejected

**Keep one setting and verify against testnet.** Safest on paper, and rejected
because it would make the acceptance run inconclusive on exactly the questions
the run exists to answer. An inconclusive verification that looks complete is
worse than an honest gap.

**Keep one setting and add mainnet to the permitted execution set for the run.**
Rejected outright. It would widen the capital guard to obtain research data, and
the guard is the thing this architecture is built around (Phase 6 §2).

**A boolean such as `allow_mainnet_market_data`.** Rejected: a boolean says
nothing about what else is permitted, whereas an environment enumerates the
whole set of possibilities and forces every new value to have an explicit
endpoint decision — which a test asserts.

**Read mainnet data through a separate credential-free process.** Genuinely
stronger isolation, and deferred rather than rejected: it is the right shape
once the recorder is deployed rather than invoked, and it does not change what
this ADR settles.

## Consequences

- Market data can reach mainnet while execution cannot, which is what makes the
  M2 acceptance run meaningful.
- Two settings to reason about instead of one. The evidence report prints both,
  so an acceptance run states plainly which venue it read and that execution was
  disabled.
- `MAINNET_PUBLIC` names the constraint it carries. A future writable mainnet
  value would be a new member with its own endpoint decision, not a reuse of
  this one.

## Revisit when

The recorder becomes a deployed service rather than a CLI invocation, at which
point process-level isolation of the market-data reader is worth the
operational cost.
