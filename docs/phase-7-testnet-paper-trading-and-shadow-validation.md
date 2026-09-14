Testnet, Paper Trading & Shadow Validation Specification

Version: 1.0
Phase: 7 — Testnet, Paper Trading & Shadow Validation
Core Assets: BTC, ETH, SOL, BNB
System: AI-Powered Automated Trading Platform
Status: Pre-Capital Validation Architecture
Criticality: Maximum

⸻

1. Purpose

Phase 7 is the transition between historical research and real-capital deployment.

Its purpose is to determine whether the complete trading system behaves correctly when exposed to live market conditions.

The system must prove not only that its strategies remain statistically useful, but that:

* Live data arrives correctly
* Features are generated correctly
* AI decisions remain stable
* Risk rules operate correctly
* Orders are constructed correctly
* Exchange state is reconciled correctly
* Latency remains acceptable
* Data quality is maintained
* Execution assumptions remain realistic
* Backtest expectations remain consistent with live observations

No meaningful real capital is permitted during this phase.

⸻

2. Validation Ladder

The mandatory progression is:

Historical Backtest

↓

Out-of-Sample Validation

↓

Walk-Forward Validation

↓

Stress Testing

↓

Testnet

↓

Paper Trading

↓

Shadow Trading

↓

Limited-Capital Live Trading

Each stage has a different purpose.

Passing one stage does not automatically imply passing the next.

⸻

3. Fundamental Principle

Historical validation answers:

Would the strategy have worked under our reconstructed historical assumptions?

Phase 7 asks:

Does the entire system behave correctly when reality begins supplying the data?

This distinction is critical.

⸻

4. Three Validation Environments

The platform will maintain three separate pre-capital environments.

Environment A — Testnet

Primary objective:

Infrastructure correctness

Environment B — Paper Trading

Primary objective:

Live strategy behavior without capital

Environment C — Shadow Trading

Primary objective:

Production-equivalent decision validation without execution

Each environment must maintain separate credentials, logs, databases, and performance reports where appropriate.

⸻

5. Stage A — Testnet

Testnet should be used primarily to validate exchange integration and execution infrastructure.

The system should verify:

* Authentication
* API wallet functionality
* Order submission
* Order cancellation
* Order modification
* Position creation
* Position reduction
* Position closure
* Stop Loss
* Take Profit
* Partial fills where reproducible
* Reconciliation
* WebSocket subscriptions
* API recovery
* Rate-limit behavior
* Client Order IDs
* Dead-Man’s Switch
* Kill Switch

⸻

6. What Testnet Does Not Prove

Testnet profitability must not be treated as evidence of trading edge.

Testnet may differ materially from production in:

* Liquidity
* Participants
* Order-book depth
* Spread
* Volatility
* Market impact
* Fill probability

Therefore:

Testnet validates plumbing, not alpha.

⸻

7. Testnet Execution Matrix

Every supported order behavior must receive an automated test.

Examples:

Market Long

Market Short

Limit Long

Limit Short

Cancel Order

Replace Order

Partial Position Close

Full Position Close

Stop Trigger

Take Profit Trigger

Reduce-Only Order

Expired Intent

Rejected Order

Duplicate Request

Each test produces a deterministic expected outcome.

⸻

8. Testnet Failure Injection

The system must deliberately create failure conditions.

Examples:

* Disconnect WebSocket
* Interrupt REST access
* Introduce API timeout
* Send duplicate request
* Expire execution intent
* Delay market data
* Restart Execution Engine
* Restart Risk Engine
* Restart database connection
* Create internal/exchange position mismatch

The objective is to verify safe recovery.

⸻

9. Restart Recovery

The platform must be able to restart while positions or orders exist.

After restart:

Connect to Venue

↓

Retrieve Orders

↓

Retrieve Positions

↓

Compare Internal State

↓

Reconcile

↓

Recalculate Risk

↓

Resume or Enter Safe Mode

Local memory must never be assumed to represent exchange truth after restart.

⸻

10. Testnet Acceptance Gate

Testnet passes only when:

* Order lifecycle works
* Position lifecycle works
* Protective orders work
* Reconciliation works
* Restart recovery works
* Duplicate-order protection works
* Dead-Man’s Switch works
* Kill Switch works
* Failure scenarios produce safe behavior
* Audit logs reconstruct every event

Profitability is irrelevant to this gate.

⸻

11. Stage B — Paper Trading

Paper Trading operates on:

Real Live Market Data

but uses:

Simulated Capital

No actual trading order reaches the production venue.

The complete strategy stack should operate normally:

Live Data

↓

Feature Engine

↓

Regime Engine

↓

AI / Strategies

↓

Risk Engine

↓

Simulated Execution

↓

Simulated Portfolio

⸻

12. Paper Execution Simulator

The Paper Engine must not assume:

Signal Price = Fill Price

It should estimate:

* Spread
* Slippage
* Fees
* Funding
* Order delay
* Available liquidity
* Partial fills where possible

The simulator should consume live order-book information whenever available.

⸻

13. Paper Capital

Paper Trading should operate using realistic hypothetical account sizes.

Multiple capital profiles may be tested simultaneously.

Example:

Small Account

Medium Account

Large Account

This allows capacity effects to be measured before real deployment.

⸻

14. Live Feature Verification

Every feature produced live should be compared against its historical implementation.

For identical source information:

Historical Feature Function

and:

Live Feature Function

should produce equivalent results within defined tolerances.

This prevents:

Training-Serving Skew

⸻

15. Live Data Latency

The system must measure:

Exchange Event Time

↓

Ingestion Time

↓

Feature Time

↓

Prediction Time

↓

Risk Decision Time

↓

Simulated Execution Time

Latency distributions should be recorded rather than only averages.

Required metrics include:

* Median
* P95
* P99
* Maximum observed

⸻

16. Data Freshness

Every decision must know the age of its inputs.

Example:

Price Age

Order Book Age

Funding Age

OI Age

On-Chain Feature Age

If a critical feature exceeds its permitted freshness threshold:

NO TRADE

⸻

17. Prediction Logging

Every live AI prediction must be stored.

Not only executed paper trades.

Required records include:

* Timestamp
* Asset
* Regime
* Model version
* Feature version
* Direction
* Probability
* Uncertainty
* Expected value
* Strategy votes
* Final decision
* Risk decision

This creates a complete live prediction history.

⸻

18. NO TRADE Logging

NO TRADE decisions must also be retained.

This allows later analysis of:

* Avoided losses
* Missed opportunities
* Confidence thresholds
* Opportunity frequency

Without this data, selection bias can appear in live evaluation.

⸻

19. Paper Trading Evaluation

Paper results must be compared against historical expectations.

Metrics include:

* Signal frequency
* Trade frequency
* Win Rate
* Expectancy
* Average win
* Average loss
* Sharpe
* Drawdown
* Holding time
* Exposure
* Funding cost
* Simulated slippage
* Strategy distribution
* Regime distribution

⸻

20. Expected vs Observed

Every strategy should maintain an expected performance envelope derived from historical validation.

Paper performance is compared against this envelope.

Example:

Expected Trade Frequency

versus:

Observed Trade Frequency

Expected Win Rate Range

versus:

Observed Win Rate

Expected Drawdown Distribution

versus:

Observed Drawdown

Significant divergence requires investigation.

⸻

21. Statistical Patience

The system must not declare success after a small number of profitable trades.

Example:

10 profitable trades

is not sufficient evidence.

The required observation period depends on:

* Strategy frequency
* Statistical power
* Market regimes encountered
* Number of independent observations

No universal number of days or trades will be arbitrarily declared sufficient.

⸻

22. Minimum Evidence Principle

Promotion decisions should be based on whether enough evidence exists to meaningfully compare:

Observed Live Behavior

against:

Expected Historical Behavior

A low-frequency strategy may require substantially more calendar time than a high-frequency strategy.

⸻

23. Regime Coverage

Paper validation should ideally observe multiple market regimes.

Examples:

* Trend
* Range
* High volatility
* Low volatility

If only one regime has occurred during testing, the strategy should not automatically be assumed validated for all environments.

⸻

24. Paper Failure Analysis

Every material discrepancy must be classified.

Possible causes:

Model Problem

Data Problem

Feature Problem

Execution Simulation Problem

Risk Problem

Market Regime Difference

Infrastructure Problem

This attribution is essential before changing the strategy.

⸻

25. Stage C — Shadow Trading

Shadow Trading is the most important pre-capital stage.

The complete production system operates against live production market data.

It behaves as though it were authorized to trade.

However:

Actual production orders are not submitted.

⸻

26. Shadow Decision Flow

Production Market Data

↓

Production Feature Engine

↓

Production AI

↓

Production Risk Engine

↓

Production Execution Decision

↓

STOP BEFORE ORDER SUBMISSION

↓

Shadow Fill Estimation

↓

Shadow Position

↓

Outcome Tracking

This brings the system extremely close to live operation without exposing capital.

⸻

27. Production Equivalence

Shadow infrastructure should be as close as practical to future production infrastructure.

Ideally:

Same code

Same models

Same features

Same risk rules

Same execution logic

Same infrastructure topology

with only the final order-routing permission disabled.

This minimizes the difference between Shadow and Live.

⸻

28. Shadow Order Intent

The Execution Engine should still generate the exact order it would have submitted.

Example:

Asset: ETH

Direction: SHORT

Order: LIMIT

Price: X

Size: Y

Stop: Z

TP: Q

Intent Time: T

The order is recorded but not transmitted.

⸻

29. Counterfactual Fill Engine

After creating a Shadow Order, the system should determine whether that order would likely have filled.

This should use subsequent live:

* Trades
* Quotes
* L2 Order Book
* Price movement

where available.

The system must not automatically assume every Shadow Limit Order filled.

⸻

30. Conservative Shadow Fills

Where exact fill certainty cannot be established, Shadow simulation should prefer conservative assumptions.

Optimistic shadow fills can create false confidence immediately before real-capital deployment.

⸻

31. Shadow Execution Metrics

The platform should estimate:

* Expected fill price
* Fill probability
* Slippage
* Spread cost
* Fill latency
* Partial fill
* Funding
* Position outcome

These estimates should later be compared with actual Limited-Live fills.

⸻

32. Shadow Risk Validation

The Risk Engine should behave exactly as it would with capital.

If the AI proposes a trade:

Risk Engine may reject it.

Rejected trades remain tracked counterfactually.

This allows separate measurement of:

AI Value

and:

Risk Engine Value

⸻

33. Risk Counterfactual Analysis

For every rejected signal:

Track:

What would have happened if Risk had approved it?

For every approved signal:

Track:

What happened under the approved size?

This allows evaluation of whether the Risk Engine:

* Avoided losses
* Reduced excessive exposure
* Missed profitable opportunities
* Improved risk-adjusted performance

⸻

34. Strategy Counterfactual Analysis

The same infrastructure can compare inactive strategies.

Example:

Champion

runs in production-equivalent Shadow mode.

Challenger A

Challenger B

Challenger C

receive identical live data.

This creates a live Strategy Tournament.

⸻

35. Model Calibration in Live Data

Historical probability calibration must be tested again under live observations.

Example:

Signals predicted around:

60%

70%

80%

should be evaluated separately.

If confidence becomes systematically overconfident in live markets:

the model must not progress.

⸻

36. Prediction Drift

The system should monitor changes in:

* Prediction distribution
* Confidence distribution
* Feature distributions
* Regime frequency
* Signal frequency

Example:

Historical:

NO TRADE = 65%

Live:

NO TRADE = 10%

may indicate a significant problem.

⸻

37. Feature Drift

For every important feature, compare:

Training Distribution

vs.

Live Distribution

Metrics may include:

* Mean shift
* Variance shift
* Quantile shift
* Distribution distance

Material drift should be investigated.

⸻

38. Concept Drift

Feature distributions may remain stable while the relationship between features and outcomes changes.

Therefore the platform must also monitor:

Prediction → Outcome Relationship

This is more difficult and usually requires accumulated live observations.

⸻

39. Live Calibration Decay

A model may remain directionally useful while its confidence becomes unreliable.

Example:

Historical:

70% confidence → ~70% defined outcome rate

Live:

70% confidence → ~54%

This should trigger:

Calibration Warning

and potentially:

Allocation Reduction

⸻

40. Backtest-to-Live Gap

One of the central Phase 7 metrics is:

Backtest-to-Live Gap

It measures differences between expected and observed behavior.

Components may include:

* Return gap
* Sharpe gap
* Win Rate gap
* Expectancy gap
* Slippage gap
* Trade-frequency gap
* Drawdown gap
* Calibration gap

Large unexplained gaps block promotion.

⸻

41. Execution Assumption Validation

Shadow Trading should determine whether the execution assumptions used during Phase 4 were realistic.

Example:

Backtest assumed:

4 bps slippage

Shadow observations suggest:

11 bps

The historical strategy must then be rerun using the improved assumption.

This creates a feedback loop:

Live Observation

↓

Execution Model Update

↓

Backtest Revalidation

⸻

42. No Goalpost Moving

When live results disappoint, researchers must not casually modify:

* Strategy
* Thresholds
* Stop
* Take Profit
* Features
* Models

and continue counting the same validation period.

A material change creates:

A New Strategy Version

and:

A New Validation Cycle

This prevents live overfitting.

⸻

43. Freeze Before Validation

Before a formal Shadow Validation run:

the following should be frozen:

* Model version
* Strategy version
* Feature version
* Risk version
* Execution assumptions

This creates a true forward test.

⸻

44. Shadow Cohort

A formal Shadow run receives a unique identifier.

Example:

SHADOW-2027-001

It records:

* Start date
* End date
* Models
* Strategies
* Risk configuration
* Assets
* Capital assumptions
* Infrastructure version

Results are permanently retained.

⸻

45. Operational Reliability

Phase 7 must also measure system uptime and reliability.

Metrics include:

* Market-data uptime
* Prediction uptime
* Risk Engine uptime
* Execution Engine uptime
* Database availability
* WebSocket reconnect frequency
* API error rate

A profitable strategy running on unstable infrastructure is not ready.

⸻

46. Incident Registry

Every operational incident must be recorded.

Example:

INC-0042

Type:

WebSocket disconnect

Duration:

X

Impact:

ETH Order Book stale

Response:

New trades frozen

Recovery:

Reconciliation completed

This creates an engineering reliability history.

⸻

47. Severity Levels

Incidents may be classified:

SEV-1

Potential capital-threatening failure.

SEV-2

Major trading impairment.

SEV-3

Degraded service.

SEV-4

Minor operational issue.

SEV-1 events require formal review before promotion.

⸻

48. Incident Replay

Important incidents should be reproducible in simulation.

If a real Shadow outage reveals a weakness:

the scenario should become a permanent automated test.

Thus:

Every serious failure makes the system harder to break next time.

⸻

49. Shadow Risk Dashboard

Live monitoring should show:

Shadow Equity

Shadow P&L

Drawdown

Open Shadow Positions

Portfolio Exposure

Asset Exposure

Strategy Exposure

Crypto Beta

Risk Rejections

AI Predictions

Calibration

Execution Quality

System Health

⸻

50. Daily Validation Report

The system should automatically produce a daily research report.

Contents include:

Signals Generated

Trades Approved

Trades Rejected

NO TRADE Count

P&L

Drawdown

Execution Estimates

Model Drift

Feature Drift

Risk Events

System Incidents

The purpose is operational visibility, not daily strategy modification.

⸻

51. Weekly Validation Review

A deeper weekly review should examine:

* Expected vs observed performance
* Model calibration
* Regime performance
* Asset performance
* Risk Engine contribution
* Execution assumptions
* Incidents
* Drift
* Strategy degradation

⸻

52. Promotion Is Not Based on Profit Alone

A profitable Shadow period can still fail validation.

Examples:

Profitable but severe calibration failure

Profitable but unrealistic fills

Profitable but infrastructure instability

Profitable but unacceptable drawdown

Profitable due to one extreme trade

All may block progression.

⸻

53. Shadow Acceptance Dimensions

A candidate must be evaluated across five dimensions:

Alpha

Does the strategy retain evidence of edge?

Risk

Does the Risk Engine behave correctly?

Execution

Are assumed fills realistic?

Reliability

Does infrastructure remain stable?

Consistency

Are live observations reasonably consistent with historical expectations?

⸻

54. Statistical Acceptance

No single universal Sharpe, Win Rate, or return threshold will be hard-coded during architecture design.

Acceptance thresholds must derive from:

* Strategy characteristics
* Historical distribution
* Number of observations
* Statistical uncertainty
* Risk profile

The system must avoid arbitrary vanity targets.

⸻

55. Practical Acceptance

Regardless of strategy statistics, certain conditions are mandatory:

Zero unresolved critical reconciliation errors

Zero uncontrolled duplicate orders

Zero unexplained future-data leakage

Zero unprotected simulated positions caused by system logic

Kill Switch verified

Safe Mode verified

Data freshness protection verified

⸻

56. Promotion Gate to Real Capital

A strategy may proceed to Limited-Capital Live Trading only if:

1. Phase 4 validation remains valid.
2. Phase 5 model requirements remain valid.
3. Phase 6 Risk Engine requirements pass.
4. Testnet execution passes.
5. Paper behavior is consistent with expectations.
6. Shadow behavior is consistent with expectations.
7. Backtest-to-Live Gap is understood.
8. Live calibration is acceptable.
9. Execution assumptions are validated.
10. No unresolved critical infrastructure issue exists.
11. No unresolved critical data-quality issue exists.
12. Kill Switch and Safe Mode are verified.
13. Strategy version has remained frozen during formal validation.
14. Sufficient forward evidence exists.

Only then can the strategy become:

LIMITED-LIVE ELIGIBLE

⸻

57. Limited-Live Capital Is a New Experiment

Passing Shadow does not mean:

Production Approved.

It means:

Eligible for a controlled real-money experiment.

The next phase introduces:

* Real fills
* Real fees
* Real funding
* Real slippage
* Real psychological/operational consequences
* Real venue behavior

Therefore it receives its own validation gate.

⸻

58. Phase 7 Architecture

The complete architecture is:

Historical Validation

↓

TESTNET

Infrastructure correctness

↓

PAPER TRADING

Live strategy simulation

↓

SHADOW TRADING

Production-equivalent forward validation

↓

Performance Comparison

Calibration

Drift Detection

Execution Validation

Risk Validation

Reliability Validation

↓

PROMOTION GATE

↓

If Failed:

Research / Fix / New Version / Restart Validation

If Passed:

LIMITED-CAPITAL LIVE ELIGIBLE

⸻

59. Learning Feedback Loop

Phase 7 creates a critical feedback loop:

Historical Assumption

↓

Live Observation

↓

Difference Detected

↓

Root Cause Analysis

↓

Model / Execution / Data Improvement

↓

Historical Revalidation

↓

New Frozen Version

↓

New Forward Validation

This process continues until the system demonstrates acceptable convergence between research and reality.

⸻

60. Phase 7 Deliverables

Implementation must produce:

Testnet Environment

Paper Trading Engine

Shadow Trading Engine

Counterfactual Fill Engine

Live Prediction Logger

NO TRADE Logger

Live Feature Validator

Latency Monitor

Data Freshness Monitor

Drift Detection System

Calibration Monitor

Backtest-to-Live Gap Analyzer

Incident Registry

Shadow Performance Dashboard

Daily Validation Report

Weekly Validation Review

Promotion Gate

⸻

61. Phase 7 Acceptance Gate

Phase 7 is considered complete only when the complete trading stack has demonstrated:

* Correct exchange integration
* Correct live feature generation
* Stable live predictions
* Correct Risk Engine behavior
* Correct execution-intent generation
* Realistic fill assumptions
* Controlled failure behavior
* Successful reconciliation
* Acceptable infrastructure reliability
* Acceptable model calibration
* Acceptable drift behavior
* Understood backtest-to-live differences
* Successful formal Shadow Validation

No real capital is introduced before these requirements are satisfied.

⸻

62. Strategic Principle

The purpose of Phase 7 is not to prove that the system works.

It is to give reality repeated opportunities to prove that the system does not work.

Every discrepancy is investigated.

Every failure becomes data.

Every infrastructure incident becomes a future test.

Every unrealistic assumption is corrected.

Only after the system survives this process should capital be exposed.

⸻

Phase 7 Decision

APPROVED AS PRE-CAPITAL VALIDATION ARCHITECTURE

The next stage is:

Phase 8 — Limited-Capital Live Trading & Production Qualification

Phase 8 will introduce real capital for the first time under deliberately restrictive risk limits.

Its objective will not be maximizing return.

Its objective will be determining whether the system’s historical, Paper, and Shadow behavior survives contact with real execution.

⸻

Document: Testnet, Paper Trading & Shadow Validation Specification
Version: 1.0
Phase: 7
Core Assets: BTC / ETH / SOL / BNB
Next Phase: Limited-Capital Live Trading & Production Qualification