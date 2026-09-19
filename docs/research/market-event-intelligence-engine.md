# MEIE v1 — Market Event Intelligence Engine

**Status:** High-Priority Experimental Candidate · **Production authority:** None
**Build 0.1 critical path:** No — but it constrains recorder, clock and schema design

Architecture and engineering specification for integration into the trading
research platform, stored as delivered. Section numbering is the source
document's and is cited as `§n` elsewhere in this repository.

Two things this project has already measured bear directly on it, and are set
out in [What this project has already measured](#what-this-project-has-already-measured)
at the end rather than silently edited into the text above. The specification is
kept as written; the measurements are kept as findings.

---

Architecture & Engineering Specification for Integration
into the Trading Research Platform

## 1. Mission

Build a research-grade Market Event Intelligence Engine (MEIE) capable of detecting, normalizing,
understanding, timestamping, and evaluating market-moving information and determining whether an
event still contains executable trading information after latency, fees, slippage, and market reaction.
MEIE must not be implemented as a simple:
 News → Sentiment → LONG / SHORT
system.
The target architecture is:
```
 Information
      ↓
Event Detection
      ↓
Event Normalization
      ↓
Event Understanding
      ↓
Reliability / Novelty / Surprise
      ↓
Market Reaction Measurement
      ↓
Information Decay
      ↓
Remaining Edge Estimation
      ↓
Event × Market-State Model
      ↓
Signal Fusion
      ↓
Independent Risk Kernel
      ↓
LONG / SHORT / NO TRADE
```
The core research question is not:
Is this news bullish or bearish?
It is:
Given this event, the current market state, observed reaction, information age, execution latency, fees
and slippage, does statistically defensible executable edge remain?
NO TRADE is a first-class outcome.

## 2. Core Design Principles

MEIE must obey the following principles.

### 2.1. Events are data, not orders

No article, tweet, regulatory announcement, macroeconomic release, LLM output, sentiment score, or
external vendor signal may directly generate an executable order.
All information must pass through:
 Event Layer
→ Evidence Layer
→ Market Reaction Layer
→ Edge Model

→ Signal Fusion
→ Risk Kernel
→ Execution

### 2.2. Risk remains independent

MEIE cannot override the Risk Kernel.
MEIE proposes.
Risk Kernel disposes.
The Risk Kernel has final authority over:
- position permission
- position size
- leverage
- exposure
- stop conditions
- kill switches
- volatility limits
- liquidity constraints
- execution permission

### 2.3. Raw-first storage

Every source payload must be preserved before transformation.
Never store only the AI interpretation.
```
 RAW SOURCE
    ↓
Immutable storage
    ↓
Normalized event
    ↓
Features
    ↓
Models
```
This allows future replay when parsers or models change.

### 2.4. Point-in-time correctness

Historical research must use only information available at that exact historical timestamp.
No:
- revised economic data
- corrected articles unavailable at T0
- future labels
- later consensus values
- hindsight event classifications
may leak into historical features.

### 2.5. Latency is part of the signal

A signal that exists at T+100 ms but cannot be executed until T+2 s is not executable alpha.
Latency must therefore be modeled explicitly.
```
3. MEIE Architecture
                     ┌───────────────────────┐
                    │ INFORMATION SOURCES   │
                    └───────────┬───────────┘
                                │
       ┌────────────────────────┼───────────────────────┐
       │                        │                       │
```

 Scheduled Macro        Breaking Information     Crypto-Native
```
       │                        │                       │
       └────────────────────────┼───────────────────────┘
                                ↓
                    ┌───────────────────────┐
                    │ INGESTION LAYER       │
                    └───────────┬───────────┘
                                ↓
                    ┌───────────────────────┐
                    │ RAW EVENT STORE       │
                    └───────────┬───────────┘
                                ↓
                    ┌───────────────────────┐
                    │ DEDUP / CLUSTERING    │
                    └───────────┬───────────┘
                                ↓
                    ┌───────────────────────┐
                    │ EVENT UNDERSTANDING   │
                    └───────────┬───────────┘
                                ↓
             ┌──────────────────┼───────────────────┐
             │                  │                   │
        Reliability         Novelty             Surprise
             │                  │                   │
             └──────────────────┼───────────────────┘
                                ↓
                    ┌───────────────────────┐
                    │ EVENT OBJECT          │
                    └───────────┬───────────┘
                                ↓
                    ┌───────────────────────┐
                    │ MARKET REACTION       │
                    └───────────┬───────────┘
                                ↓
                    ┌───────────────────────┐
                    │ INFORMATION DECAY     │
                    └───────────┬───────────┘
                                ↓
                    ┌───────────────────────┐
                    │ REMAINING EDGE MODEL  │
                    └───────────┬───────────┘
                                ↓
                    ┌───────────────────────┐
                    │ SIGNAL FUSION         │
                    └───────────┬───────────┘
                                ↓
                    ┌───────────────────────┐
                    │ RISK KERNEL           │
                    └───────────┬───────────┘
                                ↓
                    LONG / SHORT / NO TRADE
```

## 4. Source Hierarchy

Sources must not be treated equally.
Tier 0: Primary / Authoritative Sources
Highest priority.
Examples:
- Federal Reserve
- BLS
- SEC
- CFTC
- government agencies
- court publications
- exchange announcements

- exchange status feeds
- protocol foundations
- official project communications
- issuer announcements
These should receive the highest initial reliability prior.
Whenever technically possible, use:
API
RSS
WebSocket
official structured feed
instead of web scraping.

## 5. Tier 1: Professional Machine-Readable News

Potential providers include professional financial news/event feeds.
The ingestion interface must be provider-independent.
Normalized fields should support:
source
headline
body
timestamp
entities
topics
relevance
sentiment
novelty
urgency
provider_event_id
The architecture must allow providers to be replaced without changing downstream research
components.

## 6. Tier 2: Crypto-Specialist Sources

Capture:
- exchange events
- protocol incidents
- hacks
- exploits
- token listings
- delistings
- ETF developments
- stablecoin events
- network failures
- regulatory developments
- institutional activity
- custody developments
- major protocol upgrades
These sources supplement authoritative feeds.

They must never automatically inherit high reliability.

## 7. Tier 3: Social / Narrative Sources

Potential inputs:
- X
- Reddit
- Telegram
- public communities
- public developer channels
Their primary purpose is:
Early Detection
Narrative Birth
Narrative Velocity
Attention Spike
Rumor Detection
Crowd Disagreement
Information Propagation
Social information must not be interpreted as confirmed fact without independent confirmation.

## 8. Scheduled Event Engine

Scheduled macroeconomic releases require a dedicated path.
Examples:
CPI
Core CPI
PPI
PCE
NFP
Unemployment
GDP
FOMC
Interest-rate decisions
Fed projections
Retail sales
PMI
Jobless claims
For every scheduled event store:
event_name
scheduled_timestamp
country
importance
previous
consensus
forecast_distribution
actual
revision
source
Calculate at minimum:
raw_surprise = actual - consensus

and preferably:
standardized_surprise =
(actual - consensus) /
historical_surprise_std
Do not rely on LLM interpretation when a deterministic numeric surprise is available.

## 9. Event Taxonomy

Create a versioned taxonomy.
Initial top-level classes:
MACRO
MONETARY_POLICY
REGULATION
LEGAL
ETF
SECURITY_BREACH
EXPLOIT
EXCHANGE
PROTOCOL
NETWORK
STABLECOIN
INSTITUTIONAL
LIQUIDITY
MARKET_STRUCTURE
LISTING
DELISTING
TOKENOMICS
GEOPOLITICAL
CORPORATE
MINING
CUSTODY
SYSTEMIC_RISK
RUMOR
OTHER
Each category may contain subtypes.
Example:
```
 SECURITY_BREACH
 ├── Exchange Hack
 ├── Bridge Exploit
 ├── Smart Contract Exploit
 ├── Key Compromise
 ├── Oracle Attack
 └── Unknown Security Incident
```
Taxonomy versions must be stored with every classification.

## 10. Event Object

Every detected event should eventually become a normalized object.
Example schema:
event_id

source_event_id
source
source_tier
source_reliability
source_timestamp
first_seen_timestamp
ingestion_timestamp
normalization_timestamp
classification_timestamp
headline
raw_reference
event_type
event_subtype
taxonomy_version
entities[]
affected_assets[]
scheduled
expected
actual
raw_surprise
standardized_surprise
sentiment
expected_direction
expected_magnitude
expected_horizon
novelty
relevance
confidence
urgency
cross_source_confirmation_count
contradiction_score
rumor_probability
information_age_ms
market_snapshot_reference
model_version
parser_version
Never overwrite historical event objects silently.
Updates should be versioned.

## 11. Deduplication and Event Clustering

One real-world event may generate hundreds of articles.
The system must not interpret them as hundreds of independent signals.
Build an Event Clustering Engine using:
semantic similarity
entity overlap
temporal proximity
topic similarity

source relationships
headline similarity
event identifiers
Transform:
Reuters story
Exchange announcement
CoinDesk article

## 50. reposts

2,000 tweets
into:
ONE EVENT CLUSTER
with multiple evidence objects.
This prevents artificial confidence inflation.

## 12. Novelty Engine

Novelty is critical.
The system must distinguish:
NEW INFORMATION
UPDATE
CONFIRMATION
REPETITION
COMMENTARY
ANALYSIS
OLD INFORMATION
A repeated headline should not regenerate alpha.
Possible output:
 novelty_score = 0.00 → 1.00
Example:
First credible hack report 0.97
Second independent confirmation 0.72
Reuters confirmation 0.61
20th repost 0.03
Opinion article 30 min later 0.01
These values are illustrative, not hard-coded trading thresholds.
They must ultimately be calibrated empirically.

## 13. Reliability Engine

Reliability should incorporate:
source prior
primary-source status
historical accuracy
cross-source confirmation
source independence
contradictions

corrections
rumor indicators
entity authenticity
Important:
Five websites repeating one original rumor are not five independent confirmations.
The engine must model source lineage where possible.

## 14. Event Understanding Layer

Use a hybrid system:
Deterministic extraction
+
Financial NLP
+
LLM structured reasoning
+
Statistical models
The LLM may extract:
event_type
entities
affected_assets
expected_direction
expected_horizon
causal mechanism
uncertainty
conditions
contradictions
LLM output must be structured and schema-validated.
The LLM must never return an executable command such as:
BUY BTC
SELL BTC
as an authoritative trading action.

## 15. Market Reaction Engine

Immediately after an Event Object is created, attach synchronized market state.
For BTC MVP:
BTC price
returns
trade flow
L2 order book
spread
depth
order-book imbalance
volume
realized volatility
open interest
funding

liquidations
basis
mark/index divergence
Where available, add cross-market information:
ETH
Nasdaq futures
S&P futures
DXY
Treasury yields
Gold
For each event measure reactions at multiple horizons:

## 100. ms

## 250. ms

## 500. ms

## 1. s

## 2. s

## 5. s

## 10. s

## 30. s

## 1. min

## 5. min

## 15. min

## 30. min

## 1. h

## 4. h

## 24. h

Use only horizons supported by timestamp precision and dataset quality.

## 16. Already-Priced-In Model

A critical model must estimate how much of the expected reaction has already occurred before execution
becomes possible.
Conceptually:
```
 Expected Event Impact
        ↓
Observed Reaction
        ↓
Expected Remaining Move
```
Do not blindly calculate:
remaining = expected - observed
because market response is nonlinear.
Instead train/calibrate conditional models using historical event classes and market regimes.
Output:
reaction_consumed_probability
remaining_edge_estimate
remaining_edge_confidence

## 17. Information Decay Engine

Every event class may have a different information half-life.
Conceptually:
```
 Edge
│\
│ \
│  \
│   \__
│      \____
└────────────── Time
Estimate empirically:
```
E[alpha | event_type, market_state, time_since_event]
Do not hard-code universal decay constants.
Possible conditioning variables:
event_type
event_magnitude
novelty
source_quality
market_regime
volatility
liquidity
time_of_day
initial reaction
cross-venue reaction

## 18. Reaction Divergence

Explicitly model the difference between:
Expected reaction
and:
Observed reaction
Example:
Very bearish event
+
BTC refuses to decline
+
selling pressure fades
+
OI falls
+
liquidity remains strong
This may contain more information than the original negative headline.
Create features such as:
expected_direction
observed_direction
direction_agreement
expected_magnitude
observed_magnitude
reaction_gap
reaction_resilience
reaction_reversal

This is a research feature, not an assumed profitable rule.

## 19. Event × Market-State Model

The primary alpha hypothesis should be:
 EVENT
×
MARKET STATE
rather than:
 EVENT
→ PRICE
Market-state features may include:
volatility regime
trend regime
liquidity regime
spread
depth
order flow
funding
OI
liquidation state
basis
positioning
recent returns
market concentration
cross-asset state
TBIE state
Example:
Negative regulation news
+
extremely short positioning
+
large OI
+
little downside reaction
+
aggressive selling exhausted
may behave differently from the same news during neutral positioning.
The model must learn this from data rather than encode narrative assumptions.

## 20. TBIE Integration

MEIE and Trader Behavior Intelligence must remain independent signal families.
Then create interaction features:
 event_type × wallet_cluster_behavior
event_direction × informed_trader_response
event_timestamp × whale_flow
news_reaction × trader_reaction
Research question:
Do historically informative traders react to an event before or differently from the general market?

Do not assume that they do.
Validate it.

## 21. Remaining Edge Model

This should become one of MEIE's central outputs.
Conceptually:
 Remaining Edge =
f(
    event,
    novelty,
    reliability,
    surprise,
    market reaction,
    information age,
    market state,
    TBIE,
    expected execution cost,
    latency
)
Outputs should include:
expected_return
expected_adverse_excursion
expected_favorable_excursion
confidence
expected_horizon
edge_after_cost
Prefer distributions over point estimates.
Example:
 Expected return:
P10   -0.42%
P50   +0.18%
P90   +0.73%
Expected execution cost:
0.06%
Risk-adjusted remaining edge:
insufficient
RESULT:
NO TRADE

## 22. Counterfactual Event Analysis

Research should estimate:
What would likely have happened if this event had not occurred?
Match events against comparable periods using:
time of day
volatility
trend
liquidity
funding
OI
recent return

macro regime
market regime
Then estimate:
Observed Move
-
Expected Counterfactual Move
=
Estimated Event Impact
Potential methodologies:
event studies
matched controls
local projections
synthetic controls
causal ML
Use causal language only where methodology supports it.

## 23. Latency Instrumentation

Record the full event-to-fill chain.
 T0 = source publication timestamp
T1 = upstream provider receipt
T2 = local ingestion
T3 = parsing complete
T4 = event classification complete
T5 = market snapshot complete
T6 = feature generation complete
T7 = signal generation
T8 = risk approval
T9 = order submission
T10 = exchange acknowledgement
T11 = fill
Persist every available timestamp.
Compute:
 source → ingestion
ingestion → understanding
understanding → signal
signal → risk
risk → send
send → ack
ack → fill
total source → fill

## 24. Synthetic Latency Ladder

Every candidate strategy must be replayed under:

## 0. ms

## 50. ms

## 100. ms

## 250. ms

## 500. ms

## 1. s

## 2. s

## 5. s

## 10. s

## 30. s

Potentially extend for slower event classes.
A strategy that disappears under realistic latency fails.

## 25. Historical Research Dataset

Create a point-in-time event dataset.
Minimum structure:
event_id
event_timestamp
source
source_tier
event_type
event_subtype
entities
assets
novelty
reliability
sentiment
surprise
magnitude
horizon
BTC_at_event
BTC_100ms
BTC_250ms
BTC_500ms
BTC_1s
BTC_2s
BTC_5s
BTC_10s
BTC_30s
BTC_1m
BTC_5m
BTC_15m
BTC_30m
BTC_1h
BTC_4h
BTC_24h
volume_change
spread_change
depth_change
orderflow_change
OI_change
funding_change
liquidations
MFE
MAE
market_regime
TBIE_state

raw_payload_reference
Never fabricate unavailable historical precision.

## 26. Research Methodology

MEIE must use the same research discipline as the main trading system.
Required:
point-in-time data
walk-forward evaluation
purged cross-validation
embargo
strict train/test separation
transaction costs
slippage
latency
execution realism
multiple-testing controls
Deflated Sharpe where applicable
PBO where applicable
experiment registry
reproducibility
Every experiment should store:
experiment_id
dataset_version
feature_version
taxonomy_version
model_version
code_commit
parameters
training_period
validation_period
test_period
cost assumptions
latency assumptions
results

## 27. Leakage Prevention

Explicitly test for:
future article updates
economic revisions
future consensus values
later source confirmation
future classifications
market prices after decision timestamp
future wallet information
future event labels
duplicate stories crossing folds
Event clusters must remain in the same train/test partition where necessary to prevent duplicate-event
leakage.

## 28. Execution Reality

Backtests must incorporate:
fees
spread
slippage
book depth
order size
market impact
latency
partial fills
rejected orders
cancel latency
exchange downtime
MEIE alpha is valid only if it survives execution reality.

## 29. Signal Fusion

MEIE must not dominate the entire trading system.
Potential signal families:
Price / Market Structure
Order Book
Derivatives
TBIE
On-chain
MEIE
Cross-asset / Macro
Signal Fusion should receive standardized outputs.
Example:
MEIE:
direction = bearish
edge_after_cost = 0.21%
confidence = 0.73
Order Flow:
bearish
confidence = 0.82
TBIE:
neutral
Derivatives:
short crowding elevated
Liquidity:
poor
Risk:
event volatility extreme
The result may still be:
NO TRADE

## 30. Risk-Only Mode

MEIE must support a mode where it cannot create positions but can reduce risk.
Example actions:
block new entries
reduce maximum leverage
reduce position limits
widen required edge threshold
cancel passive orders
enter event-risk mode
temporarily halt execution
Examples:
CPI in 2 minutes
FOMC imminent
major exchange outage
confirmed protocol exploit
unexpected geopolitical shock
This capability may prove valuable even if event-driven alpha fails.

## 31. MEIE Operating States

Define explicit states:
NORMAL
SCHEDULED_EVENT_APPROACHING
BREAKING_EVENT
EVENT_VOLATILITY
SOURCE_CONFLICT
RUMOR
DATA_DEGRADED
NEWS_FEED_DEGRADED
EVENT_COOLDOWN
The Risk Kernel may apply different policies to each state.

## 32. Failure Modes

Design explicitly for:
fake news
hacked social accounts
duplicate articles
incorrect timestamps
provider delays
article corrections
LLM hallucinations
ambiguous entities
satire
rumors
old stories resurfacing
scheduled-release revisions
feed outages
contradictory sources
clock drift

API throttling
network partitions
Fail safe.
When confidence in information infrastructure is low:
NO TRADE
or:
RISK-ONLY MODE

## 33. Observability

Expose metrics including:
events/sec
source latency
source availability
duplicate rate
event clustering rate
classification latency
LLM latency
classification disagreement
source conflicts
rumor rate
event-to-signal latency
event-to-fill latency
remaining-edge distribution
trades by event type
PnL by event type
PnL after costs
false-event rate

## 34. Kill Switches

MEIE-specific kill switches:
source timestamp corruption
clock synchronization failure
feed latency above threshold
abnormal duplicate explosion
classification failure rate
provider outage
market data mismatch
risk service unavailable
execution state uncertain
A news signal must never bypass an unavailable Risk Kernel.

## 35. Development Sequence

Do not jump directly to automated news trading.
Recommended milestones:
 MEIE-M0

Architecture / schemas / interfaces
MEIE-M1
Raw source recorder
MEIE-M2
Scheduled macro recorder
MEIE-M3
Breaking-news ingestion
MEIE-M4
Deduplication + event clustering
MEIE-M5
Event taxonomy + structured extraction
MEIE-M6
Reliability + novelty
MEIE-M7
Market synchronization
MEIE-M8
Historical event dataset
MEIE-M9
Event study framework
MEIE-M10
Information decay analysis
MEIE-M11
Market-state conditioning
MEIE-M12
Remaining-edge model
MEIE-M13
TBIE interaction research
MEIE-M14
Execution-aware backtesting
MEIE-M15
Risk-only integration
MEIE-M16
Testnet signal integration
MEIE-M17
Paper trading
MEIE-M18
Shadow mode
No milestone should be skipped merely because later functionality can be coded.

## 36. Acceptance Gates

MEIE must produce one of four research outcomes.
`NEWS_ALPHA_VALIDATED`
Evidence demonstrates statistically and economically meaningful out-of-sample edge after:

latency
fees
spread
slippage
execution constraints
multiple-testing adjustment
Only then may MEIE become an alpha-producing component.
`NEWS_RISK_ONLY`
No reliable directional alpha survives, but events improve:
drawdown
tail-risk avoidance
execution quality
exposure control
Use MEIE only for risk management.
`NEWS_CONTEXT_ONLY`
Useful for regime/context classification but insufficient for direct risk or alpha decisions.
`NEWS_NO_EDGE`
No meaningful incremental value.
Disable it from trading decisions.
This is a valid research result.

## 37. Critical Hypotheses to Test

Do not assume these are true.
Test them independently.
 H1:
High-novelty authoritative events predict short-horizon BTC returns.
H2:
Macro surprise magnitude predicts BTC reaction magnitude.
 H3:
Event × market-state interactions outperform event-only models.
H4:
Reaction divergence contains incremental predictive information.
H5:
TBIE response after events contains incremental information.
H6:
Professional news feeds provide usable latency advantage.
H7:
Social narrative velocity provides incremental information.
H8:
Remaining-edge estimation improves event-trade selection.
H9:
MEIE improves risk even when directional alpha is absent.
H10:
MEIE retains edge after realistic execution latency and costs.

Reject hypotheses when evidence fails.

## 38. What Must Not Be Built

Do not implement:
 headline → GPT → BUY/SELL
Do not use:
positive sentiment = LONG
negative sentiment = SHORT
Do not:
- scrape random news sites and treat them equally
- count reposts as independent confirmation
- let an LLM control risk
- use revised macro data in historical tests
- ignore publication latency
- ignore market reaction before entry
- optimize on the complete historical dataset
- report gross alpha without costs
- force trades from events
- assume more news means more alpha
- assume a sophisticated model is profitable without evidence
```
39. Target End-State Architecture
                           ┌─────────────────┐
                          │  MARKET CLOCK   │
                          └────────┬────────┘
                                   │
       ┌───────────────────────────┼──────────────────────────┐
       │                           │                          │
┌──────▼───────┐          ┌────────▼────────┐       ┌────────▼────────┐
│ MARKET DATA  │          │     MEIE        │       │      TBIE       │
│              │          │                 │       │                 │
│ Price        │          │ Macro           │       │ Trader Identity │
│ Trades       │          │ News            │       │ Wallet Behavior │
│ L2 Book      │          │ Regulation      │       │ Positioning     │
│ Derivatives  │          │ Events          │       │ Behavior Change │
└──────┬───────┘          └────────┬────────┘       └────────┬────────┘
       │                           │                          │
       └───────────────────────────┼──────────────────────────┘
                                   │
                          ┌────────▼────────┐
                          │ FEATURE STORE   │
                          └────────┬────────┘
                                   │
                          ┌────────▼────────┐
                          │ SIGNAL FUSION   │
                          │                 │
                          │ Expected Edge   │
                          │ Uncertainty     │
                          │ Horizon         │
                          └────────┬────────┘
                                   │
                          ┌────────▼────────┐
                          │  RISK KERNEL    │
                          │ FINAL AUTHORITY │
                          └────────┬────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
                  LONG           SHORT        NO TRADE

                    │              │
                    └───────┬──────┘
                            │
                    ┌───────▼────────┐
                    │ EXECUTION      │
                    │ REALITY LAYER  │
                    └───────┬────────┘
                            │
                    ┌───────▼────────┐
                    │ OBSERVATION /  │
                    │ ATTRIBUTION    │
                    └────────────────┘
40. Final Engineering Directive
```
Build MEIE as a research instrument first and a trading component second.
The system must answer five questions for every candidate event:

## 1. WHAT happened?

## 2. HOW RELIABLE and HOW NEW is the information?

## 3. HOW has the market already reacted?

## 4. HOW MUCH executable edge may still remain?

## 5. DOES that edge survive uncertainty, latency,

fees, slippage and independent risk constraints?
Only question five can justify execution.
The intended competitive advantage is not:
READ NEWS FASTER
It is:
 UNDERSTAND EVENT
        ×
UNDERSTAND MARKET STATE
        ×
UNDERSTAND TRADER BEHAVIOR
        ×
MEASURE INFORMATION DECAY
        ×
MEASURE EXECUTION REALITY
        =
POTENTIAL EXECUTABLE EDGE
Do not assume this edge exists.
Measure it. Attempt to falsify it. Preserve NO TRADE and NEWS_NO_EDGE as successful system
outcomes.

---

## What this project has already measured

Added by the repository, not part of the source specification. Two of this
document's assumptions are already constrained by measurements taken on
2026-09-14 and 2026-09-18 against the live venue, and recording them here is
cheaper than rediscovering them at MEIE-M14.

### The first four rungs of the latency ladder are unreachable

§24 requires every candidate strategy to be replayed at 0 ms, 50 ms, 100 ms,
250 ms, 500 ms, 1 s, 2 s, 5 s, 10 s and 30 s. §15 measures market reaction from
100 ms upward.

The interval between the timestamp Hyperliquid puts on an event and the moment
that event reaches a public WebSocket subscriber was measured at **p50 425 ms,
p90 566 ms, min 325 ms** over 16,755 quote observations. That is the venue's own
publication delay, established as neither our clock (systemd-timesyncd, stratum
2, root dispersion 274 µs) nor our network (one-way transport ≈ 28 ms), and it
is therefore the observation floor for *any* consumer of this feed.

So 0 ms, 50 ms, 100 ms and 250 ms cannot be occupied by this system at all,
before decoding, classification, feature generation, inference, risk check or
order transmission is counted. The ladder is not wrong — it is a good test — but
its first four rungs measure a machine this project does not have. TBIE v1.1
inherited the same assumption independently, which is worth noting: two
specifications arrived at sub-second ladders without either having measured the
floor.

**This does not invalidate MEIE.** It relocates it. Every rung from 1 s upward
is reachable, and the event classes this document is mostly about — CPI, FOMC,
exchange incidents, regulatory decisions — decay over minutes and hours rather
than milliseconds. The ladder should keep its slow rungs and extend upward, as
§24 already permits.

### Cost, not latency, is what a news edge has to clear

A round trip currently costs **9.99 bps** with the measured spread: 4.5 bps
taker fee each way plus a median half-spread of 0.49 bps. Fees are 90% of it.

Over the 322 ms it takes information to arrive, BTC's mid moves a median of
**0.066 bps** — and 3.40 bps even at the 99th percentile. So the delay is not a
tax on a fast edge; it is that no fast edge of the required size exists to be
taxed. An event-driven signal is only executable if it predicts a move
materially larger than ten basis points, which on this venue means a horizon of
minutes rather than seconds.

This makes §16 (Already-Priced-In) and §17 (Information Decay) the load-bearing
components rather than refinements. If the reaction to a CPI print is complete
within the first second, MEIE's answer for that event class is `NO TRADE`
regardless of how well the event was understood — and §36's `NEWS_RISK_ONLY`
becomes the most probable useful outcome rather than the consolation one.

Maker execution would change the arithmetic: 1.5 bps each way instead of 4.5
puts a round trip near 3 bps. Whether a passive order can be filled at a useful
moment during an event is unmeasured, and adverse selection during exactly those
moments is the reason it cannot be assumed.

### What the repository already satisfies

Three of this document's principles are load-bearing here and already hold, so
MEIE would inherit rather than introduce them:

- **§2.3 raw-first storage** — every source frame is archived to object storage
  before normalization is attempted, and normalized rows carry a reference back
  to it (`ADR-009`, Build 0.1 Rev.2 §20).
- **§2.4 point-in-time correctness** — research datasets are stamped
  `PIT_SAFE`, ordered by receipt time rather than venue time, and declare every
  gap overlapping their range rather than reading across it.
- **§23 latency instrumentation** — T0 through T11 has a partial analogue
  already: venue time, local receipt time and monotonic receipt are recorded per
  event (`ADR-007`), which is what made the 322 ms figure above measurable at
  all. The stages from classification onward do not exist yet because the
  components do not.

§2.2 — *MEIE proposes, the Risk Kernel disposes* — matches the existing
boundary exactly: the Risk Engine issues intents, the Execution Engine
re-validates them independently, and no component may reach `place_order`
directly.
