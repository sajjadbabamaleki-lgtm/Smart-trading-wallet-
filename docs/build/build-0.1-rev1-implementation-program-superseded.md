IMPLEMENTATION PROGRAM — BUILD 0.1

Program: AI Automated Perpetual Futures Trading Platform
Architecture: Phases 1–10 Approved
Build: 0.1
Purpose: Foundation & Evidence
Real Capital: PROHIBITED
Initial Venue: Hyperliquid Testnet
Assets: BTC / ETH / SOL / BNB

⸻

1. Build 0.1 Mission

Build 0.1 will create the first functioning skeleton of the system.

Its objective is NOT:

AI trading

profitability

frontend polish

or:

real-money execution

Its objective is to establish a trustworthy engineering foundation capable of:

1. Receiving real market data
2. Preserving raw data
3. Normalizing market events
4. Detecting data gaps
5. Reconnecting safely
6. Reproducing datasets
7. Connecting to Hyperliquid Testnet
8. Recording exchange state
9. Producing complete audit evidence
10. Running deterministic automated tests

Only after these foundations are demonstrated should strategy implementation begin.

⸻

2. Build Philosophy

Every implementation milestone follows:

BUILD

↓

TEST

↓

BREAK

↓

OBSERVE

↓

FIX

↓

RETEST

↓

EVIDENCE

↓

PASS / FAIL

A feature without evidence is not considered complete.

⸻

3. Initial Repository Strategy

Start with:

One Monorepo

rather than multiple repositories.

Recommended structure:

trading-platform/
├── apps/
│   └── web/
│
├── services/
│   ├── market_data/
│   ├── feature_engine/
│   ├── strategy_engine/
│   ├── risk_engine/
│   ├── execution_engine/
│   └── portfolio_engine/
│
├── research/
│   ├── notebooks/
│   ├── experiments/
│   ├── backtests/
│   └── datasets/
│
├── libs/
│   ├── schemas/
│   ├── domain/
│   ├── exchange/
│   ├── observability/
│   └── security/
│
├── infrastructure/
│   ├── docker/
│   ├── database/
│   ├── monitoring/
│   └── scripts/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── replay/
│   ├── failure/
│   └── security/
│
├── docs/
│   ├── architecture/
│   ├── ADR/
│   ├── runbooks/
│   └── evidence/
│
└── .github/
    └── workflows/

This structure preserves logical boundaries without prematurely introducing distributed-system complexity.

⸻

4. Architecture Decision Records

Important engineering decisions receive:

ADR

Architecture Decision Records.

Examples:

ADR-001
Why Python is used for the trading core.

ADR-002
Why ClickHouse is used for high-frequency historical data.

ADR-003
Why PostgreSQL remains separate.

ADR-004
Why V1 begins as a modular monolith.

ADR-005
Why Hyperliquid Testnet is the first execution integration.

Architectural decisions should remain historically explainable.

⸻

5. Core Languages

Trading / Research

Python

Product Frontend

TypeScript

React

Next.js

Python owns:

* Market Data
* Features
* Strategies
* ML
* Risk
* Execution
* Backtesting

TypeScript owns:

* Product interface
* Wallet UX
* User controls

⸻

6. Python Runtime

Use one pinned modern Python runtime across trading services.

Runtime versions must be controlled.

Production behavior should never depend on:

whatever Python happens to be installed.

⸻

7. Python Environment

Dependencies require:

* Version locking
* Reproducible installation
* Separate production/dev dependencies
* Automated vulnerability scanning

Research experiments may use additional packages but production dependencies remain deliberately small.

⸻

8. Initial Python Libraries

Candidate foundation:

Polars

NumPy

Pydantic

HTTP/WebSocket libraries

Official Hyperliquid SDK

Testing:

pytest

ML libraries are intentionally NOT required during the first milestone.

⸻

9. Polars Decision

Polars becomes the preferred dataframe engine for:

* Feature generation
* Dataset preparation
* Research transformations

Its lazy execution model should be used for larger pipelines where appropriate.

Pandas may remain available for interoperability but should not become the default analytical engine.

⸻

10. Infrastructure

Initial development infrastructure:

Docker Compose

Services:

PostgreSQL

ClickHouse

Redis

Object Storage

plus application services.

Do not introduce Kubernetes in Build 0.1.

⸻

11. Why No Kubernetes Yet

At this stage Kubernetes would introduce:

* Deployment complexity
* Networking complexity
* Security complexity
* Observability complexity
* Operational overhead

without proving a corresponding need.

Infrastructure complexity must earn its place just like ML complexity.

⸻

12. PostgreSQL Responsibility

PostgreSQL stores transactional/application state.

Examples:

* Users
* Wallet mappings
* Trading accounts
* Strategy registry
* Model registry
* Risk configurations
* Execution intents
* Orders
* Positions
* Incidents
* Configuration versions

It is NOT the primary raw tick-data warehouse.

⸻

13. ClickHouse Responsibility

ClickHouse stores analytical high-volume event data.

Examples:

* Trades
* Order-book events
* Quotes
* Funding
* Open interest
* Market context
* Feature history
* Prediction history
* Execution analytics

This separates transactional state from analytical market history.

⸻

14. Object Storage Responsibility

Object storage contains immutable raw datasets.

Conceptually:

raw/
  hyperliquid/
  binance/
  onchain/
  external/

Raw source data should be preserved before aggressive transformation.

⸻

15. Redis Responsibility

Redis should initially be limited to:

* Live state cache
* Short-lived coordination
* Rate-limit state
* Fast ephemeral data

Redis must not become the authoritative source of capital state.

⸻

16. Source of Truth Hierarchy

Different information has different authoritative sources.

Actual Position

Exchange

Application Position Record

PostgreSQL

Historical Market Events

Raw Archive + ClickHouse

Live Cache

Redis

Model Artifact

Model Registry / Artifact Store

Never assume one database is authoritative for everything.

⸻

17. Timestamp Standard

Every market event should support appropriate timestamps.

Minimum common fields:

event_time
exchange_time
provider_time
ingestion_time

where available.

Internally:

UTC

becomes mandatory.

⸻

18. Timestamp Precision

High-frequency market events should support sufficient sub-second precision.

Do not reduce everything to second-level timestamps.

Precision requirements must preserve the source’s meaningful timing.

⸻

19. Canonical Market Event Schema

Initial normalized event schema:

event_id
source
venue
asset
instrument
event_type
event_time
exchange_time
provider_time
ingestion_time
sequence
price
quantity
side
raw_reference
quality_status
pit_status
schema_version

Not every field applies to every event type.

⸻

20. Schema Versioning

Every event carries:

schema_version

A schema change must not silently reinterpret historical records.

⸻

21. Raw Data Rule

Incoming raw information should be preserved before normalization whenever practical.

Pipeline:

SOURCE

↓

RAW

↓

VALIDATE

↓

NORMALIZE

↓

STORE

↓

FEATURES

Raw data is never overwritten because normalization logic changed.

⸻

22. Data Layers

Implement:

BRONZE

Raw source data.

SILVER

Validated normalized data.

GOLD

Research/ML-ready features.

Build 0.1 focuses primarily on:

Bronze + Silver

Gold begins later.

⸻

23. First Live Data Source

First live integration:

Hyperliquid

because it is currently our intended execution environment.

The objective is to learn the actual environment where fills may eventually occur.

⸻

24. First Required Hyperliquid Streams

Recorder should initially capture:

Trades

L2 Book

BBO

Asset Context

Later:

Order Updates

User Fills

Funding

User Events

during execution testing.

⸻

25. Initial Assets

Recorder subscribes only to:

BTC

ETH

SOL

BNB

No uncontrolled universe expansion.

⸻

26. Market Data Recorder

Create:

market-data-recorder

Responsibilities:

1. Connect
2. Subscribe
3. Timestamp
4. Preserve raw message
5. Normalize
6. Validate
7. Persist
8. Monitor
9. Reconnect
10. Record gaps

⸻

27. Recorder State Machine

Explicit states:

STARTING
CONNECTING
CONNECTED
SUBSCRIBING
HEALTHY
DEGRADED
RECONNECTING
BACKFILLING
FAILED

No hidden reconnect behavior.

⸻

28. Heartbeat

Recorder must know whether:

socket connected

and:

useful data flowing

These are not equivalent.

Heartbeat monitoring should detect silent connections.

⸻

29. Reconnect Logic

When WebSocket disconnects:

DISCONNECT DETECTED
↓
record timestamp
↓
RECONNECT
↓
RESUBSCRIBE
↓
receive snapshot
↓
identify missing interval
↓
BACKFILL where possible
↓
register unresolved gap
↓
HEALTHY

⸻

30. Gap Registry

Create a dedicated:

data_gap_registry

Example:

gap_id
source
asset
event_type
start_time
end_time
detected_at
backfill_status
resolution
quality_impact

Missing data must never silently disappear.

⸻

31. Duplicate Detection

Reconnect and backfill can create duplicates.

Every ingestion path must implement deterministic or source-aware deduplication.

Duplicate removal must not accidentally delete legitimate repeated market events.

⸻

32. Sequence Monitoring

Where source sequence information exists:

track:

expected_sequence
actual_sequence

Unexpected sequence jumps generate a gap event.

⸻

33. Data Quality Engine 0.1

Initial checks:

Missing fields

Invalid numeric values

Impossible timestamps

Extreme timestamp delay

Malformed messages

Duplicate events

Unexpected schema

Sequence gaps

Negative quantity

Unknown asset

⸻

34. Data Quality Status

Each event/batch may receive:

VALID

WARNING

INVALID

UNKNOWN

Invalid data must not silently enter future training datasets.

⸻

35. Data Freshness Monitor

For each stream:

now - latest_valid_event_time

becomes a monitored metric.

If stale:

DEGRADED

Later this connects directly to:

NO TRADE

⸻

36. Data Recorder Evidence

Build 0.1 must prove:

* Continuous recording
* Reconnection
* Gap detection
* Backfill behavior
* Deduplication
* Schema validation
* Persistence
* Restart recovery

Screenshots are not sufficient evidence.

Automated logs/tests are required.

⸻

37. Historical Acquisition Skeleton

After live recording works:

implement batch ingestion architecture for:

Binance public historical market data

and:

Hyperliquid historical archive

without yet downloading the maximum possible dataset.

First prove:

small reproducible acquisition

↓

checksum/validation

↓

normalize

↓

query

⸻

38. Dataset Manifest

Every acquired dataset receives:

dataset_id
source
assets
start_time
end_time
data_types
acquired_at
source_version
schema_version
quality_summary
pit_status
checksum

⸻

39. Dataset Reproducibility

Given:

dataset_id

the research system should eventually reconstruct exactly which data was used.

This becomes mandatory before serious backtesting.

⸻

40. Point-in-Time Metadata

Initial implementation includes:

pit_status

Possible values:

PIT_SAFE

PIT_APPROXIMATE

NON_PIT

Future strict validation can reject NON_PIT datasets automatically.

⸻

41. Testnet Integration

After the market-data foundation passes:

create:

hyperliquid-testnet-adapter

No mainnet execution credentials are permitted.

⸻

42. Testnet Adapter Responsibilities

Implement:

* Account query
* Market metadata
* Order submission
* Order cancellation
* Order status
* Position query
* Fill query
* WebSocket order events

No AI is required.

Orders are generated by deterministic test scenarios.

⸻

43. Exchange Abstraction

Hyperliquid-specific implementation lives behind:

ExchangeAdapter

Conceptual interface:

get_market_state()
get_account_state()
place_order()
cancel_order()
get_orders()
get_positions()
get_fills()
subscribe_events()

This allows future venues without rewriting Risk or Strategy layers.

⸻

44. Hyperliquid Adapter

Implement:

HyperliquidAdapter

using official APIs/SDK where appropriate.

Do not duplicate cryptographic signing logic without a demonstrated need.

⸻

45. Testnet Credential

Generate a dedicated:

TESTNET API WALLET

It must never be reused for future production.

The credential is stored through environment/secrets management rather than source code.

⸻

46. Mainnet Protection

Build 0.1 should contain an explicit guard preventing accidental mainnet order execution.

Example architectural control:

EXECUTION_ENVIRONMENT = TESTNET

with fail-closed validation.

Changing one URL should not accidentally enable real-money trading.

⸻

47. Execution Intent Skeleton

Even testnet orders should begin using the future architecture.

Create:

ExecutionIntent

Fields:

intent_id
created_at
expires_at
asset
direction
max_quantity
order_type
price_constraints
reduce_only
risk_decision_id
status

⸻

48. No Direct Orders

Even during Build 0.1:

application components should not casually call:

exchange.place_order()

Orders should flow:

TEST SCENARIO
↓
EXECUTION INTENT
↓
EXECUTION ENGINE
↓
EXCHANGE ADAPTER

This establishes the correct architecture early.

⸻

49. Execution State Machine

Implement:

CREATED
VALIDATED
SUBMITTED
ACKNOWLEDGED
PARTIALLY_FILLED
FILLED
CANCEL_PENDING
CANCELLED
REJECTED
EXPIRED
UNKNOWN

UNKNOWN is a real state.

⸻

50. Order Audit

Every execution action records:

internal_order_id
intent_id
exchange_order_id
asset
direction
quantity
order_type
requested_price
submitted_at
acknowledged_at
status
exchange_response_reference

⸻

51. Reconciliation 0.1

Create the first reconciliation loop:

LOCAL ORDERS
vs
EXCHANGE ORDERS
LOCAL POSITIONS
vs
EXCHANGE POSITIONS

Mismatch produces:

RECONCILIATION ALERT

Never silently repair without recording what changed.

⸻

52. Restart Test

Required test:

1. Submit Testnet order
2. Kill Execution Engine
3. Restart service
4. Query exchange
5. Recover order/position state
6. Reconcile
7. Produce audit evidence

If this fails:

Build 0.1 does not pass.

⸻

53. Duplicate Order Test

Required:

1. Generate intent
2. Submit
3. Simulate network timeout
4. Retry workflow
5. Verify only permitted order state exists

A timeout cannot automatically mean:

submit another order.

⸻

54. Risk Engine Skeleton

Do NOT implement sophisticated portfolio risk yet.

Implement deterministic basic controls:

* Asset allowlist
* Maximum test order size
* Intent expiration
* Environment restriction
* Reduce-only validation
* Global trading enabled flag

This creates the security boundary before AI arrives.

⸻

55. Risk Decision

Initial object:

RiskDecision
decision_id
intent_candidate_id
decision
reason_codes
approved_quantity
created_at
expires_at

Decision:

APPROVED
MODIFIED
REJECTED

⸻

56. Risk Reason Codes

Start standardized codes immediately.

Examples:

RISK_ASSET_NOT_ALLOWED
RISK_SIZE_EXCEEDED
RISK_INTENT_EXPIRED
RISK_ENVIRONMENT_BLOCKED
RISK_TRADING_DISABLED
RISK_DATA_STALE

Machine-readable reason codes become extremely valuable later.

⸻

57. Kill Switch 0.1

Implement:

TRADING_ENABLED = TRUE/FALSE

When FALSE:

No new exposure

Testnet execution must prove this control cannot be bypassed through ordinary order routes.

⸻

58. Audit Event System

Create universal:

AuditEvent

Fields:

event_id
event_type
timestamp
service
actor_type
actor_id
entity_type
entity_id
payload_reference
correlation_id
severity

⸻

59. Correlation ID

Every important workflow receives a:

correlation_id

Example:

signal
→ risk decision
→ intent
→ order
→ fill

can later be reconstructed as one chain.

Implement this now rather than retrofitting it later.

⸻

60. Structured Logging

Logs should be machine-readable.

Prefer structured events rather than free-text logs such as:

Something went wrong with BTC.

Example:

event=order_rejected
asset=BTC
reason=RISK_SIZE_EXCEEDED
correlation_id=...

⸻

61. Metrics

Initial metrics:

Data

* messages_received
* messages_invalid
* gaps_detected
* reconnects
* stream_lag

Execution

* orders_submitted
* orders_rejected
* order_ack_latency
* reconciliation_mismatches

System

* service_health
* database_latency
* error_rate

⸻

62. Alerting

Build 0.1 needs simple operational alerts for:

* Recorder down
* Data stale
* Database unavailable
* Repeated reconnect
* Reconciliation mismatch
* Execution UNKNOWN

Do not build a giant observability platform yet.

⸻

63. Testing Pyramid

Required:

Unit Tests

Pure functions and domain rules.

Integration Tests

Database and exchange adapters.

Replay Tests

Recorded market data replay.

Failure Tests

Disconnects and crashes.

Security Tests

Authorization and environment boundaries.

⸻

64. Deterministic Tests

Tests must not rely unnecessarily on current market direction.

Example:

Bad test:

BTC should rise.

Good test:

Given this recorded sequence of messages, normalization must produce exactly these events.

⸻

65. Recorded Fixtures

Store small sanitized market-event fixtures.

These allow deterministic testing of:

* Parser
* Normalizer
* Feature functions later
* Gap detection
* Replay

⸻

66. Replay Engine 0.1

Implement a minimal:

Event Replay Engine

Input:

Recorded events.

Output:

Events emitted according to deterministic ordering.

This becomes the seed of the future event-driven backtester.

⸻

67. Replay Clock

Do not depend on wall-clock time.

Create:

Clock

abstraction.

Implement:

SystemClock
ReplayClock

This tiny architectural choice will later save enormous pain in backtesting.

⸻

68. Dependency Injection

Core components should receive:

* Clock
* Exchange Adapter
* Data Store
* Configuration

through explicit interfaces.

This allows production components to be replaced with deterministic test implementations.

⸻

69. Configuration

Configuration should be typed and validated.

Examples:

ENVIRONMENT
EXCHANGE
DATABASE
ASSETS
DATA_STALENESS_LIMIT
TRADING_ENABLED

Invalid configuration should fail startup.

⸻

70. Environment Guard

If:

ENVIRONMENT=development

and a production execution credential is detected:

FAIL STARTUP

Build safety into configuration rather than relying on memory.

⸻

71. CI Pipeline

Every pull request should run:

1. Formatting
2. Linting
3. Type checks
4. Unit tests
5. Integration tests where practical
6. Secret scanning
7. Dependency/security scanning

Broken critical checks block merge.

⸻

72. Main Branch Protection

Main branch requires:

* Pull Request
* Passing CI
* Review
* No direct casual production changes

Even with a small initial team.

⸻

73. Security From Day One

Build 0.1 should already implement:

* No committed secrets
* Environment separation
* Secret scanning
* Dependency scanning
* Structured audit
* Least privilege database users

Security is not postponed until launch.

⸻

74. No AI Yet

A deliberate Build 0.1 decision:

DO NOT IMPLEMENT THE AI MODEL YET.

Until we trust:

Data

Time

Schemas

Replay

Execution

Audit

adding AI would create sophistication on top of uncertain foundations.

⸻

75. No Strategy Yet

Similarly:

Do not begin by writing:

RSI strategy

or:

Transformer strategy

to make the application appear alive.

The first signal can wait.

⸻

76. Build 0.1 Milestones

M0 — Repository Foundation

Monorepo
CI
Docker
Configuration
Testing skeleton
Security scanning

↓

M1 — Storage Foundation

PostgreSQL
ClickHouse
Redis
Object Storage
Schemas
Migrations

↓

M2 — Hyperliquid Live Recorder

WebSocket
BTC/ETH/SOL/BNB
Raw capture
Normalization
Persistence

↓

M3 — Data Integrity

Quality checks
Gap Registry
Reconnect
Backfill
Deduplication
Freshness monitoring

↓

M4 — Historical Acquisition Skeleton

Hyperliquid archive
Binance sample history
Dataset manifests
PIT metadata

↓

M5 — Replay Engine

Recorded fixtures
Replay Clock
Deterministic event stream

↓

M6 — Hyperliquid Testnet

Dedicated testnet credential
Exchange Adapter
Account query
Orders
Cancels
Fills
Positions

↓

M7 — Risk Skeleton

Allowlist
Size limit
Expiration
Environment guard
Kill Switch

↓

M8 — Execution & Reconciliation

Execution Intent
Order state machine
Reconciliation
Restart recovery
Duplicate protection

↓

M9 — Evidence Pack

Automated tests
Failure reports
Data-quality report
Execution report
Security checks
Acceptance review

⸻

77. Build 0.1 Hard Gate

Build 0.1 cannot pass until:

Infrastructure

* Clean environment can start entire stack.
* Configuration is validated.
* Secrets are absent from source.
* CI passes.

Data

* Four assets stream successfully.
* Raw data is retained.
* Normalized data is queryable.
* Reconnect works.
* Gaps are detected.
* Duplicates are handled.
* Freshness is measured.
* Dataset manifests exist.

Replay

* Recorded events can be replayed deterministically.
* Replay does not depend on real wall-clock time.

Testnet

* Account state can be queried.
* Order can be submitted.
* Order can be cancelled.
* Fill can be detected.
* Position can be reconciled.
* Service restart can recover state.

Risk

* Unsupported assets are rejected.
* Oversized test orders are rejected.
* Expired intents are rejected.
* Kill Switch blocks new exposure.
* Mainnet accidental execution is structurally blocked.

Audit

* A test order can be reconstructed from:

Intent
→ Risk Decision
→ Submission
→ Exchange Response
→ Fill
→ Position

Failure

* WebSocket disconnect tested.
* Exchange timeout tested.
* Database interruption tested.
* Execution restart tested.
* Duplicate-order scenario tested.

Only then:

BUILD 0.1 = PASSED

⸻

78. Evidence Pack

Build completion creates:

docs/evidence/build-0.1/

containing:

infrastructure-report
data-ingestion-report
data-quality-report
reconnect-test
gap-detection-test
replay-determinism-test
testnet-order-report
reconciliation-report
restart-recovery-report
duplicate-order-test
kill-switch-test
security-scan-report
acceptance-matrix

The evidence pack becomes part of project history.

⸻

79. What Build 0.1 Does Not Contain

Explicitly excluded:

Production Mainnet Trading

Real Capital

Final AI Models

Strategy Optimization

Native Wallet

Full Product UI

Capital Scaling

Production Deployment

This protects focus.

⸻

80. Build 0.2

Only after Build 0.1 passes:

BUILD 0.2 — RESEARCH ENGINE

will begin.

Its mission will be:

Historical datasets

↓

Feature Engine

↓

Backtesting Engine

↓

Baseline Strategies

↓

PIT / Lookahead Validation

↓

Walk Forward

↓

Robustness Testing

No AI complexity until simple baselines exist.

⸻

81. Build 0.3

After research infrastructure proves reliable:

BUILD 0.3 — INTELLIGENCE ENGINE

will introduce:

Regime Engine

LightGBM

XGBoost

Meta-Labeling

Calibration

Ensemble

Uncertainty

Only then will ML begin competing against validated baseline strategies.

⸻

82. Build 0.4

Then:

BUILD 0.4 — COMPLETE RISK & EXECUTION

Portfolio risk

Correlation

Dynamic sizing

Leverage

Stops

TP

Liquidation monitoring

Safe Mode

Failure handling

⸻

83. Build 0.5

Then:

BUILD 0.5 — SHADOW SYSTEM

Paper

Shadow Twin

Drift

Calibration

Execution modeling

Backtest-to-Live Gap

⸻

84. Build 0.6

Then:

BUILD 0.6 — PRODUCT

Next.js

Phantom

Trust Wallet

Autopilot

Copilot

Research

WHY THIS TRADE?

Risk UI

Emergency controls

⸻

85. Build 0.7

Then:

BUILD 0.7 — SECURITY QUALIFICATION

Threat-model verification

Penetration testing

Failure injection

Independent audit

Limited-Live readiness

⸻

86. Build 1.0

Build 1.0 is NOT defined by feature count.

It is reached when:

Implementation Evidence

satisfies:

Architecture Acceptance Gates

and the system has survived the required validation progression.

⸻

87. First Engineering Action

The first actual implementation action is:

M0 — REPOSITORY FOUNDATION

We create:

Repository

Python project

TypeScript/web shell

Docker Compose

PostgreSQL

ClickHouse

Redis

Object storage

CI

Tests

Configuration

Secret scanning

No market prediction code is written yet.

⸻

88. Build 0.1 Decision

APPROVED FOR IMPLEMENTATION

Real-money trading remains:

PROHIBITED

AI implementation remains:

DEFERRED

Strategy optimization remains:

DEFERRED

The immediate engineering target is:

M0 → M1 → M2

The first meaningful victory of this project will not be:

“The AI predicted BTC.”

It will be:

“We can prove exactly what the market sent us, when we received it, what we stored, what was missing, and reproduce it deterministically.”

That is the foundation on which everything else depends.