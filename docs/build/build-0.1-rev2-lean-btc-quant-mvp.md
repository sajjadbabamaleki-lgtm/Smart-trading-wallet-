Build 0.1 Rev.2 — Lean BTC Quant MVP

Program: AI-Powered Automated Perpetual Futures Trading Platform
Revision: Build 0.1 Rev.2
Execution Venue: Hyperliquid
Experimental Asset: BTC
Real Capital: PROHIBITED
Mainnet Execution: HARD-BLOCKED
Status: Approved for Implementation

1. Revision Purpose

Build 0.1 Rev.2 narrows the implementation scope without changing the long-term architecture defined in Phases 1–10.

The objective is to reduce time-to-evidence, avoid premature infrastructure complexity, and determine as early as possible whether a genuine trading edge exists.

The architecture remains capable of supporting BTC, ETH, SOL and BNB.

However, the first experimental implementation will focus exclusively on:

BTC perpetual futures.

⸻

2. Core Principle

The project will optimize for:

Speed to Reliable Evidence

not:

Speed to Feature Completion.

The first objective is not to build the complete AI trading platform.

The first objective is to determine whether a small, correctly implemented trading system can demonstrate a reproducible net edge under realistic market conditions.

⸻

3. Experimental Scope

Build 0.1 Rev.2 includes:

Asset: BTC

Venue: Hyperliquid

Instrument: BTC perpetual futures

Initial Data: Hyperliquid market and execution-relevant data

Research Scope: One initial trading horizon

Strategy Scope: One initial strategy family

Execution: Testnet only

Capital: Simulated

ETH, SOL and BNB remain supported by the long-term architecture but are excluded from the initial experimental pipeline.

⸻

4. Deferred Scope

The following are deliberately deferred:

* ETH
* SOL
* BNB
* On-chain intelligence
* Glassnode
* CryptoQuant
* Kaiko
* Coin Metrics commercial datasets
* Deep learning
* Transformers
* Reinforcement learning
* Native wallet
* Production UI
* Multi-venue execution
* Real-money trading

These components may return only when evidence justifies their cost or complexity.

⸻

5. BTC-Only Decision

The first recorder, research dataset, strategy experiment, backtest and execution simulation will operate on BTC only.

This provides:

* Lower engineering complexity
* Faster debugging
* Cleaner attribution
* Lower data requirements
* Easier execution analysis
* Faster research iteration
* Clearer failure diagnosis

Asset expansion must be earned.

⸻

6. Asset Expansion Rule

ETH, SOL or BNB may enter the experimental pipeline only after the BTC pipeline demonstrates that:

1. Data collection is reliable.
2. Replay is deterministic.
3. Backtesting is trustworthy.
4. Execution simulation is credible.
5. Risk controls function correctly.
6. Research methodology works end-to-end.

Expansion is therefore evidence-driven rather than roadmap-driven.

⸻

7. On-Chain Intelligence Decision

On-chain intelligence is removed from the critical path.

It will not be included merely because blockchain data is available.

The future hypothesis will be:

Does on-chain information provide statistically and economically meaningful incremental predictive value after market, derivatives and execution information are already available?

Only ablation testing may justify its inclusion.

⸻

8. Commercial Data Providers

Build 0.1 Rev.2 does not require institutional data subscriptions.

Initial research should use:

* Hyperliquid data
* Hyperliquid historical resources where appropriate
* Public historical datasets where scientifically valid
* Our own live recorder

Commercial providers may later be evaluated individually.

Every paid dataset must answer:

What hypothesis becomes testable or materially better because this dataset exists?

⸻

9. Historical Data Priority

Live recording becomes the highest-priority implementation task.

Historical datasets can often be acquired later.

Live microstructure data that is not recorded today may be impossible to reconstruct perfectly tomorrow.

Therefore:

START THE RECORDER EARLY

becomes a formal engineering priority.

⸻

10. Initial Implementation Path

The implementation sequence becomes:

M0 Rev.2 Foundation

↓

M1 Storage Foundation

↓

M2 BTC Hyperliquid Live Recorder

↓

M3 Data Integrity & Replay

↓

M4 BTC Research Dataset

↓

M5 Baseline Strategy Research

↓

M6 Event-Driven Backtesting

↓

M7 Risk & Execution Skeleton

↓

M8 Hyperliquid Testnet

↓

M9 Paper Trading

↓

M10 Shadow Trading

↓

ML Research, only if justified

↓

Limited Live, only after all gates pass

⸻

11. M0 Rev.2 Foundation

The repository remains a modular monolith.

Core structure remains:

trading-platform/
apps/
services/
research/
libs/
infrastructure/
tests/
docs/

No Kubernetes.

No premature microservices.

No production execution.

⸻

12. Exchange Abstraction

Hyperliquid is the initial venue.

It must not become a permanent architectural dependency.

Execution remains behind:

ExchangeAdapter

with a conceptual contract such as:

get_market_state()
get_account_state()
place_order()
cancel_order()
get_orders()
get_positions()
get_fills()
subscribe_events()

Hyperliquid becomes:

HyperliquidAdapter

rather than becoming the trading system itself.

⸻

13. Single-Venue MVP

Build 0.1 intentionally uses one venue.

This is acceptable for experimental validation.

However:

Single Venue MVP ≠ Single Venue Architecture

Future venue diversification remains possible without rewriting:

* Strategy Engine
* Risk Engine
* Portfolio Engine
* Research Engine

⸻

14. AI Removed From Critical Path

AI/ML is no longer required before forward validation begins.

The initial system may progress through:

Backtest → Testnet → Paper → Shadow

using a simple quantitative baseline.

This allows the complete infrastructure to be tested before introducing model complexity.

⸻

15. Baseline Before AI

The first serious research candidate should come from a simple strategy family.

Possible families include:

* Trend
* Momentum
* Breakout
* Mean Reversion

The specific family and horizon will be selected after examining BTC perpetual market behavior, transaction costs and execution characteristics.

It will not be selected merely because it is easy to implement.

⸻

16. One Horizon First

The initial experiment uses one primary trading horizon.

Multi-horizon intelligence remains part of the future architecture.

The first horizon should be selected based on:

* Spread
* Fees
* Funding
* Slippage
* Market noise
* Signal persistence
* Execution latency
* Available data quality

⸻

17. Risk Engine Moves Earlier

A minimal Risk Engine must exist before sophisticated AI.

Initial controls include:

* BTC-only allowlist
* Testnet-only execution
* Maximum order size
* Intent expiration
* Trading enable/disable
* Data freshness requirement
* Duplicate-order protection
* Kill Switch

The purpose is to establish the capital-control boundary early.

⸻

18. Execution Engine Moves Earlier

Execution infrastructure should also be implemented before advanced strategy research is complete.

This allows early testing of:

* WebSocket disconnects
* API failures
* Timeouts
* Partial fills
* Duplicate requests
* Order reconciliation
* Position reconciliation
* Process crashes
* Restart recovery
* Kill Switch behavior

Execution reality should influence research assumptions as early as possible.

⸻

19. BTC Recorder

The first real system component consuming live market information will be:

BTC Hyperliquid Recorder

Initial responsibilities:

CONNECT
↓
SUBSCRIBE
↓
CAPTURE RAW
↓
TIMESTAMP
↓
VALIDATE
↓
NORMALIZE
↓
PERSIST
↓
MONITOR

It must support reconnect and gap detection from the beginning.

⸻

20. Raw Preservation

Original source messages should be retained whenever practical.

Pipeline:

Hyperliquid
    ↓
Raw Event
    ↓
Validation
    ↓
Normalized Event
    ↓
Analytical Storage

Normalization bugs must never destroy the original evidence.

⸻

21. Data Integrity

The recorder must detect:

* Connection loss
* Stale streams
* Missing intervals
* Duplicate events
* Invalid timestamps
* Malformed messages
* Schema changes
* Unexpected assets
* Persistence failures

Unknown data quality must never silently become valid research data.

⸻

22. Replayability

Recorded BTC events must become deterministically replayable.

The same input dataset and system version should produce the same ordered event stream.

This becomes the foundation of the event-driven backtester.

⸻

23. Research Dataset

Only after recorder integrity passes will Build 0.1 construct the first formal BTC research dataset.

Every dataset requires:

dataset_id
source
time_range
schema_version
quality_status
pit_status
checksum
creation_time

Research without dataset identity is prohibited.

⸻

24. First Research Question

The first research objective is not:

Can we predict Bitcoin?

It is:

Can a simple, reproducible BTC perpetual strategy produce a statistically credible positive expected value after realistic trading costs?

This is intentionally narrower.

⸻

25. Transaction Costs

Every serious experiment must account for:

* Fees
* Spread
* Slippage
* Funding
* Execution delay

A strategy profitable before costs but unprofitable afterward has no demonstrated trading edge.

⸻

26. Baseline Strategy Gate

The first baseline must pass:

* Point-in-time correctness
* Lookahead checks
* Out-of-sample testing
* Walk-forward validation
* Cost modeling
* Parameter robustness
* Regime decomposition
* Drawdown analysis

Only then may it become a Shadow candidate.

⸻

27. ML Entry Gate

Machine learning enters only when at least one of the following is justified:

1. A baseline signal exists and ML may improve trade selection.
2. Regime classification may improve strategy eligibility.
3. Meta-labeling may improve expected value.
4. Nonlinear relationships appear economically meaningful.

ML is therefore introduced to solve an observed problem.

It is not introduced because the product is branded as AI-powered.

⸻

28. ML Must Beat a Baseline

Every ML model must compete against a simpler relevant baseline.

Example:

Simple Strategy
        ↓
Logistic Regression
        ↓
LightGBM / XGBoost
        ↓
Advanced Sequence Model

A more complex model is promoted only if it demonstrates durable incremental value.

⸻

29. NO TRADE Remains First-Class

The simplified implementation does not weaken the original philosophy.

Valid outputs remain:

LONG
SHORT
NO TRADE

Trading frequency is not an objective.

⸻

30. NO EDGE FOUND

A new formal project outcome is introduced:

NO_EDGE_FOUND

This means:

Under the tested hypotheses, datasets, costs, execution assumptions and validation methodology, no strategy has demonstrated sufficient evidence of durable positive expected value.

This is a valid scientific result.

⸻

31. NO_EDGE_FOUND Is Not Failure

If no strategy passes the gates, the project must not:

* Lower validation standards
* Hide transaction costs
* Search endlessly until a profitable backtest appears
* Increase leverage
* Cherry-pick periods
* Replace evidence with AI complexity

Instead, the project enters a formal decision process.

⸻

32. No-Edge Decision Tree

If:

NO_EDGE_FOUND

then evaluate:

Was the hypothesis weak?
        ↓
Was the horizon inappropriate?
        ↓
Was the strategy family inappropriate?
        ↓
Is another dataset economically justified?
        ↓
Is another market justified?
        ↓
Is another venue justified?

Possible final decision:

STOP TRADING RESEARCH

Stopping is acceptable if evidence does not justify continued investment.

⸻

33. No Founder Override

The original Phase 10 rule remains intact.

No founder, engineer, model or business objective may convert:

NO_EDGE_FOUND

into:

DEPLOY ANYWAY

Real capital requires evidence.

⸻

34. Shadow Before AI Is Allowed

If a simple baseline passes historical validation, it may enter Paper and Shadow validation without an ML layer.

This provides earlier evidence about:

* Execution assumptions
* Live feature behavior
* Slippage
* Funding
* Data reliability
* Operational stability
* Backtest-to-live divergence

⸻

35. Shadow Twin Remains Mandatory

When real-money validation eventually begins, every real trade should retain its corresponding Shadow Twin.

This allows direct comparison between:

Expected Execution

and:

Real Execution

The original Phase 8 principle remains unchanged.

⸻

36. Scaling One Dimension at a Time

Future expansion must change only one major dimension at a time where practical.

Examples:

BTC → BTC + ETH

or:

Baseline → ML-enhanced baseline

or:

Shadow → Limited Live

or:

Low capital → Higher capital

Avoid simultaneously increasing:

* Assets
* Models
* Strategies
* Capital
* Leverage
* Autonomy

Otherwise causal attribution becomes weak.

⸻

37. Regulatory Track

Regulatory analysis becomes an independent project track.

It does not block private Testnet/Paper research.

It becomes mandatory before:

* Public launch
* Offering automated leveraged trading to users
* Marketing the service
* Monetizing user execution
* Builder-fee implementation
* Jurisdiction expansion

Technical readiness does not imply legal readiness.

⸻

38. Builder Fee Conflict

Builder-fee monetization remains disabled during research.

If introduced later, the system must ensure that strategy objectives are not rewarded for increasing trading volume.

The optimization objective remains:

Net Risk-Adjusted User Outcome

not:

Trading Volume

⸻

39. Build 0.1 Rev.2 Success Definition

Build 0.1 Rev.2 succeeds when we can prove:

1. BTC live data is reliably recorded.
2. Raw data is preserved.
3. Data quality is measured.
4. Gaps are visible.
5. Reconnect works.
6. Events are deterministically replayable.
7. Research datasets are reproducible.
8. Testnet execution works.
9. Risk controls cannot be trivially bypassed.
10. Orders and positions reconcile correctly.
11. Failure scenarios are tested.
12. The complete workflow is auditable.

Profitability is NOT a Build 0.1 acceptance criterion.

⸻

40. Revised Architecture

                 HYPERLIQUID
                      │
                      ▼
              BTC LIVE RECORDER
                      │
             ┌────────┴────────┐
             ▼                 ▼
         RAW STORAGE      NORMALIZATION
                               │
                               ▼
                        QUALITY ENGINE
                               │
                               ▼
                         BTC DATASET
                               │
                               ▼
                        REPLAY ENGINE
                               │
                               ▼
                      BASELINE RESEARCH
                               │
                               ▼
                    EVENT-DRIVEN BACKTEST
                               │
                        ┌──────┴──────┐
                        │             │
                        ▼             ▼
                   NO EDGE        CANDIDATE
                                      │
                                      ▼
                                RISK ENGINE
                                      │
                                      ▼
                              EXECUTION ENGINE
                                      │
                                      ▼
                            HYPERLIQUID TESTNET
                                      │
                                      ▼
                              PAPER / SHADOW
                                      │
                            ┌─────────┴─────────┐
                            ▼                   ▼
                       NO EDGE            ML RESEARCH
                                               │
                                               ▼
                                         LIMITED LIVE

⸻

41. Immediate Engineering Target

The next implementation target is now:

M0 Rev.2 + M1 + M2

Specifically:

M0 Rev.2

Update repository scope and safety configuration.

M1

Verify PostgreSQL, ClickHouse, Redis and raw object storage.

M2

Run the first real:

BTC Hyperliquid Live Recorder

and produce evidence demonstrating:

Live BTC Event
     ↓
Raw Capture
     ↓
Timestamp
     ↓
Validation
     ↓
Normalization
     ↓
Persistence

⸻

42. Final Decision

Build 0.1 Rev.1: Superseded, retained for historical traceability.

Build 0.1 Rev.2: APPROVED.

Experimental Asset: BTC ONLY.

On-Chain: DEFERRED.

Commercial Data: DEFERRED.

AI: REMOVED FROM INITIAL CRITICAL PATH.

Risk & Execution: MOVED FORWARD.

Real Capital: PROHIBITED.

Mainnet Execution: HARD-BLOCKED.

Valid Research Outcome: EDGE_FOUND or NO_EDGE_FOUND.

Immediate Next Step

Implement M0 Rev.2 → M1 → M2 BTC Recorder

The first meaningful evidence milestone is no longer a document or an AI prediction.

It is:

A real BTC market event received from Hyperliquid, preserved in raw form, timestamped, validated, normalized, persisted, and deterministically reproducible.