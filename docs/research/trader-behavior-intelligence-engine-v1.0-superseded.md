Trader Behavior Intelligence Engine

Research & Architecture Specification

Project: AI-Powered Automated Perpetual Futures Trading Platform
Document Type: Research & Architecture Specification
Component: Trader Behavior Intelligence Engine (TBIE)
Initial Market: BTC Perpetual Futures
Initial Venue: Hyperliquid
Revision: 1.0
Status: Research Candidate — High Priority
Production Signal Status: NOT APPROVED
Real-Capital Authority: NONE
Date: September 2026

⸻

1. Executive Summary

This document evaluates whether the observable trading behavior of historically successful and unsuccessful traders can provide incremental predictive information for an automated BTC perpetual-futures trading system.

The conclusion is:

Trader behavior should be treated as a high-priority experimental feature family, but not as a copy-trading system and not as an independent trading authority.

The central hypothesis is not:

“Successful traders bought BTC, therefore the system should buy BTC.”

Instead, the hypothesis is:

“Certain pseudonymous traders may exhibit persistent, context-dependent informational advantage or disadvantage, and their real-time behavior may contain incremental predictive information beyond price, order-book, derivatives, and anonymous order-flow data.”

Recent empirical research on Hyperliquid provides meaningful support for testing this hypothesis.

A 2026 study reconstructed a full-depth limit-order book from 17.1 billion messages and examined 14.3 million aggressive orders from 147,113 wallets representing approximately $84.3 billion of taker notional. Trader informativeness showed a 0.52 rank correlation across adjacent ten-day windows. Adding activity from the highest-ranked wallets to an anonymous price, quote, and order-flow benchmark increased out-of-sample one-second return R² to 12.31%, representing a 13.2% improvement over the benchmark. (SSRN)

Separate 2026 research comparing Binance and Hyperliquid BTC perpetual markets found that Binance led aggregate price discovery, but a minority of Hyperliquid wallets exhibited persistent anticipatory behavior. The strongest first-half wallet cohort remained the only tested quintile with positive second-half lead scores across all evaluated horizons. (SSRN)

These results do not prove that trader identity can generate profitable signals after fees, latency, slippage, funding, and implementation constraints.

They do establish that the hypothesis is scientifically credible enough to test.

The proposed component is therefore:

Trader Behavior Intelligence Engine (TBIE)

TBIE will estimate the historical, contextual, and time-varying informational quality of pseudonymous trading entities and transform their activity into research features.

TBIE will never directly authorize an order.

Its outputs must pass through the broader intelligence architecture and ultimately through the independent Risk Engine.

⸻

2. Strategic Objective

TBIE exists to answer one question:

Does point-in-time observable trader behavior provide statistically significant, economically meaningful, out-of-sample predictive information beyond the existing market-data baseline?

The engine is not designed to identify celebrities, famous traders, influencers, or social-media personalities.

The relevant analytical object is:

A persistent pseudonymous trading entity with an observable behavioral history.

The system therefore analyzes wallets and behavioral entities, not personalities.

⸻

3. Non-Objective: Copy Trading

TBIE must explicitly not become a conventional copy-trading engine.

The following logic is prohibited:

Trader X buys
      ↓
System buys

The intended architecture is:

Trader activity
      ↓
Historical contextual skill estimation
      ↓
Current trader-state estimation
      ↓
Cohort / consensus analysis
      ↓
Feature generation
      ↓
Meta-model
      ↓
LONG / SHORT / NO TRADE
      ↓
Independent Risk Engine

Observed trader behavior is evidence.

It is not an instruction.

⸻

4. Why Hyperliquid Is Unusual

Traditional centralized exchanges generally do not expose persistent counterparty identities at sufficient granularity to reconstruct individual trading behavior.

Hyperliquid creates an unusual research environment because trading activity can be associated with persistent pseudonymous wallet identities.

Recent academic work demonstrates that running a Hyperliquid non-validating node can enable reconstruction of highly granular order-flow datasets containing order placements, cancellations, rejected orders, failed cancellation attempts, pseudonymous trader identities, counterparties on both sides of transactions, and post-transaction inventory information. (SSRN)

This creates the possibility of studying not merely:

* Price
* Volume
* Order-book state

but:

* Who acted
* When they acted
* How aggressively they acted
* What they did before
* What happened after their action
* Whether their informational quality persisted

This distinction is central to TBIE.

⸻

5. Research Evidence

5.1 Public Trader Identity and Return Predictability

The strongest current empirical evidence comes from the 2026 study Public Trader Identity: Adverse Selection and Return Predictability.

The study analyzed:

* 17.1 billion messages
* 14.3 million aggressive orders
* 147,113 wallets
* Approximately $84.3 billion in taker notional

Wallet informativeness was ranked according to subsequent price movement following aggressive orders.

The ordering displayed persistence across adjacent ten-day windows, with rank correlation:

[
\rho = 0.52
]

Adding live activity from highly ranked wallets to an anonymous benchmark based on prices, quotes, and order flow increased out-of-sample one-second return:

[
R^2 = 12.31%
]

representing a reported:

[
13.2%
]

improvement over the benchmark.

The improvement was also compared with 200 activity-matched placebo cohorts. (SSRN)

This is not evidence of 13.2% trading profitability.

It is evidence that persistent trader identity contained incremental short-horizon information in the studied sample.

⸻

6. Cross-Venue Evidence

A separate 2026 study examined price discovery between Binance and Hyperliquid BTC perpetual futures.

At the aggregate venue level, Binance led Hyperliquid.

However, wallet-level analysis revealed substantial heterogeneity.

A minority of Hyperliquid wallets demonstrated behavior that preceded subsequent Binance price movement.

Split-sample analysis suggested that the strongest wallet cohort retained anticipatory characteristics out of sample across the tested horizons. (SSRN)

This produces an important architectural principle:

Venue-level informational leadership and trader-level informational leadership are not the same phenomenon.

Hyperliquid can be a follower in aggregate while still containing individual traders whose actions possess anticipatory information.

TBIE must therefore operate at wallet and cohort level rather than relying only on aggregate Hyperliquid flow.

⸻

7. Level-4 Market Data Opportunity

Research published in 2026 demonstrates the feasibility of reconstructing unusually granular Hyperliquid market data by operating a non-validating node.

The resulting dataset includes information beyond conventional Level-3 feeds, including rejected orders and failed cancellation attempts in addition to order placements, cancellations, counterparty identity, and post-transaction inventory. (SSRN)

Another 2026 study analyzing approximately 4.5 billion messages from the BTC perpetual contract found that rejected post-only orders represented approximately 67% of message traffic in its dataset and identified anticipatory liquidity-replenishment behavior associated with a small number of market makers. (SSRN)

This suggests that TBIE may eventually analyze more than completed trades.

Potential behavioral information includes:

Order submission
Order cancellation
Rejected order
Failed cancellation
Aggressive execution
Passive execution
Position change
Inventory evolution
Order persistence
Order replacement
Queue behavior
Execution timing

This substantially expands the potential information surface.

⸻

8. Behavioral Intelligence vs. PnL Ranking

TBIE must not define a successful trader solely using realized PnL or win rate.

A trader with:

90% win rate

can still have negative expected value if occasional losses dominate accumulated gains.

Likewise, a trader with:

35% win rate

may have strongly positive expectancy.

Trader evaluation should therefore be multidimensional.

⸻

9. Trader Skill Vector

The conceptual unit is:

[
Skill_{i,t,h,r}
]

where:

* (i) = pseudonymous trader or behavioral entity
* (t) = point-in-time evaluation time
* (h) = prediction horizon
* (r) = market regime

The system should estimate skill conditionally rather than assign permanent labels such as:

GOOD TRADER
BAD TRADER

A trader may instead exhibit:

BTC Long / Trend Regime        → Strong
BTC Short / Trend Regime       → Moderate
BTC Long / Range Regime        → Weak
BTC Short / High Volatility    → Strong
1-second horizon               → Strong
30-second horizon              → Strong
5-minute horizon               → Neutral
1-hour horizon                 → Weak

Skill is therefore:

Contextual, horizon-dependent, regime-dependent, and time-varying.

⸻

10. Proposed Trader State

At any time (t), TBIE may maintain:

TraderState(wallet, t)
Historical Skill
Recent Skill
BTC-Specific Skill
Long Skill
Short Skill
Trend-Regime Skill
Range-Regime Skill
Volatility-Regime Skill
Aggressive Buy Markout
Aggressive Sell Markout
Holding-Period Distribution
Position-Sizing Behavior
Scale-In Behavior
Scale-Out Behavior
Average MFE
Average MAE
Drawdown
Consistency
Recency
Funding Exposure
Margin Behavior
Order Aggressiveness
Maker/Taker Behavior
Current Observable Position
Position Change
Behavioral Stability
Reliability Score
Sample Size
Uncertainty

Every value must carry sufficient metadata to determine whether it was legally available to the model at prediction time.

⸻

11. Markout-Based Skill

Realized PnL alone is insufficient for measuring informational quality.

TBIE should measure signed price movement following observable actions.

If a wallet aggressively buys BTC at time (t), calculate price movement over multiple horizons:

t + 1 second
t + 2 seconds
t + 5 seconds
t + 10 seconds
t + 30 seconds
t + 1 minute
t + 5 minutes
t + 15 minutes
t + 1 hour

Conceptually:

[
M_{i,t,h}=s_{i,t}(P_{t+h}-P_t)
]

where:

* (s=+1) for buy
* (s=-1) for sell
* (P_t) is an appropriate reference price
* (h) is the evaluation horizon

Normalized or basis-point variants should also be tested.

This allows TBIE to answer:

Does this trader systematically act before favorable price movement?

That question may be more useful than:

Was the trader’s final position profitable?

⸻

12. PnL Still Matters

Markout should not replace PnL.

Both capture different dimensions.

Markout estimates informational timing.

PnL estimates the eventual economic result of the trader’s position-management process.

TBIE should therefore distinguish:

INFORMATIONAL SKILL
from
POSITION-MANAGEMENT SKILL

A trader may possess one without the other.

⸻

13. Successful Trader Definition

A trader should qualify as potentially informed only after satisfying minimum evidence requirements.

Potential dimensions include:

* Minimum observations
* Minimum active history
* Signed markout
* Risk-adjusted performance
* Maximum drawdown
* Consistency
* Regime stability
* Directional stability
* Recency
* Sample confidence
* Out-of-sample persistence

No single metric should permanently define trader quality.

⸻

14. Weak-Trader Intelligence

TBIE should not restrict analysis to successful traders.

Persistently poorly timed traders may also contain information.

A cohort that systematically:

* buys before declines,
* sells before rallies,
* enters late into exhausted moves,
* increases leverage near local extremes,

may constitute a useful behavioral signal.

Therefore the system should research both:

INFORMED FLOW

and:

UNINFORMED / ADVERSELY SELECTED FLOW

⸻

15. Informed vs. Uninformed Divergence

A potentially powerful feature family is:

[
D_t =
Flow^{informed}_t -
Flow^{uninformed}_t
]

Example:

High-skill cohort     → strongly LONG
Low-skill cohort      → strongly SHORT

may contain more information than either cohort independently.

This must be tested empirically.

It must not be assumed.

⸻

16. Smart Trader Consensus

TBIE may construct a weighted consensus across currently active traders.

Let:

[
s_{i,t}\in[-1,1]
]

represent normalized directional activity and:

[
w_{i,t}
]

represent the point-in-time trader reliability weight.

Then:

[
Consensus_t =
\frac{\sum_i w_{i,t}s_{i,t}}
{\sum_i |w_{i,t}|}
]

Potential weights may depend on:

* Historical skill
* Recent skill
* Relevant horizon
* Current regime
* BTC-specific performance
* Sample size
* Skill uncertainty
* Skill decay
* Drawdown
* Direction-specific skill

Consensus is a feature.

It is not an order.

⸻

17. Cohort Architecture

Rather than tracking only individual wallets, TBIE should construct behavioral cohorts.

Potential cohorts include:

Persistent Informed Traders
Persistent Weak Traders
High-Frequency Makers
Directional Takers
Momentum Traders
Mean-Reversion Traders
Large Position Traders
Short-Horizon Leaders
Long-Horizon Leaders
Regime Specialists
Liquidation Absorbers
TWAP Users

Research on Hyperliquid also indicates meaningful differences in market impact and execution behavior between visible TWAP programs and reconstructed hidden metaorders, reinforcing the value of distinguishing behavioral classes rather than treating all large flow identically. (SSRN)

⸻

18. Point-in-Time Requirement

This is the most important research constraint.

Suppose Wallet A becomes one of Hyperliquid’s best-performing wallets during December.

A corrupted experiment would:

1. Identify Wallet A using December performance.
2. Go back to January.
3. Label Wallet A as informed.
4. Backtest January using that label.

This uses future information.

It is prohibited.

The correct process is:

At time T:
Use only data available before T
↓
Estimate trader skill
↓
Freeze trader ranking
↓
Observe future trader activity
↓
Generate feature
↓
Evaluate future outcome

No future reputation may leak backward.

⸻

19. Survivorship Bias

Current leaderboards are unsuitable as historical truth.

If only wallets that survived and became successful are selected, failed traders disappear from the dataset.

The resulting historical model will overestimate the value of trader selection.

Therefore historical cohort construction must include the observable population available at each historical point.

⸻

20. Wallet Rotation

A trader may abandon one wallet and move to another.

Therefore:

wallet ≠ guaranteed persistent human identity

TBIE should initially treat every wallet as an independent pseudonymous entity.

Wallet clustering may later become a separate research problem.

Any clustering methodology must be independently validated.

⸻

21. Multiple Wallets

One trader may operate many wallets.

Multiple traders may potentially share operational infrastructure.

TBIE must therefore avoid interpreting wallet counts as counts of unique humans.

The analytical entity remains:

Observable pseudonymous trading behavior.

⸻

22. Hidden Hedging

An observed Hyperliquid position may represent only one component of a broader portfolio.

A trader may be:

LONG BTC on Hyperliquid
but
SHORT BTC elsewhere

or may hold:

* Options
* Spot
* Futures
* OTC exposure
* Cross-asset hedges

Therefore:

Observable direction does not necessarily equal directional belief.

TBIE should infer statistical behavior, not psychological intention.

⸻

23. Latency Risk

A trader may possess information while being impossible to follow profitably.

For example:

Trader buys
↓
Price immediately moves
↓
System detects trade
↓
Signal generated
↓
Order transmitted
↓
Edge already gone

Therefore the correct test is not:

Did the trader predict the market?

It is:

Was actionable predictive information still available after our observation, computation, transmission, and execution latency?

This distinction is mandatory.

⸻

24. Capacity and Crowding

A behavioral signal may degrade as more capital follows it.

TBIE must eventually measure:

* Signal crowding
* Price impact
* Capacity
* Decay
* Execution deterioration

Historical predictive power does not imply scalable executable alpha.

⸻

25. Reflexivity

If a particular wallet becomes widely monitored, the market may begin reacting immediately to its activity.

The observed relationship can then change.

TBIE must therefore support continuous skill re-estimation and decay detection.

No trader receives permanent privileged status.

⸻

26. Skill Decay

For every trader:

[
Skill_{i,t}
]

must be allowed to decline.

Potential causes include:

* Strategy degradation
* Market-regime change
* Increased competition
* Behavioral change
* Capital scaling
* Wallet ownership change
* Random historical luck

TBIE should support recency-weighted and rolling-window estimates.

⸻

27. Confidence and Uncertainty

A wallet with five excellent trades should not automatically outrank a wallet with thousands of moderately informative trades.

Skill estimates therefore require uncertainty.

Conceptually:

Estimated Skill
+
Sample Size
+
Confidence Interval
+
Stability
+
Recency

must jointly determine weighting.

⸻

28. Minimum Sample Requirements

The system must establish research-derived thresholds for:

* Minimum fills
* Minimum active days
* Minimum market regimes observed
* Minimum directional diversity
* Minimum notional
* Minimum horizon observations

These thresholds must not be arbitrarily selected for the purpose of maximizing backtest performance.

⸻

29. Data Architecture

TBIE requires two related data streams.

Stream A: Market State

BTC MARKET RECORDER
Price
Trades
BBO
L2 Order Book
Funding
Open Interest
Asset Context
Volatility State

Stream B: Trader Events

TRADER EVENT RECORDER
Wallet / Pseudonymous Entity
Timestamp
Asset
Side
Price
Size
Order ID
Execution Type
Starting Position
Resulting Position where available
Counterparty where available
Event Type
Raw Source

The two streams must share a consistent time model.

⸻

30. Raw Data Preservation

Raw events should be preserved before transformation.

Source
   ↓
Raw Immutable Event
   ↓
Validation
   ↓
Normalization
   ↓
Enrichment
   ↓
Feature Construction

A normalization error must not destroy original evidence.

⸻

31. Event-Time Architecture

Every record should distinguish, where available:

exchange_event_time
block_time
source_time
receive_time
normalize_time
persist_time

This allows latency analysis and prevents ambiguous ordering.

⸻

32. Trader Event Schema

Conceptually:

TraderEvent
event_id
source
venue
asset
wallet
counterparty
event_type
side
price
size
notional
order_id
execution_type
start_position
end_position
exchange_timestamp
receive_timestamp
raw_event_reference
schema_version
ingestion_version

Fields should remain nullable when source data does not reliably provide them.

Unknown information must not be fabricated.

⸻

33. Trader State Store

Derived trader state should be versioned.

Conceptually:

TraderStateSnapshot
wallet
as_of_time
sample_count
active_days
skill_1s
skill_5s
skill_30s
skill_1m
skill_5m
skill_1h
long_skill
short_skill
trend_skill
range_skill
high_vol_skill
recent_skill
historical_skill
drawdown
consistency
confidence
uncertainty
feature_version

Every snapshot must be reproducible from historical events available at as_of_time.

⸻

34. Feature Families

Initial candidate features include:

Individual Trader Features

TraderSkill
TraderSkillChange
TraderRecentMarkout
TraderLongSkill
TraderShortSkill
TraderRegimeSkill
TraderActivityIntensity
TraderPositionChange

Cohort Features

InformedBuyFlow
InformedSellFlow
WeakBuyFlow
WeakSellFlow
SmartConsensus
WeakConsensus
InformedWeakDivergence
TopDecileNetFlow
SkillWeightedFlow

Behavioral Features

Aggressiveness
PositionAcceleration
ScaleInIntensity
ScaleOutIntensity
TradeClustering
DirectionPersistence
HoldingPeriodState

⸻

35. Cross-Venue Features

The cross-venue research suggests another experimental family:

Hyperliquid informed-wallet activity
versus
Binance BTC price discovery

Possible features include:

HL informed flow
Binance short-horizon return
Cross-venue lead score
Cross-venue lag score
Wallet anticipatory score
Venue divergence

This should remain a separate experiment because it introduces additional data synchronization and latency complexity.

⸻

36. Model Architecture

TBIE should initially be implemented as an independent research model.

Conceptually:

                 MARKET STATE
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
       PRICE       ORDER FLOW   DERIVATIVES
       MODEL         MODEL        MODEL
          │           │           │
          └───────────┼───────────┘
                      │
                      ▼
            TRADER BEHAVIOR MODEL
                      │
                      ▼
              REGIME CONDITIONING
                      │
                      ▼
                  META MODEL
                      │
             ┌────────┼────────┐
             ▼        ▼        ▼
           LONG     SHORT   NO TRADE
                      │
                      ▼
                 RISK ENGINE

No TBIE output may bypass the Meta Model or Risk Engine.

⸻

37. AI Training Role

Trader data may eventually contribute to AI training through:

* Feature inputs
* Meta-labeling
* Regime-conditioned signals
* Representation learning
* Trader embeddings
* Cohort embeddings
* Anomaly detection
* Skill-decay detection

However, the first TBIE implementation should favor interpretable statistical features over deep-learning representations.

Complexity must be earned.

⸻

38. Trader Embeddings

A future experimental extension may learn behavioral embeddings:

[
E_i=f(behavior_i)
]

where wallets with similar trading behavior occupy similar representation space.

Potential inputs:

* Holding period
* Aggressiveness
* Position sizing
* Direction persistence
* Regime preference
* Markout profile
* Order type
* Activity timing

This may allow the system to identify trader archetypes without manually defining them.

This remains future research.

⸻

39. Counterfactual Analysis

The system should record what would have happened if TBIE had been followed or ignored.

For every qualifying event:

Observed Trader Signal
↓
System Decision
↓
Risk Decision
↓
Actual Market Outcome

Counterfactuals:

Outcome if TBIE ignored
Outcome if TBIE included
Outcome if TBIE inverted
Outcome under alternative weighting

This enables proper attribution.

⸻

40. Ablation Requirement

TBIE must prove incremental value.

The minimum experiment is:

Model A

Market Data

Model B

Market Data
+
Derivatives

Model C

Market Data
+
Derivatives
+
Trader Behavior

TBIE survives only if:

[
Performance_C > Performance_B
]

under robust out-of-sample testing.

⸻

41. Economic Significance

Statistical significance alone is insufficient.

TBIE must improve economically relevant outcomes after:

* Fees
* Spread
* Slippage
* Funding
* Latency
* Execution failure
* Turnover

A predictive improvement that cannot survive execution costs is not deployable alpha.

⸻

42. Evaluation Horizons

Initial research should evaluate multiple horizons independently.

Potential horizons:

1 second
2 seconds
5 seconds
10 seconds
30 seconds
1 minute
5 minutes
15 minutes
1 hour

The system must not assume that wallet intelligence persists equally across horizons.

Existing research indicates particularly interesting behavior at very short horizons, making latency modeling essential. (SSRN)

⸻

43. Research Metrics

Evaluation should include:

Out-of-Sample R²
Information Coefficient
Directional Accuracy
Signed Markout
Incremental AUC where appropriate
Calibration
Net Expected Value
Sharpe
Sortino
Maximum Drawdown
Turnover
Cost Sensitivity
Regime Stability
Feature Stability
Signal Half-Life

No single metric determines success.

⸻

44. Statistical Controls

TBIE research must use the project’s existing quantitative standards:

* Point-in-time correctness
* Purged cross-validation
* Embargo
* Walk-forward testing
* CPCV where appropriate
* Multiple-testing controls
* Deflated Sharpe Ratio
* Probability of Backtest Overfitting
* Parameter robustness
* Placebo cohorts
* Randomized trader cohorts

⸻

45. Placebo Tests

Placebo testing is particularly important.

Examples:

Top Skill Cohort
vs.
Random Activity-Matched Cohort

and:

Observed Wallet Ranking
vs.
Shuffled Wallet Ranking

and:

Current Skill
vs.
Future-Leaked Skill

The last comparison can help quantify how much apparent performance would be created by leakage.

⸻

46. Adversarial Tests

TBIE should also be attacked deliberately.

Examples:

* Randomize wallet identities.
* Shift trader timestamps.
* Delay signals by 100 ms, 500 ms, 1 s, 5 s.
* Double estimated slippage.
* Remove top trader.
* Remove top 10 traders.
* Invert weak-trader cohort.
* Change skill window.
* Change regime definition.
* Simulate wallet disappearance.
* Simulate sudden skill decay.

A real signal should not depend on one fragile configuration.

⸻

47. Concentration Risk

TBIE must measure whether apparent edge depends on a tiny number of wallets.

For example:

Signal with all traders
vs.
Signal excluding top trader
vs.
Signal excluding top 5
vs.
Signal excluding top 10

If edge disappears after removing one wallet, the system contains severe concentration risk.

⸻

48. Data Acquisition Strategy

TBIE data acquisition should proceed incrementally.

Stage 1

Use accessible Hyperliquid market and wallet information.

Stage 2

Record required live events internally.

Stage 3

Evaluate whether historical reconstruction is sufficient.

Stage 4

Benchmark the cost and value of operating a non-validating node.

Stage 5

Only if justified, ingest full Level-4-style message data.

This prevents infrastructure cost from exploding before predictive value is demonstrated.

⸻

49. Node Data Cost

The Level-4 opportunity is valuable but potentially expensive.

High-frequency Hyperliquid research has demonstrated datasets containing billions of messages over relatively short periods. One BTC-focused study analyzed approximately 4.5 billion messages over one month. (SSRN)

Therefore full raw node ingestion must be treated as a storage and compute engineering decision rather than an automatic requirement.

Before production ingestion, benchmark:

* Daily raw volume
* Compression ratio
* Storage cost
* Network requirements
* ClickHouse ingestion rate
* Replay throughput
* Retention requirements

⸻

50. Build 0.1 Impact

TBIE does not justify expanding Build 0.1 into a large AI project.

The Lean BTC Quant MVP remains valid.

M0 Rev.2 should receive one additional architecture decision record:

ADR-004

Trader Behavior Intelligence as an Experimental Feature Family

The ADR should state:

Decision: Preserve architectural support for wallet-level trader intelligence.

Status: Experimental.

Production Authority: None.

Data Priority: Preserve required identity-linked event information where practical.

Validation Requirement: Point-in-time ablation against anonymous baseline.

⸻

51. M2 Recorder Impact

M2 remains primarily:

BTC Hyperliquid Live Recorder

However, the recorder architecture must avoid unnecessarily discarding trader-identity information that may later be expensive or impossible to reconstruct.

Conceptually:

                 HYPERLIQUID
                      │
          ┌───────────┴───────────┐
          │                       │
          ▼                       ▼
 BTC MARKET EVENTS          TRADER EVENTS
          │                       │
          ▼                       ▼
    RAW STORAGE               RAW STORAGE
          │                       │
          └───────────┬───────────┘
                      ▼
                NORMALIZATION
                      │
                      ▼
                 TIME ALIGNMENT
                      │
                      ▼
                  RESEARCH

This is an architectural preservation decision, not a requirement to implement the complete TBIE during M2.

⸻

52. Initial TBIE Experiment

After the core BTC recorder and research pipeline are reliable, the first TBIE experiment should test:

Do wallets classified as informed using only information available before time T predict future BTC price movement out of sample beyond price, L2, and anonymous order flow?

This should be the first formal hypothesis.

⸻

53. Hypothesis H0

Null hypothesis:

[
H_0:
TraderIdentity
\text{ provides no incremental predictive information}
]

after controlling for:

* Price
* Order book
* Anonymous order flow
* Market regime

⸻

54. Hypothesis H1

Alternative hypothesis:

[
H_1:
TraderIdentity
\text{ provides persistent incremental predictive information}
]

out of sample.

Rejecting (H_0) statistically is still insufficient for deployment.

Economic significance must also pass.

⸻

55. Second Experiment

If H1 survives:

Does skill-weighted trader consensus outperform unweighted trader flow?

Compare:

All Trader Flow
vs.
Top Trader Flow
vs.
Skill-Weighted Flow
vs.
Regime-Conditioned Skill-Weighted Flow

⸻

56. Third Experiment

If the second experiment survives:

Does informed-vs-weak divergence outperform informed flow alone?

Compare:

Informed Flow
vs.
Weak Flow
vs.
Informed - Weak Divergence

⸻

57. Fourth Experiment

If sufficient cross-venue data becomes available:

Do historically anticipatory Hyperliquid wallets predict subsequent Binance BTC price movement after realistic observation latency?

This experiment directly tests whether cross-venue trader intelligence is actionable rather than merely statistically interesting.

⸻

58. Promotion Gate

TBIE can move from:

Research Candidate

to:

Validated Feature

only if it demonstrates:

1. Point-in-time correctness.
2. Out-of-sample persistence.
3. Incremental value beyond baseline.
4. Robustness across periods.
5. Reasonable regime stability.
6. Resistance to placebo testing.
7. Resistance to trader removal.
8. Resistance to parameter perturbation.
9. Survival after realistic latency.
10. Survival after realistic transaction costs.

⸻

59. Production Gate

Validated Feature does not mean Production Signal.

Production consideration additionally requires:

* Paper validation
* Shadow validation
* Execution compatibility
* Feature freshness monitoring
* Skill-decay monitoring
* Data-quality monitoring
* Concentration monitoring
* Fail-safe behavior

Only then may TBIE influence real-capital decisions.

⸻

60. Failure Outcome

The valid outcome:

TBIE_NO_EDGE

must exist.

If trader identity fails incremental testing, the project must not force it into the product merely because the concept is attractive.

The component should then be:

ARCHIVED

or:

RESEARCH ONLY

The broader trading architecture remains functional without it.

⸻

61. Security and Privacy Principle

TBIE analyzes publicly observable pseudonymous trading behavior.

The system should not attempt to deanonymize wallet owners unnecessarily.

Research value comes from behavioral persistence, not real-world identity.

Therefore:

Wallet 0xABC...

is analytically sufficient.

The question:

“Who is this person?”

is generally irrelevant.

The question:

“Does this pseudonymous entity demonstrate persistent predictive behavior?”

is relevant.

⸻

62. Risk Authority

TBIE has:

NO execution authority
NO leverage authority
NO position-size authority
NO stop-loss authority
NO risk-limit authority
NO kill-switch authority

TBIE outputs information.

The Risk Engine controls capital.

This boundary is immutable.

⸻

63. Architectural Position

Final conceptual architecture:

                    MARKET
                       │
         ┌─────────────┼─────────────┐
         │             │             │
         ▼             ▼             ▼
       PRICE          L2         DERIVATIVES
       MODEL         MODEL          MODEL
         │             │             │
         └─────────────┼─────────────┘
                       │
                       ▼
              TRADER BEHAVIOR
              INTELLIGENCE ENGINE
                       │
                       ▼
                 REGIME ENGINE
                       │
                       ▼
                  META MODEL
                       │
              ┌────────┼────────┐
              │        │        │
              ▼        ▼        ▼
            LONG     SHORT   NO TRADE
                       │
                       ▼
                  RISK ENGINE
                       │
                 APPROVE / REJECT
                       │
                       ▼
                EXECUTION ENGINE
                       │
                       ▼
                  EXCHANGE

⸻

64. Research Decision

Based on current evidence:

Scientific Plausibility: HIGH

Data Availability: PROMISING

Implementation Complexity: MEDIUM TO HIGH

Leakage Risk: VERY HIGH

Latency Sensitivity: VERY HIGH

Potential Incremental Information: PROMISING

Production Readiness: NONE

Research Priority: HIGH

Build 0.1 Critical Path: NO

Recorder Architecture Impact: YES

⸻

65. Final Decision

Trader Behavior Intelligence is formally accepted into the research architecture as an:

EXPERIMENTAL HIGH-PRIORITY FEATURE FAMILY

It is not accepted as a proven source of alpha.

It is not accepted as a production trading signal.

It is not accepted as a copy-trading mechanism.

The project will preserve the data and architecture required to evaluate it rigorously.

The decisive experiment remains:

Can point-in-time, historically estimated trader skill predict future BTC perpetual returns beyond anonymous market information, and does that incremental information remain economically valuable after latency, fees, spread, slippage, funding, and execution constraints?

If the answer is YES:

PROMOTE

If the answer is NO:

REMOVE

No narrative, reputation, leaderboard, founder preference, or AI complexity may override that result.

⸻

66. Immediate Project Action

Add:

ADR-004 — Trader Behavior Intelligence as an Experimental Feature Family

to Build 0.1 Rev.2.

Preserve trader-identity-linked event information during recorder design where technically and economically reasonable.

Do not delay the BTC market recorder to build the full TBIE.

The immediate engineering sequence remains:

M0 Rev.2
    ↓
M1 Storage
    ↓
M2 BTC Recorder
    ↓
M3 Data Integrity / Replay
    ↓
BTC Research Dataset
    ↓
Baseline Research
    ↓
Trader Behavior Experiment

The principle is:

Capture the evidence now. Earn the complexity later.