Data Research & Architecture Specification

Version: 1.0
Phase: 2 — Data Research & Architecture
Core Markets: BTC, ETH, SOL, BNB
Document Status: Initial Data Architecture Specification
Previous Document: Master Product & Risk Specification v1.0

⸻

1. Purpose

The purpose of Phase 2 is to establish the data foundation required for the AI trading system.

The quality of the trading intelligence is fundamentally constrained by the quality, completeness, timing accuracy, and structure of the data available to it.

The system must therefore be designed around a multi-source, point-in-time-correct data architecture rather than relying exclusively on price charts or conventional technical indicators.

The core data pipeline is:

Data Acquisition → Raw Storage → Quality Validation → Normalization → Feature Engineering → Feature Store → Historical Intelligence → Research / AI

⸻

2. Core Market Universe

The primary data infrastructure will initially focus exclusively on:

* Bitcoin — BTC
* Ethereum — ETH
* Solana — SOL
* BNB — BNB

Data collection, historical reconstruction, feature engineering, and model development will prioritize these four assets.

Each asset may ultimately have its own data sources, feature sets, models, and strategy parameters.

⸻

3. Data Architecture Principles

The data platform will follow several mandatory principles.

3.1 Raw Data Preservation

Original market and blockchain data must be retained whenever economically and technically practical.

Raw historical data must not be overwritten by transformed datasets.

3.2 Point-in-Time Correctness

Historical research must only expose information that would genuinely have been available at the corresponding historical moment.

Future information must never leak into historical model inputs.

3.3 Multi-Source Intelligence

No single data provider will be assumed to contain all information required by the system.

The architecture must support multiple market, derivatives, blockchain, and analytical sources.

3.4 Reproducibility

Any derived feature or model dataset should be reproducible from preserved source data whenever practical.

3.5 Data Quality Before Prediction

If critical market information is stale, inconsistent, corrupted, or unavailable, the trading system must be capable of refusing to generate or execute a trade.

⸻

4. Data Intelligence Layers

The system will initially organize information into six primary intelligence layers.

4.1 Market Data

Market data represents the fundamental trading activity of each asset.

Required categories include:

* OHLCV
* Trade-level data
* Bid price
* Ask price
* Spread
* Trading volume
* Market depth
* Mid price
* Mark price where applicable
* Reference/index/oracle prices where applicable

Historical and real-time data should be retained at sufficient resolution to support both research and live execution.

⸻

4.2 Order Flow and Market Microstructure

The system should collect market microstructure data whenever reliable historical and real-time sources are available.

Potential inputs include:

* Level 2 Order Book
* Bid depth
* Ask depth
* Order Book Imbalance
* Aggressive Buy Volume
* Aggressive Sell Volume
* Trade intensity
* Spread behavior
* Liquidity concentration
* Liquidity gaps
* Short-term price impact
* Order Book changes
* Market-order pressure

Microstructure information may be particularly valuable for short-horizon trade timing and execution decisions.

⸻

4.3 Derivatives Intelligence

Because the primary trading instrument is perpetual futures, derivatives data is considered a core component of the intelligence system.

Required categories include:

* Funding Rate
* Open Interest
* Open Interest Change
* Mark Price
* Index or Oracle Price
* Perpetual Basis
* Funding acceleration
* Positioning proxies
* Liquidation information where reliable
* Derivatives volume
* Volatility-related derivatives features where available

Price movement without derivatives context may provide an incomplete representation of market conditions.

⸻

4.4 On-Chain Intelligence

Blockchain activity will form a separate intelligence layer.

Potential features include:

* Transaction activity
* Network activity
* Active addresses
* Large transactions
* Exchange inflows
* Exchange outflows
* Stablecoin flows
* DEX activity
* Wallet behavior
* Concentration changes
* Large-holder activity
* Network fees
* Bridge activity where relevant
* Capital movement between ecosystems

On-chain processing will be asset-specific because Bitcoin, Ethereum, Solana, and BNB operate on different blockchain architectures.

⸻

4.5 Cross-Market Intelligence

BTC, ETH, SOL, and BNB must not be modeled as completely independent markets.

The system should measure relationships including:

* Rolling correlations
* Relative strength
* Lead/lag relationships
* Volatility transmission
* BTC-driven market regimes
* ETH/BTC behavior
* SOL/BTC behavior
* BNB/BTC behavior
* Relative volume
* Relative momentum
* Cross-market divergence

The purpose of this layer is to allow the system to understand the broader crypto market state rather than analyzing each asset in isolation.

⸻

4.6 Derived Features

Raw information will be transformed into research-ready and model-ready features.

Potential feature families include:

Trend

* Moving-average structures
* Trend strength
* Price distance from trend
* Multi-timeframe trend alignment

Momentum

* Returns
* Rate of Change
* Relative momentum
* Momentum acceleration

Volatility

* ATR
* Realized volatility
* Volatility expansion
* Volatility compression
* Intraday range

Order Flow

* Order Book Imbalance
* Buy/Sell pressure
* Depth imbalance
* Trade imbalance
* Liquidity changes

Derivatives

* Funding level
* Funding acceleration
* Open Interest change
* Price/OI divergence
* Basis behavior

On-Chain

* Exchange netflows
* Large-wallet flows
* Stablecoin movement
* Network activity changes

Cross-Market

* Rolling correlation
* Relative strength
* BTC sensitivity
* Volatility spillover

Every derived feature must have a defined calculation methodology and timestamp policy.

⸻

5. Historical Intelligence Engine

The Historical Intelligence Engine will combine two major historical domains.

Market History

* Price
* Volume
* Trades
* Order Book
* Funding
* Open Interest
* Derivatives activity

Blockchain History

* Transactions
* Capital flows
* Wallet behavior
* Network activity
* On-chain market structure

These datasets will be synchronized into a unified historical research environment.

Conceptually:

Market History + Blockchain History → Unified Historical Dataset → Historical Intelligence Engine

⸻

6. Blockchain Processing Strategy

The system will not simply feed complete raw blockchains directly into machine-learning models.

Instead, blockchain information will pass through dedicated processing infrastructure.

The architecture will follow:

Raw Blockchain Data

↓

Blockchain Processor

↓

On-Chain Features

↓

Feature Store

↓

Research / AI

This approach reduces noise, computational requirements, storage pressure, and unnecessary model complexity.

Raw blockchain data should still be preserved or reproducibly accessible where practical.

⸻

7. Real-Time Data Recorder

The platform must operate its own continuous data-recording infrastructure.

Dependence exclusively on third-party historical archives creates risks including:

* Missing data
* Limited retention
* Changed schemas
* Provider outages
* Historical depth restrictions
* Expensive future retrieval
* Loss of high-frequency information

The live architecture should therefore include:

Exchange / Blockchain / Data Streams

↓

Real-Time Collectors

↓

Immutable Raw Storage

↓

Normalization

↓

Feature Engine

↓

Feature Store

↓

Research and Live Trading Systems

Data recording should begin as early as possible in the project lifecycle.

The proprietary dataset created over time should be treated as a strategic project asset.

⸻

8. Data Storage Architecture

The data platform will use a multi-tier storage model.

8.1 Bronze Layer — Raw

Contains original source data with minimal transformation.

Examples:

* Exchange messages
* Raw trades
* Order Book snapshots
* Blockchain events
* Funding records
* Open Interest observations

Raw data should generally be immutable.

⸻

8.2 Silver Layer — Normalized

Contains standardized information.

Normalization includes:

* Timestamp alignment
* Asset identifiers
* Units
* Decimal precision
* Schema standardization
* Duplicate removal
* Source identifiers

This layer creates a consistent representation across providers.

⸻

8.3 Gold Layer — Features

Contains model-ready and research-ready information.

Example record:

Asset: SOL
Timestamp: T

Potential fields:

* Price
* Volume
* Spread
* Bid depth
* Ask depth
* Order Book Imbalance
* Funding
* Open Interest
* Realized Volatility
* On-chain netflow
* Large transaction volume
* Momentum
* Cross-market correlation
* Market regime

The Gold layer becomes the primary input for research, backtesting, and machine-learning pipelines.

⸻

9. Time Resolution

The system must operate across multiple temporal resolutions.

Initial architecture:

Event-Level Data
Trades and Order Book events

1 Minute
Microstructure and very short-term market behavior

5 Minutes
Short-horizon trading intelligence

15 Minutes
Tactical market structure

1 Hour
Intermediate trend

4 Hours
Major market trend

1 Day
Longer-term market regime

Models and strategies may combine information across multiple horizons.

For example, a short-term SOL Long signal may be interpreted differently depending on whether the 4-hour market structure is bullish or bearish.

⸻

10. Proposed Storage Technologies

The initial infrastructure should separate storage responsibilities according to workload.

Object Storage

Primary purpose:

* Raw historical archives
* Large immutable datasets
* Backups
* Research snapshots

ClickHouse

Primary purpose:

* High-frequency trades
* Order Book data
* Analytical queries
* Large time-series datasets
* Historical feature analysis

PostgreSQL

Primary purpose:

* Users
* Strategies
* Positions
* Orders
* Configuration
* Risk policies
* System metadata

Redis

Primary purpose:

* Live state
* Cache
* Short-lived market information
* Real-time coordination
* Fast risk and execution state

Feature Store

Primary purpose:

* Versioned ML features
* Training datasets
* Live feature retrieval
* Research reproducibility
* Training/serving consistency

The final implementation should remain subject to benchmark testing before production deployment.

⸻

11. Data Quality Engine

Data quality validation is a mandatory component of the architecture.

The Data Quality Engine should detect conditions including:

* Missing observations
* Timestamp gaps
* Duplicate events
* Stale feeds
* Impossible values
* Outliers
* Clock drift
* Incorrect event ordering
* Cross-source disagreement
* Schema changes
* Unexpected zero values
* Abnormal price discontinuities
* Corrupted records

Critical failures must be capable of propagating into the trading system.

The required behavior is:

Data Quality Failure → Trading Restriction → NO TRADE / SAFE MODE

The system must not blindly generate trades from unreliable information.

⸻

12. Point-in-Time Correctness

Point-in-time correctness is mandatory for all historical research.

When reconstructing a historical trading decision at time T, the system may only access information that was genuinely available at or before time T.

This requirement applies to:

* Market data
* Blockchain data
* Provider calculations
* Labels
* Derived features
* Funding information
* Open Interest
* Wallet classifications
* Cross-market information

Information calculated or classified after time T must not silently appear in historical model inputs.

This principle is one of the primary defenses against look-ahead bias and unrealistic historical performance.

⸻

13. Data Lineage

Every important feature should be traceable to its origin.

The system should retain metadata describing:

* Data source
* Original timestamp
* Ingestion timestamp
* Transformation version
* Feature calculation version
* Data quality status
* Dataset version

This enables historical decisions and model training datasets to be reconstructed and audited.

⸻

14. Dataset Versioning

Training datasets must be versioned.

A model should never be described simply as being trained on “BTC data.”

Instead, the system should be able to identify:

Dataset Version

Feature Version

Training Window

Validation Window

Source Version

Model Version

This creates reproducibility across experiments.

⸻

15. Separation of Research and Live Data

Research and production pipelines must remain logically separated while sharing compatible schemas.

Research Pipeline

Optimized for:

* Historical queries
* Feature experimentation
* Model training
* Backtesting
* Statistical analysis

Live Pipeline

Optimized for:

* Low latency
* Current market state
* Risk calculation
* Signal generation
* Execution

The same feature definition should produce equivalent results in historical and live environments wherever possible.

This reduces training-serving skew.

⸻

16. Initial Data Architecture

The resulting architecture is:

BTC / ETH / SOL / BNB

↓

Market Data + Derivatives Data + On-Chain Data

↓

Raw Data Lake

↓

Data Quality Engine

↓

Normalization Layer

↓

Feature Engine

↓

Feature Store

↓

Historical Intelligence Engine

↓

Research / Backtesting / AI

↓

Live Signal Engine

↓

Risk Engine

↓

Execution Engine

⸻

17. Strategic Data Asset

The project’s continuously accumulated dataset should be treated as a core intellectual and technical asset.

Over time, the platform should accumulate proprietary synchronized histories of:

* Market microstructure
* Derivatives activity
* On-chain behavior
* Cross-market relationships
* Generated features
* AI predictions
* Trading decisions
* Orders
* Fills
* Slippage
* Strategy outcomes

This will enable future models to learn not only from market history but also from the system’s own historical decisions and execution behavior.

⸻

18. Phase 2 Acceptance Requirements

The Data Architecture phase will be considered technically ready for implementation when:

* The four-asset universe is represented consistently.
* Required data categories are defined.
* Historical and live pipelines are separated.
* Raw data preservation is defined.
* Point-in-time correctness is enforced.
* Data quality controls are specified.
* Dataset versioning is defined.
* Feature lineage is defined.
* Real-time recording architecture is established.
* Storage responsibilities are assigned.
* Training and live feature consistency is addressed.

⸻

19. Remaining Phase 2 Research

The architecture defined in this document establishes what information the system requires and how that information will be managed.

A separate Data Source Matrix must determine where each dataset will originate.

For each of BTC, ETH, SOL, and BNB, the next research stage must evaluate:

* Price source
* Trade source
* Order Book source
* Funding source
* Open Interest source
* Liquidation source
* Blockchain historical source
* Real-time blockchain source
* Exchange-flow source
* Wallet-intelligence source
* Historical depth
* Resolution
* API limitations
* Latency
* Reliability
* Cost
* Licensing
* Point-in-time availability
* Redundancy requirements

No provider should be selected solely because it exposes a convenient API.

Selection must prioritize:

Accuracy → Historical Depth → Point-in-Time Integrity → Reliability → Resolution → Latency → Cost

⸻

Phase 2 Output

The resulting data foundation is defined as:

A multi-source, point-in-time-correct, continuously recorded historical and real-time intelligence infrastructure for BTC, ETH, SOL, and BNB, combining market, derivatives, blockchain, microstructure, and cross-market information into reproducible model-ready datasets.

This infrastructure will form the foundation of the Historical Intelligence Engine, Research Laboratory, AI models, Risk Engine, and live trading system.

⸻

Document: Data Research & Architecture Specification
Version: 1.0
Phase: 2
Status: Architecture Defined — Data Source Selection Pending
Next Deliverable: Data Source Matrix & Provider Research