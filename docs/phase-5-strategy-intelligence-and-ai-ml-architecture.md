Strategy Intelligence & AI/ML Architecture Specification

Version: 1.0
Phase: 5 — Strategy Intelligence & AI/ML Architecture
Core Assets: BTC, ETH, SOL, BNB
System: AI-Powered Automated Trading Platform
Status: Research Architecture
Criticality: Maximum

⸻

1. Purpose

The purpose of the Strategy Intelligence & AI/ML Engine is to transform validated historical and real-time market information into probabilistic trading intelligence.

The system is not designed to predict the exact future price of an asset.

Its primary objective is:

Estimate whether a statistically favorable trading opportunity currently exists, quantify the uncertainty surrounding that opportunity, and determine whether the opportunity is strong enough to justify taking risk.

The fundamental outputs are:

LONG

SHORT

NO TRADE

Additional outputs may include:

* Expected return distribution
* Probability of success
* Expected adverse movement
* Expected favorable movement
* Market regime
* Signal quality
* Prediction uncertainty
* Strategy agreement
* Recommended holding horizon

The AI Engine does not have authority to execute trades.

Every actionable signal must pass through the independent Risk Engine.

⸻

2. Fundamental Architecture

The AI system will not initially rely on one monolithic model.

The preferred architecture is a multi-layer intelligence system:

Historical + Live Data

↓

Feature Engine

↓

Market Regime Engine

↓

Specialized Strategy Models

↓

Meta-Model

↓

Ensemble Decision Engine

↓

Uncertainty & Calibration Layer

↓

LONG / SHORT / NO TRADE

↓

Risk Engine

↓

Execution Engine

This architecture separates:

prediction

from:

risk

and:

execution.

⸻

3. Why a Single AI Model Is Not Preferred

Crypto markets behave differently under different conditions.

A model effective during:

strong trends

may fail during:

range-bound markets.

A model effective during:

normal liquidity

may fail during:

liquidity shocks.

A single universal model would therefore be forced to learn multiple conflicting market behaviors simultaneously.

The preferred architecture is:

specialized intelligence + controlled ensemble.

⸻

4. Intelligence Hierarchy

The system will contain several intelligence layers.

Layer 1 — Market State

What is happening now?

Layer 2 — Market Regime

What type of market environment are we currently experiencing?

Layer 3 — Strategy Signals

Do specific market mechanisms indicate opportunity?

Layer 4 — Meta Intelligence

Should the base signal actually be traded?

Layer 5 — Ensemble Intelligence

How much agreement exists between independent sources of evidence?

Layer 6 — Uncertainty

How reliable is the current prediction?

Layer 7 — Risk

Even if the opportunity is statistically attractive, should capital be exposed?

This hierarchy prevents one model from controlling the entire decision process.

⸻

5. Market Regime Engine

The first major intelligence component should classify the current market environment.

Candidate regimes include:

Bull Trend

Bear Trend

Range

Breakout

High Volatility

Low Volatility

Volatility Expansion

Volatility Compression

Liquidity Stress

Panic

Short Squeeze

Long Squeeze

Regimes may overlap.

For example:

Bull Trend + High Volatility

may be a valid market state.

Therefore regime representation should not necessarily be restricted to one mutually exclusive label.

⸻

6. Regime Detection Methods

Multiple methods should be researched.

Candidate approaches include:

Statistical

* Volatility thresholds
* Trend strength
* Distribution shifts
* Correlation changes

Unsupervised ML

* K-Means
* Gaussian Mixture Models
* Hidden Markov Models
* Change-point detection

Supervised ML

Models trained on explicitly defined market-state labels.

Hybrid

Combine statistical rules with machine-learning probabilities.

No regime-detection technique receives automatic production approval.

The winner must be determined experimentally.

⸻

7. Regime Probability

The system should preferably avoid pretending regime identification is perfectly certain.

Instead of:

REGIME = BULL

the system may internally represent:

Bull Trend: 62%

Range: 18%

High Volatility: 74%

This preserves uncertainty.

⸻

8. Strategy Families

The intelligence engine should initially research independent strategy families.

Trend

Uses information such as:

* Price structure
* Momentum persistence
* Moving-average relationships
* Multi-timeframe alignment

Momentum

Measures:

* Return acceleration
* Relative strength
* Volume-confirmed momentum
* Cross-asset momentum

Mean Reversion

Searches for statistically abnormal deviations likely to revert.

Breakout

Detects:

* Range escape
* Volatility expansion
* Volume confirmation
* Liquidity displacement

Order Flow

Uses:

* Aggressive Buy/Sell pressure
* Book imbalance
* Depth
* Spread
* Trade intensity

Derivatives

Uses:

* Funding
* Open Interest
* Basis
* Price/OI relationships
* Liquidation conditions

On-Chain

Uses only validated features that demonstrate incremental predictive value.

Cross-Market

Uses relationships among:

BTC / ETH / SOL / BNB

and broader market context where validated.

⸻

9. Independent Strategy Models

Where possible, strategy families should remain logically independent.

Example:

Trend Model

Order Flow Model

Derivatives Model

Volatility Model

Cross-Market Model

On-Chain Model

Each produces its own evidence.

Example output:

Trend: +0.71

Order Flow: +0.48

Derivatives: -0.22

Volatility: Risk Elevated

On-Chain: +0.10

This is preferable to hiding all reasoning inside one opaque score.

⸻

10. Direction Model vs Tradeability Model

A critical architectural distinction must exist between:

Where might the market move?

and:

Is this opportunity worth trading?

These are different questions.

A model may predict:

BTC likely to rise

while the trading system concludes:

NO TRADE

because:

* Expected move is too small
* Spread is too wide
* Volatility is excessive
* Funding is unfavorable
* Uncertainty is high
* Portfolio exposure is already excessive

Direction prediction alone does not constitute a trading strategy.

⸻

11. Meta-Labeling

A Meta-Model should be researched above base strategies.

The base strategy asks:

Is there a directional opportunity?

The Meta-Model asks:

Is this particular signal worth acting upon?

Conceptually:

Base Signal

↓

Meta-Model

↓

TRADE / REJECT

This may reduce low-quality trades without forcing the directional model to solve every decision simultaneously.

⸻

12. Target Design

Target construction is one of the most important research decisions.

Candidate targets include:

Direction Classification

UP / DOWN

Simple but potentially insufficient.

Three-Class Classification

LONG / SHORT / NO TRADE

Return Regression

Predict future return over horizon H.

Risk-Adjusted Return

Predict return relative to expected volatility.

Barrier Outcome

Predict whether:

Take Profit

or:

Stop Loss

is likely to be reached first.

Distribution Prediction

Estimate a distribution of possible future returns rather than a single value.

Different targets must compete experimentally.

⸻

13. Multi-Horizon Intelligence

A single prediction horizon is unlikely to capture the entire market.

Candidate horizons may include:

5 minutes

15 minutes

1 hour

4 hours

potentially longer where justified.

The system may produce:

BTC 5m → Neutral

BTC 15m → Long

BTC 1h → Long

BTC 4h → Bullish Regime

The Decision Engine can then reason over horizon agreement.

⸻

14. Asset Architecture

Three architectures should be tested.

Architecture A — Independent Models

Separate models for:

BTC

ETH

SOL

BNB

Advantages:

Asset specialization.

Disadvantages:

Less shared learning.

Architecture B — Shared Model

One model trained across all four assets with asset identity and contextual features.

Advantages:

Potential cross-asset learning and larger training sample.

Disadvantages:

May incorrectly assume common behavior.

Architecture C — Hybrid

Shared representation plus asset-specific components.

This should be treated as the advanced candidate.

No architecture should be selected before empirical comparison.

⸻

15. Baseline Models

Before Deep Learning, the system must establish strong statistical and ML baselines.

Mandatory candidates include:

Logistic Regression

Linear / Regularized Models

Random Forest

XGBoost

LightGBM

Potential additional models:

CatBoost

These provide strong reference points for structured financial features.

⸻

16. Why Gradient-Boosted Trees Matter

Much of the initial feature space will be structured numerical information:

* Returns
* Volatility
* Funding
* OI
* Order-flow metrics
* Regime features
* Cross-asset features
* On-chain metrics

Gradient-boosted trees are therefore strong candidates.

They provide:

* Non-linear relationships
* Feature interactions
* Efficient training
* Feature importance tools
* Relatively fast experimentation

They also allow the project to establish powerful baselines before introducing neural architectures.

⸻

17. Deep Learning Research Track

Deep Learning remains a research track rather than a default production choice.

Candidate architectures include:

MLP

LSTM

GRU

Temporal CNN

Transformer

Temporal Fusion architectures

Potential advantages include learning:

* Sequential patterns
* Long-range dependencies
* Cross-feature interactions
* Dynamic temporal representations

Potential disadvantages include:

* Greater overfitting risk
* Larger data requirements
* Higher computational cost
* Lower interpretability
* More difficult debugging
* More complex production infrastructure

A neural model must outperform simpler models after costs and robust validation to justify deployment.

⸻

18. Sequence Models

Sequence models should consume historical windows rather than isolated snapshots.

Conceptually:

T-100

…

T-2

T-1

T

↓

Sequence Model

↓

Future Probability Distribution

The appropriate window length must be determined experimentally.

⸻

19. Multi-Timeframe Representation

Models should be capable of receiving multiple temporal contexts.

Example:

1m Microstructure

5m Momentum

15m Tactical Structure

1h Trend

4h Regime

This provides both local and broader market context.

However, additional timeframes must pass ablation testing.

⸻

20. Feature Groups

The Feature Engine should organize inputs into families.

Price

* Returns
* Log returns
* Range
* Candle structure

Trend

* Moving-average relationships
* Trend strength
* Distance from trend

Momentum

* ROC
* Relative momentum
* Momentum acceleration

Volatility

* ATR
* Realized volatility
* Volatility ratios

Volume

* Volume change
* Relative volume
* Volume anomalies

Order Flow

* Trade imbalance
* Book imbalance
* Depth
* Spread
* Liquidity

Derivatives

* Funding
* OI
* Basis
* Liquidation state

On-Chain

Only validated point-in-time features.

Cross-Market

* Correlation
* Beta
* Relative strength
* Lead/Lag

Regime

* Trend regime
* Volatility regime
* Liquidity regime

⸻

21. Feature Selection

More features do not automatically create better models.

Feature selection should use combinations of:

* Ablation testing
* Permutation importance
* Stability analysis
* Correlation analysis
* Mutual information
* SHAP where appropriate
* Regularization
* Out-of-sample contribution

A feature should ideally demonstrate:

incremental predictive value

rather than simply correlate with historical outcomes.

⸻

22. Feature Stability

Feature usefulness must be evaluated over time.

A feature that is powerful during 2021 but useless afterward should not automatically remain in production.

Feature performance should be measured by:

* Year
* Market regime
* Asset
* Volatility state
* Liquidity state

⸻

23. Feature Leakage Protection

Feature generation must obey strict causal timing.

For every feature:

Feature Timestamp ≤ Decision Timestamp

The system must reject:

* Centered rolling windows
* Future normalization
* Future regime labels
* Retrospective wallet labels where PIT unsafe
* Future extrema
* Forward-filled future information

⸻

24. Probability Calibration

Raw model scores must not automatically be treated as confidence probabilities.

A model output of:

0.82

does not necessarily mean:

82% probability of success.

Probability calibration must therefore be measured.

Candidate methods include:

* Platt / Sigmoid calibration
* Isotonic calibration
* Other validated calibration methods

Calibration must use unseen data.

⸻

25. Calibration Evaluation

The system should maintain:

Reliability Diagrams

and metrics such as:

Brier Score

alongside appropriate discrimination metrics.

Example:

Predictions around:

70%

should empirically correspond to approximately the defined 70% outcome frequency if the probability is well calibrated.

Calibration quality should be monitored continuously.

⸻

26. Confidence Is Not Leverage

This rule is mandatory:

Model confidence must never map directly to leverage.

Example:

95% confidence ≠ 20× leverage

Leverage is determined by the independent Risk Engine using:

* Volatility
* Stop distance
* Liquidity
* Position size
* Portfolio exposure
* Correlation
* Drawdown
* Liquidation distance
* Risk budget

⸻

27. Uncertainty Engine

The system should estimate uncertainty separately from directional prediction.

Potential approaches include:

* Model disagreement
* Ensemble dispersion
* Bootstrap variation
* Predictive intervals
* Quantile models
* Distributional models
* Out-of-distribution detection

High uncertainty should reduce willingness to trade.

⸻

28. Out-of-Distribution Detection

The AI should recognize when current market conditions differ materially from its historical training environment.

Potential signals include:

* Extreme feature values
* Novel correlation structure
* Abnormal volatility
* Unusual liquidity
* Feature-distribution shifts

When the system encounters unfamiliar conditions:

Confidence must decrease.

Potential response:

NO TRADE

or:

SAFE MODE

⸻

29. Ensemble Architecture

The production intelligence layer should combine multiple sources of evidence.

Conceptually:

Trend Model

Momentum Model

Order Flow Model

Derivatives Model

Regime Model

Cross-Market Model

Optional On-Chain Model

↓

Ensemble Engine

The ensemble may use:

* Weighted voting
* Probability averaging
* Stacking
* Meta-modeling
* Regime-dependent weighting

The best approach must be empirically validated.

⸻

30. Dynamic Ensemble Weights

Model weights should not necessarily remain constant.

Example:

During:

Strong Trend

Trend models may receive greater influence.

During:

Range

Mean-reversion models may become more relevant.

During:

High Volatility

Some strategies may be disabled completely.

Therefore:

Market Regime → Strategy Eligibility + Strategy Weight

should be researched.

⸻

31. Strategy Eligibility

The Regime Engine should be capable of determining which strategies are allowed to operate.

Example:

Trend Strategy

Allowed:

Bull Trend / Bear Trend

Restricted:

Range

Mean Reversion

Allowed:

Range / Stable Volatility

Restricted:

Breakout / Panic

This prevents every strategy from trading every environment.

⸻

32. Strategy Tournament

Validated strategies should compete continuously.

The platform will maintain:

Champion Strategies

and:

Challenger Strategies

Challengers may operate in:

Shadow Mode

without real capital.

Their performance is compared against production strategies.

Capital allocation should favor strategies with stronger validated and live evidence.

⸻

33. Strategy Decay Detection

A profitable strategy may stop working.

The system must monitor:

Expected Performance

vs.

Observed Live Performance

Metrics may include:

* Win Rate
* Expectancy
* Sharpe
* Drawdown
* Calibration
* Slippage
* Signal frequency
* Feature distributions

Significant degradation triggers:

Allocation Reduction

then potentially:

Suspension

⸻

34. Concept Drift

Financial markets are non-stationary.

Relationships can change.

The system must therefore monitor changes in:

* Feature distributions
* Target distributions
* Correlations
* Volatility
* Liquidity
* Model error
* Probability calibration

Model retraining should be driven by validated policy rather than blindly scheduled retraining alone.

⸻

35. Retraining Architecture

Potential policies include:

Scheduled

Retrain periodically.

Rolling Window

Train only on the latest historical window.

Expanding Window

Continuously add new history.

Drift-Triggered

Retrain when meaningful distribution or performance changes are detected.

Hybrid

Combine scheduled and drift-triggered retraining.

The correct policy must be experimentally determined.

⸻

36. Model Registry

Every model receives a permanent identity.

Example:

MODEL-SOL-META-0047

Metadata includes:

* Model family
* Model version
* Dataset version
* Feature version
* Training period
* Validation period
* Hyperparameters
* Code commit
* Calibration model
* Performance
* Approval status

No anonymous model may enter production.

⸻

37. Model Lifecycle

Each model moves through:

EXPERIMENTAL

↓

CANDIDATE

↓

VALIDATED

↓

SHADOW

↓

LIMITED LIVE

↓

PRODUCTION

and potentially:

DEGRADED

↓

SUSPENDED

↓

RETIRED

⸻

38. Champion / Challenger Framework

Production models become:

Champions

New candidates become:

Challengers

Challengers receive identical live market information but do not necessarily execute capital.

Their decisions are recorded.

After sufficient evidence:

Challenger > Champion

may justify promotion.

Promotion must pass statistical and risk review.

⸻

39. Explainability

Every trade candidate should expose understandable evidence.

Example:

SOL — LONG

Regime: Bull Trend

Probability: 67%

Evidence:

Trend: Positive

Momentum: Strong

Order Flow: Positive

Funding: Neutral

Open Interest: Constructive

BTC Context: Positive

Volatility: Acceptable

Decision: Candidate Trade

The user should not receive:

“AI says buy.”

⸻

40. Explanation Integrity

Explanations must reflect actual model inputs and decision logic.

The system must not generate plausible-sounding explanations after the decision that were unrelated to the model.

This is particularly important if an LLM is later used to translate quantitative decisions into natural language.

The explanation layer must consume actual recorded decision evidence.

⸻

41. Role of Large Language Models

An LLM should not initially be the primary trading model.

LLMs may instead be useful for:

* Explaining decisions
* Summarizing market state
* Research assistance
* Interpreting model diagnostics
* Generating human-readable reports
* Interface interaction

The quantitative trading decision should originate from validated numerical models and strategy logic.

⸻

42. LLM Isolation

If an LLM is introduced, it must not independently issue executable orders.

Architecture:

Quantitative Engine

↓

Structured Decision

↓

LLM Explanation Layer

The LLM may explain:

why

but must not silently change:

what

the quantitative system decided.

⸻

43. Adversarial Model Testing

Candidate models should be tested under intentionally hostile conditions.

Examples:

* Missing features
* Delayed features
* Extreme values
* Distribution shift
* Corrupted data
* Sudden volatility
* Liquidity collapse

The system must fail safely.

⸻

44. Missing Feature Policy

Models must define behavior when a required feature disappears.

Possible policies:

Fallback Model

Reduced Feature Model

NO TRADE

Critical features must never be silently replaced with arbitrary values.

⸻

45. Model Agreement

The Ensemble Engine should track agreement between models.

Example:

Trend: Long

Momentum: Long

Order Flow: Long

Derivatives: Neutral

Regime: Supportive

may represent strong agreement.

Whereas:

Trend: Long

Momentum: Short

Order Flow: Neutral

Derivatives: Short

represents disagreement.

High disagreement should increase uncertainty.

⸻

46. Expected Value Layer

The final trading decision should not be based solely on probability.

Conceptually:

Expected Value = Probability-Weighted Reward − Probability-Weighted Loss − Trading Costs

A trade with:

high win probability

can still have negative expected value.

The system should prefer positive expected value rather than high Win Rate.

⸻

47. Cost-Aware Prediction

Where practical, the decision layer should account for:

* Fees
* Spread
* Expected slippage
* Funding
* Expected market impact

before classifying an opportunity as tradeable.

The relevant question is:

Is the expected edge large enough to survive execution?

⸻

48. NO TRADE Zone

The Decision Engine should maintain an explicit uncertainty/edge zone.

Conceptually:

Strong Negative Edge → SHORT

Insufficient Edge → NO TRADE

Strong Positive Edge → LONG

The thresholds must be optimized for:

out-of-sample net risk-adjusted performance

not trading frequency.

⸻

49. Prediction Logging

Every prediction must be recorded.

Including predictions that do not become trades.

Required fields include:

* Timestamp
* Asset
* Model version
* Features
* Regime
* Prediction
* Probability
* Uncertainty
* Strategy votes
* Final decision
* Risk rejection if applicable
* Subsequent outcome

This dataset will later become extremely valuable for model evaluation.

⸻

50. Counterfactual Logging

When the Risk Engine rejects an AI trade, the system should continue tracking what would have happened.

Example:

AI: LONG SOL

Risk Engine: REJECTED

The platform later records:

Hypothetical Outcome

This enables us to evaluate:

* AI quality
* Risk Engine quality
* Missed opportunities
* Avoided losses

without exposing capital.

⸻

51. Decision Attribution

Every trading outcome should eventually be attributable across the pipeline.

Example:

Signal Quality

Risk Sizing

Execution

Exit Logic

This prevents incorrectly blaming the AI for a loss caused primarily by poor execution or blaming execution for a weak signal.

⸻

52. Online Learning Policy

Direct unrestricted online learning from live trades is prohibited initially.

The model must not automatically modify itself after every win or loss.

This could create unstable feedback loops.

Instead:

Live Data

↓

Research Dataset

↓

Controlled Retraining

↓

Validation

↓

Shadow

↓

Promotion

Only later should more adaptive learning mechanisms be researched.

⸻

53. Reinforcement Learning

Reinforcement Learning should not be part of the initial production system.

It may later be researched for:

* Execution optimization
* Dynamic order placement
* Portfolio allocation
* Sequential position management

However, RL introduces substantial simulation and reward-design risk.

It must prove superiority against simpler approaches before deployment.

⸻

54. AI Safety Boundary

The AI Engine may:

* Generate predictions
* Estimate probability
* Classify regimes
* Score opportunities
* Rank signals
* Recommend trade candidates

The AI Engine may not:

* Override portfolio risk
* Override maximum leverage
* Override drawdown limits
* Disable the Kill Switch
* Ignore stale data
* Increase its own capital allocation
* Promote itself to production

This boundary is architectural, not merely procedural.

⸻

55. Initial Model Stack

The recommended research sequence is:

Stage A

Statistical Baselines

Stage B

Logistic / Regularized Models

Stage C

LightGBM + XGBoost

Stage D

Specialized Strategy Models

Stage E

Meta-Labeling

Stage F

Regime-Aware Ensemble

Stage G

Sequence Models

Stage H

Transformer / Advanced Deep Learning

Every stage must beat relevant previous baselines to justify additional complexity.

⸻

56. Initial Production Candidate

The current preferred first serious AI candidate is:

Regime Engine

Specialized Strategy Signals

LightGBM / XGBoost Meta-Model

Probability Calibration

Ensemble Decision Layer

This architecture is intentionally less glamorous than immediately deploying a Transformer.

It is also easier to:

* Validate
* Debug
* Explain
* Retrain
* Stress-test
* Compare

Advanced neural models can then attempt to defeat this baseline.

⸻

57. Production Decision Object

The AI layer should return a structured object conceptually containing:

Asset

Timestamp

Direction

Tradeability

Expected Return

Expected Downside

Probability

Uncertainty

Market Regime

Holding Horizon

Strategy Agreement

Data Quality

Model Version

Feature Version

Rationale Evidence

This object is passed to the Risk Engine.

⸻

58. AI Performance Metrics

AI evaluation must include more than trading P&L.

Prediction-level metrics may include:

* Precision
* Recall
* ROC-AUC where appropriate
* PR-AUC where appropriate
* Log Loss
* Brier Score
* Calibration Error
* Rank correlation
* Directional accuracy
* Expected-value accuracy

Trading-level evaluation includes:

* Net Expectancy
* Sharpe
* Sortino
* Drawdown
* Profit Factor
* Tail Risk
* Stability

A model can have good classification accuracy and still be a bad trading model.

⸻

59. Model Evaluation by Confidence

Performance should be decomposed by confidence bucket.

Example:

50–55%

55–60%

60–65%

65–70%

70–80%

80%+

If higher reported confidence does not correspond to stronger realized outcomes, the confidence system is unreliable.

⸻

60. Model Evaluation by Regime

Every model must be evaluated independently across:

Bull

Bear

Range

High Volatility

Low Volatility

Liquidity Stress

This reveals hidden regime dependence.

⸻

61. Model Evaluation by Asset

Performance must also be decomposed by:

BTC

ETH

SOL

BNB

A shared model must demonstrate that shared learning improves rather than damages asset-specific performance.

⸻

62. AI Promotion Gate

No AI model can reach production without passing:

Point-in-Time Validation

Leakage Testing

Out-of-Sample Testing

Walk-Forward Testing

Cost-Adjusted Backtesting

Probability Calibration

Stress Testing

Regime Analysis

Asset Analysis

Ablation Testing

Shadow Trading

Limited-Capital Validation

Failure of a critical gate blocks promotion.

⸻

63. AI Architecture

The resulting architecture is:

Historical Data Engine

Real-Time Market Data

↓

Feature Engine

↓

Market Regime Engine

↓

┌──────────────────────────────┐

Trend Intelligence

Momentum Intelligence

Order Flow Intelligence

Derivatives Intelligence

Volatility Intelligence

Cross-Market Intelligence

Validated On-Chain Intelligence

└──────────────────────────────┘

↓

Base Signals

↓

Meta-Model

↓

Regime-Aware Ensemble

↓

Probability Calibration

↓

Uncertainty Engine

↓

Expected Value Engine

↓

LONG / SHORT / NO TRADE

↓

Risk Engine

⸻

64. Strategic Learning Loop

The complete learning loop becomes:

Observe

↓

Predict

↓

Risk Evaluate

↓

Execute or Reject

↓

Observe Outcome

↓

Attribute Outcome

↓

Store

↓

Research

↓

Retrain

↓

Validate

↓

Shadow

↓

Promote or Reject

The system learns through controlled research rather than uncontrolled self-modification.

⸻

65. Phase 5 Deliverables

Implementation must eventually produce:

Feature Engine

Regime Detection Engine

Baseline Model Suite

Strategy Model Framework

Meta-Labeling Engine

Ensemble Engine

Probability Calibration Engine

Uncertainty Engine

Expected Value Engine

Model Registry

Champion/Challenger Framework

Drift Detection

Strategy Decay Detection

Prediction Logger

Counterfactual Logger

Explainability Layer

AI Promotion Pipeline

⸻

66. Phase 5 Acceptance Gate

Phase 5 will not be considered complete merely because an AI model exists.

It must demonstrate that:

1. Strong non-AI baselines exist.
2. AI models are compared against those baselines.
3. Probabilities are calibrated.
4. Market regime is represented.
5. Uncertainty is explicitly modeled.
6. NO TRADE is a native output.
7. Model decisions are reproducible.
8. Model versions are registered.
9. Predictions are permanently logged.
10. Drift can be detected.
11. Strategy degradation can trigger suspension.
12. AI cannot bypass the Risk Engine.
13. Model complexity is justified by out-of-sample evidence.
14. Production promotion requires Shadow and Limited-Live validation.

⸻

67. Critical Design Decision

The project will not begin with:

One Giant AI Predicting Crypto Prices.

The initial architecture will instead be:

A regime-aware ensemble of independently testable quantitative intelligence models, governed by calibrated probability, uncertainty estimation, expected value, and an independent Risk Engine.

This provides a stronger foundation for scientific validation and future expansion.

⸻

68. Long-Term AI Direction

If sufficient proprietary historical and live data is accumulated, future research may investigate:

* Cross-asset Transformers
* Self-supervised market representations
* Multi-modal market models
* Learned order-book representations
* Adaptive mixture-of-experts
* Distributional forecasting
* Execution RL
* Portfolio RL
* Online adaptation
* Foundation models for financial time series

These are research directions.

They are not assumptions built into Version 1.

⸻

69. Final Principle

The most sophisticated model is not automatically the best model.

The production winner is the model that demonstrates the strongest combination of:

Predictive Edge

Calibration

Robustness

Stability

Execution Viability

Risk-Adjusted Performance

Operational Reliability

If a simple LightGBM model consistently defeats a Transformer under these criteria:

LightGBM wins.

If the Transformer later proves a durable incremental advantage:

the Transformer earns deployment.

Production capital follows evidence, not technological fashion.

⸻

Phase 5 Decision

APPROVED AS AI/ML RESEARCH ARCHITECTURE

The AI Engine will remain strictly separated from capital-control authority.

The next phase is:

Phase 6 — Risk Engine & Execution Architecture

This phase will define the system responsible for converting validated AI opportunities into controlled real-world positions while protecting capital against model errors, execution failures, leverage risk, liquidation risk, correlated exposure, exchange/API failures, and extreme market events.

⸻

Document: Strategy Intelligence & AI/ML Architecture Specification
Version: 1.0
Phase: 5
Core Assets: BTC / ETH / SOL / BNB
Next Phase: Risk Engine & Execution Architecture