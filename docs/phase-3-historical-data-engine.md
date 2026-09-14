Historical Data Engine Specification

Version: 1.0
Phase: 3 — Historical Data Engine
Core Assets: BTC, ETH, SOL, BNB
System: AI-Powered Automated Trading Platform
Status: Research Architecture
Priority: Critical

⸻

1. Purpose

The Historical Data Engine is the long-term memory of the trading intelligence system.

Its purpose is not simply to store historical cryptocurrency prices.

It must reconstruct, as accurately as technically possible, what the cryptocurrency market looked like at any historical point in time.

For any historical timestamp T, the research system should ultimately be capable of answering:

What information would the trading system genuinely have known at this exact moment?

The Historical Data Engine therefore combines:

* Market history
* Trade history
* Order-book history
* Derivatives history
* On-chain history
* Cross-market history
* Execution-related information
* Data-quality metadata

for:

BTC

ETH

SOL

BNB

The resulting datasets will become the foundation for:

* Backtesting
* Feature engineering
* Machine learning
* Market regime detection
* Strategy discovery
* Risk research
* Execution simulation
* Model validation

⸻

2. Fundamental Design Principle

The Historical Data Engine must not be designed around a single provider.

The required architecture is:

Primary Sources

Institutional Historical Sources

Blockchain Sources

Our Own Continuous Recorder

↓

Canonical Historical Data Layer

This is necessary because no single provider offers complete, perfectly reliable, point-in-time-correct historical coverage of every market variable required by the system.

⸻

3. Historical Data Domains

The engine will maintain six primary historical domains.

Domain A — Price and Market Activity

Required data:

* OHLCV
* Tick-level trades
* Aggregate trades
* Buy/Sell aggressor classification
* Trading volume
* VWAP
* Number of trades
* Bid/Ask
* Spread
* Mid price

This forms the basic market-history layer.

⸻

4. Domain B — Order Book History

Historical order-book information is substantially more valuable than candles for reconstructing actual market conditions.

Required information should include, where available:

* Level 1 quotes
* Level 2 Order Book
* Bid levels
* Ask levels
* Bid depth
* Ask depth
* Spread
* Depth distribution
* Book imbalance
* Order-book updates
* Liquidity gaps
* Liquidity concentration

The preferred long-term objective is event-level reconstruction.

However, complete historical event-level L2 coverage cannot be assumed across all venues and all historical periods.

The system must therefore explicitly identify the quality level of every order-book dataset.

Possible classifications:

L2-EVENT

Complete or near-complete event-level order-book updates.

L2-SNAPSHOT

Periodic Level 2 snapshots.

L1

Best Bid / Best Ask only.

UNAVAILABLE

No reliable historical book information.

Models must know which information class was available for each historical period.

⸻

5. Domain C — Derivatives History

Because the trading system targets perpetual futures, derivatives history is a first-class dataset.

Required fields include:

* Funding Rate
* Predicted Funding where available
* Open Interest
* Open Interest Change
* Mark Price
* Index Price
* Oracle Price where applicable
* Premium Index
* Perpetual Basis
* Futures Volume
* Liquidation events where reliable
* Long/Short positioning proxies where reliable

Derived historical features may include:

Price × OI divergence

Funding acceleration

Funding extremes

OI acceleration

Liquidation intensity

Basis expansion

Basis compression

These variables may provide information that cannot be inferred from price alone.

⸻

6. Domain D — On-Chain History

The Historical Data Engine must maintain a separate blockchain-intelligence layer.

It must not assume that all public blockchain information is automatically useful for prediction.

Raw blockchain history will therefore be transformed into measurable features.

Potential categories include:

Network Activity

* Transaction count
* Transfer volume
* Active addresses
* Sending addresses
* Receiving addresses
* Fees
* Network utilization

Capital Movement

* Large transfers
* Transfer-size distributions
* Stablecoin movement
* Bridge activity
* DEX flows

Exchange Interaction

Where reliable historical entity labels exist:

* Exchange inflows
* Exchange outflows
* Exchange netflows
* Exchange balances
* Exchange reserves

Large Holder Behavior

Where statistically defensible:

* Whale transaction activity
* Large wallet accumulation
* Large wallet distribution
* Concentration changes

These features must be evaluated experimentally rather than assumed to contain predictive value.

⸻

7. Critical Finding — On-Chain Point-in-Time Problem

A major issue identified during provider research concerns historical wallet labeling.

Many exchange-flow datasets depend on identifying which blockchain addresses belong to exchanges.

These classifications evolve over time.

For example, a provider may discover today that an address used three years ago belonged to an exchange.

If that updated classification is inserted into a historical dataset, the backtest may receive information that traders did not possess at the historical moment.

This creates a subtle form of:

Historical Information Leakage

Some providers explicitly acknowledge this limitation.

Therefore, every entity-derived on-chain feature must receive a classification:

PIT-SAFE

Point-in-time reconstruction is sufficiently reliable.

PIT-APPROXIMATE

Historical information may contain later classification improvements.

NON-PIT

The feature must not be used in strict predictive validation.

NON-PIT features may still be used for exploratory research but must not silently enter production-model validation.

⸻

8. Domain E — Cross-Market History

The four assets must be synchronized into a shared historical timeline.

The system should reconstruct relationships such as:

* BTC ↔ ETH
* BTC ↔ SOL
* BTC ↔ BNB
* ETH ↔ SOL
* ETH ↔ BNB
* SOL ↔ BNB

Derived features may include:

* Rolling correlation
* Relative momentum
* Relative volume
* Beta to BTC
* Beta to ETH
* Lead/Lag relationships
* Relative volatility
* Divergence
* Market-wide breadth
* Volatility propagation

BTC should also be considered a potential global market-state variable for the other three assets.

⸻

9. Domain F — Historical Execution Environment

A conventional backtest assumes:

Signal price = execution price.

This assumption is unacceptable for the final research environment.

The Historical Data Engine should retain enough information to estimate:

* Bid/Ask spread
* Available depth
* Slippage
* Maker/Taker conditions
* Funding cost
* Order latency assumptions
* Partial-fill probability
* Market impact approximation

The purpose is to eventually enable:

Execution-Aware Backtesting

rather than theoretical candle-based trading.

⸻

10. Data Source Strategy

Provider research indicates that the project should use a layered sourcing strategy.

Tier 1 — Exchange-Native Data

Exchange-native historical information should be preferred where reliable.

Examples include:

* Binance public historical datasets
* Hyperliquid historical archives
* Exchange APIs
* Exchange WebSocket streams

Binance currently provides downloadable public historical datasets including spot and futures:

* Trades
* Aggregate Trades
* Klines
* Futures price series

with downloadable checksum files.

The public repository also documents futures trade downloads extending from 2020 for available datasets.

This makes Binance valuable for reconstructing major centralized-market history.

However, exchange-native archives must still pass our independent quality validation.

⸻

11. Hyperliquid Historical Data

Hyperliquid provides historical archives including:

* L2 Book snapshots
* Asset contexts
* Trade/fill-related historical data
* Historical node data

However, its own documentation states that historical asset data is uploaded approximately monthly, timely updates are not guaranteed, and data may be missing.

Therefore:

Hyperliquid Historical Archive ≠ Complete Historical Truth

It should be used as:

Historical Source + Validation Source

while our own recorder continuously captures new information.

⸻

12. Institutional Market Data Providers

For historical market microstructure and derivatives reconstruction, institutional-grade providers should be evaluated.

Coin Metrics

Coin Metrics exposes historical market datasets including:

* Trades
* Order Books
* Quotes
* Funding Rates
* Open Interest
* Liquidation-related metrics
* Candles

Its catalog also exposes the historical availability range for individual markets and data types.

This makes it particularly useful for determining exactly which historical periods are genuinely available before purchasing or ingesting data.

⸻

Kaiko

Kaiko provides:

* Tick-level trades
* Order-book information
* Spot data
* Derivatives data
* Funding
* Open Interest
* Liquidation information
* Historical exchange data

Its documentation indicates historical tick-level trade coverage reaching significantly further back for supported markets, while derivatives datasets have their own later coverage windows.

Kaiko should be evaluated primarily for:

Market Microstructure

and:

Institutional Historical Market Data

rather than used automatically for every dataset.

⸻

13. On-Chain Data Providers

Glassnode

Glassnode currently supports on-chain information for all four core assets:

BTC

ETH

SOL

BNB

Available metric families include information such as:

* Active Addresses
* Sending Addresses
* Receiving Addresses
* Transfer activity
* Exchange flows
* Market metrics
* Perpetual futures metrics

However, Glassnode explicitly notes that exchange-address labeling is continuously updated and some exchange-derived historical values may therefore change over time.

Consequently, these features require PIT classification before use in strict backtests.

⸻

Coin Metrics Network Data

Coin Metrics provides blockchain-network metrics including:

* Transaction counts
* Transfer values
* Contract activity
* Token activity
* Large-transfer metrics
* Network statistics

This makes it a strong candidate for standardized cross-chain historical features.

⸻

CryptoQuant

CryptoQuant provides extensive:

* Exchange flows
* Exchange reserves
* Market data
* Funding
* Open Interest
* Liquidations
* On-chain metrics

However, its documentation explicitly identifies some entity-derived datasets as not point-in-time accurate because wallet clustering can be updated retrospectively.

Therefore CryptoQuant should be treated as:

Potentially valuable research data

but not automatically:

Ground truth for strict historical prediction tests.

⸻

14. Blockchain Nodes

Running blockchain infrastructure should be evaluated separately for each network.

The project does not automatically require archive nodes for every blockchain.

An archive node is valuable when historical blockchain state must be queried repeatedly.

Ethereum documentation confirms that archive nodes retain historical states, while ordinary full nodes can regenerate older states but at significant computational cost.

BNB Chain similarly provides archive-node infrastructure specifically for historical-state access.

Therefore the decision:

Provider vs Own Node

must be based on:

* Query frequency
* Required historical depth
* Storage cost
* Infrastructure cost
* Reliability
* Data sovereignty
* Required latency

Running four heavy archive infrastructures simply because the data is public would be inefficient.

⸻

15. Canonical Timestamp Architecture

Every record must distinguish multiple timestamps where applicable.

Required timestamp concepts include:

event_time

When the event occurred.

exchange_time

Timestamp supplied by the exchange.

block_time

Blockchain timestamp.

provider_time

Timestamp supplied by a provider.

ingestion_time

When our system received the information.

database_time

When the information entered persistent storage.

This distinction is critical.

For live-trading reconstruction:

When information became available to the system

can be more important than:

When the underlying event technically occurred.

⸻

16. Canonical Data Schema

Every historical record should contain metadata including:

asset

venue

instrument

data_type

event_time

ingestion_time

source

source_version

quality_status

PIT_status

raw_reference

This creates traceability throughout the research pipeline.

⸻

17. Immutable Raw Layer

The Bronze layer must be append-oriented and effectively immutable.

Raw source information should not be silently modified after ingestion.

If a provider later changes historical data:

Old Version

and

New Version

should both remain traceable.

This is important because some providers explicitly revise historical archives.

⸻

18. Dataset Versioning

Every research dataset receives an immutable identifier.

Example:

HDE-BTCETHSOLBNB-2026-09-V001

The dataset manifest should contain:

* Creation date
* Assets
* Venues
* Sources
* Historical range
* Missing periods
* Quality issues
* Feature version
* PIT classifications
* Transformation version

A model must always reference the exact dataset on which it was trained.

⸻

19. Data Quality Scoring

Every dataset segment should receive a Data Quality Score.

Conceptually:

A — Excellent

Complete, validated, high-resolution.

B — Good

Minor gaps with reliable reconstruction.

C — Limited

Material limitations.

D — Research Only

Potential biases or incomplete history.

F — Invalid

Must not be used.

Models should be prevented from silently training across F-quality segments.

⸻

20. Gap Registry

Missing historical information must never be silently filled without documentation.

The system will maintain a:

Historical Gap Registry

Example:

Asset: SOL
Venue: X
Data: L2 Order Book
Start: T1
End: T2
Reason: Provider outage
Recovery: None
Quality: C

This prevents invisible corruption of experiments.

⸻

21. Cross-Source Validation

Critical market variables should be validated against secondary sources where possible.

Example:

BTC Price

Primary → Binance

Secondary → Coinbase / another reliable market source

Large disagreement triggers investigation.

Similarly:

Funding

Open Interest

Volume

Timestamp continuity

should be cross-checked where economically practical.

⸻

22. Historical Dataset Segmentation

The dataset should not be treated as one homogeneous period.

Crypto markets have undergone major structural changes.

Historical periods should eventually be classified into regimes including:

* Early market structure
* Bull markets
* Bear markets
* High-volatility crashes
* Low-volatility periods
* Deleveraging events
* Liquidity crises
* Post-exchange-failure environments
* ETF-era market structure
* High-institutional-participation periods

Models must be evaluated across multiple regimes.

⸻

23. Asset-Specific Historical Depth

The project must not force every asset to begin at the same date.

BTC has substantially more relevant historical history than SOL.

BNB and SOL also evolved through very different market structures.

Therefore:

Maximum Available History

does not automatically equal:

Maximum Useful Training History.

Very old market periods may have limited relevance to modern perpetual-futures trading.

Historical windows must ultimately be selected empirically.

⸻

24. Recency Weighting

The architecture must support models that assign different importance to historical periods.

Possible approaches include:

* Rolling training windows
* Exponential recency weighting
* Regime-specific training
* Adaptive windows

This prevents the model from assuming that cryptocurrency market structure is permanently stationary.

⸻

25. Historical Intelligence Levels

To control complexity, the dataset will be developed progressively.

Level 1

Price + Volume

Purpose:

Baseline strategies.

Level 2

Trades + Market Microstructure

Purpose:

Order-flow intelligence.

Level 3

Derivatives

Purpose:

Funding, OI and leverage-state intelligence.

Level 4

On-Chain

Purpose:

Capital-flow and network intelligence.

Level 5

Cross-Market

Purpose:

System-wide crypto regime intelligence.

Level 6

Execution Environment

Purpose:

Realistic trade simulation.

This structure allows us to measure whether each additional intelligence layer actually improves performance.

⸻

26. Ablation Testing Requirement

This is a mandatory research requirement.

The system must not assume that more data produces a better model.

Models will be compared using combinations such as:

Price Only

vs.

Price + Order Flow

vs.

Price + Derivatives

vs.

Price + On-Chain

vs.

Price + Order Flow + Derivatives

vs.

Full Intelligence Stack

If On-Chain data does not improve out-of-sample performance, it should not be retained simply because it sounds sophisticated.

Every major data family must justify its complexity.

⸻

27. Storage Strategy

Recommended architecture:

Object Storage

For:

* Immutable raw archives
* Provider files
* Blockchain extracts
* Dataset snapshots

ClickHouse

For:

* Tick trades
* L2 data
* High-frequency derivatives
* Large analytical time-series queries

PostgreSQL

For:

* Dataset registry
* Metadata
* Gap registry
* Source configuration
* Experiment references

Redis

For future real-time pipeline state.

The Historical Data Engine should not depend on Redis for durable history.

⸻

28. Continuous Recorder

Historical acquisition alone is insufficient.

From the earliest implementation stage, the project must operate its own continuous recorder.

The recorder should capture:

* Trades
* Order Book
* Quotes
* Funding
* Open Interest
* Mark prices
* Oracle/index prices
* Relevant exchange context
* Data arrival timestamps

for all four core assets.

The resulting dataset becomes increasingly valuable because:

we control its timestamp semantics, completeness monitoring, and version history.

⸻

29. Recorder Reliability

The recorder must support:

* Automatic reconnect
* Sequence validation
* Gap detection
* Backfill attempts
* Heartbeat monitoring
* Duplicate detection
* Clock synchronization
* Source failover
* Persistent buffering

A recorder that silently misses 20 minutes of market data is worse than one that explicitly reports a 20-minute gap.

⸻

30. No Synthetic Historical Truth

Missing raw data must not be casually interpolated.

For example:

Missing L2 Order Book information cannot simply be reconstructed from candles.

Synthetic reconstruction may be permitted for specific experiments but must be explicitly labeled:

SYNTHETIC

and must never be confused with observed market data.

⸻

31. Historical Leakage Firewall

Before any dataset reaches machine learning, an automated leakage-validation layer should test for:

* Future timestamps
* Future labels
* Revised historical entity classifications
* Forward-filled future values
* Incorrect rolling windows
* Target-derived features
* Post-trade information
* Dataset joins that reveal future observations

Any failure invalidates the corresponding experiment.

⸻

32. Expected Historical Scale

The storage requirement will vary dramatically by data class.

OHLCV is relatively small.

Tick trades are significantly larger.

Event-level L2 Order Book history can become extremely large.

Therefore the architecture must not treat every dataset identically.

Storage policy:

High predictive potential + difficult to reproduce → retain aggressively

Low predictive potential + easily reproducible → retain selectively

This policy will be refined after empirical feature-value testing.

⸻

33. Historical Data Engine Output

The engine should eventually be able to produce a query such as:

Asset: SOL
Historical Time: T
Decision Horizon: 15 minutes

and return only information legitimately available at that point:

Market State

Order Flow

Funding

Open Interest

On-Chain State

BTC Context

ETH Context

BNB Context

Volatility

Liquidity

Data Quality

Information Availability

This becomes the historical sensory input of the AI system.

⸻

34. Research Dataset Generation

The Historical Data Engine will generate controlled datasets for specific experiments.

Example:

Dataset

SOL-15M-V17

Target

Future 15-minute risk-adjusted return

Features

412

Period

Defined historical window

PIT

Verified

Missing Data

Documented

Quality

A/B only

Training

Defined historical subset

Validation

Future non-overlapping subset

This makes every AI experiment reproducible.

⸻

35. Data Provider Selection Policy

Providers will not be selected purely on the basis of cost.

Each source will be evaluated using:

1. Historical depth
2. Resolution
3. Completeness
4. Point-in-time integrity
5. Reliability
6. Timestamp quality
7. Market coverage
8. API/export capability
9. Revision policy
10. Licensing
11. Cost
12. Vendor dependence

No provider receives unconditional status as the single source of truth.

⸻

36. Initial Source Architecture

The current research supports the following architecture as a starting point:

Exchange-Native

Binance

Historical centralized market baseline.

Hyperliquid

Historical and live execution-venue intelligence.

Institutional Market Data

Coin Metrics and/or Kaiko

For deeper historical microstructure, derivatives and cross-venue validation.

On-Chain Intelligence

Glassnode and/or Coin Metrics Network Data

Primary research candidates.

Specialized Validation

CryptoQuant

Potential supplementary source, particularly for exchange-flow research, subject to PIT restrictions.

Blockchain Infrastructure

Own nodes or archive access introduced only where provider-independent historical state materially improves research.

This source architecture remains subject to commercial pricing, licensing and detailed coverage verification.

⸻

37. Critical Research Conclusion

The original concept of:

“Train the AI using the entire history of BTC, ETH, SOL and BNB.”

is directionally strong but technically incomplete.

The correct formulation is:

Train and validate models using the maximum useful, reliable, point-in-time-correct historical representation of BTC, ETH, SOL and BNB market behavior.

More historical data is not automatically better.

More features are not automatically better.

More blockchain data is not automatically better.

The objective is:

Maximum Information Quality

not:

Maximum Data Volume

⸻

38. Phase 3 Acceptance Gate

Phase 3 must not be considered complete until the implementation can demonstrate:

* Historical BTC ingestion
* Historical ETH ingestion
* Historical SOL ingestion
* Historical BNB ingestion
* Trade history
* Derivatives history
* Historical timestamp normalization
* Raw immutable storage
* Dataset versioning
* Data Quality scoring
* Gap Registry
* PIT classification
* Cross-source validation
* Continuous recorder
* Leakage checks
* Reproducible dataset generation

In addition, at least one research dataset for each core asset must be reproducibly generated from the Historical Data Engine.

⸻

39. Phase 3 Deliverables

The implementation phase must produce:

Historical Data Collector

Historical Data Lake

Continuous Market Recorder

Normalization Engine

Data Quality Engine

Historical Gap Registry

PIT Classification System

Dataset Versioning System

Leakage Firewall

Research Dataset Generator

Data Source Registry

⸻

40. Final Architecture

The Historical Data Engine architecture is:

Exchange History

Blockchain History

Institutional Market Data

Our Continuous Recorder

↓

Immutable Raw Data Lake

↓

Integrity Verification

↓

Timestamp Normalization

↓

Point-in-Time Classification

↓

Quality Engine

↓

Canonical Historical Store

↓

Feature Generation

↓

Versioned Research Datasets

↓

Backtesting / ML / Market Regime Research

⸻

41. Strategic Principle

The Historical Data Engine is not merely infrastructure.

It becomes one of the principal long-term assets of the project.

As the system operates, it will accumulate information that external providers cannot fully reproduce:

* Exact data arrival times
* Internal features
* Model predictions
* Model confidence
* Strategy decisions
* Rejected trades
* Risk Engine decisions
* Actual fills
* Slippage
* Execution latency
* Position outcomes

Eventually, the AI will be able to learn not only from:

the history of the market

but also from:

the history of its own decisions.

⸻

Phase 3 Decision

APPROVED FOR IMPLEMENTATION DESIGN

with one important qualification:

Historical provider contracts, exact coverage windows, pricing, licensing, and point-in-time characteristics must be verified before final procurement.

No model training should begin before the Historical Data Engine can guarantee dataset lineage and point-in-time integrity.

⸻

Document: Historical Data Engine Specification
Version: 1.0
Phase: 3
Core Assets: BTC / ETH / SOL / BNB
Next Phase: Research & Backtesting Laboratory