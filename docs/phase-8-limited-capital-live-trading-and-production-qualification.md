Limited-Capital Live Trading & Production Qualification Specification

Version: 1.0
Phase: 8 — Limited-Capital Live Trading & Production Qualification
Core Assets: BTC, ETH, SOL, BNB
Primary Instrument: Perpetual Futures
Initial Execution Venue: Hyperliquid, subject to final venue validation
Status: Real-Capital Validation Architecture
Criticality: Maximum

⸻

1. Purpose

Phase 8 introduces real capital for the first time.

Its purpose is NOT to maximize profit.

Its purpose is to determine whether the trading system’s validated historical, Paper and Shadow behavior survives contact with:

* Real orders
* Real fills
* Real fees
* Real funding
* Real slippage
* Real latency
* Real liquidity
* Real exchange state
* Real margin mechanics
* Real operational failures

Phase 8 is therefore:

A controlled production experiment using deliberately limited capital.

The principal objective is to measure the difference between simulated reality and actual reality.

⸻

2. Fundamental Rule

Passing Shadow Trading does not mean:

PRODUCTION READY

It means:

ELIGIBLE FOR LIMITED LIVE VALIDATION

No strategy receives meaningful capital simply because Phase 7 was successful.

⸻

3. Phase 8 Objective Hierarchy

Success is evaluated in the following order:

Priority 1

Capital Safety

Priority 2

Execution Correctness

Priority 3

System Reliability

Priority 4

Shadow-to-Live Consistency

Priority 5

Risk-Model Accuracy

Priority 6

Alpha Persistence

Priority 7

Profitability

Profitability intentionally appears last.

⸻

4. Limited Capital Principle

Initial live capital must be deliberately small relative to:

* Available project capital
* Personal risk tolerance
* Strategy capacity
* Exchange liquidity

The purpose is to purchase information cheaply.

If an unknown production failure exists, discovering it with minimal exposure is preferable to discovering it after scaling.

⸻

5. No Arbitrary Starting Capital

Phase 8 will not hard-code a universal amount such as:

$100

$1,000

or:

$10,000

before validated strategy characteristics are known.

Starting capital should instead satisfy:

Large enough to generate economically meaningful real fills

while remaining:

Small enough that total loss would not materially damage the project.

The exact amount will be determined immediately before deployment from:

* Minimum viable order sizes
* Expected trade frequency
* Fee burden
* Strategy stop distance
* Liquidity
* Statistical observation requirements
* Available risk capital

⸻

6. Capital-at-Risk vs Account Balance

A critical distinction must be maintained between:

Capital deposited

and:

Capital actually at risk.

Depositing $X does not mean $X should be exposed.

The system must define:

Maximum Capital-at-Risk

independently from:

Account Balance.

⸻

7. Live Capital Segmentation

Initial production capital should be isolated from the project’s larger capital pool.

Conceptually:

Reserve Capital

separate from:

Limited-Live Trading Capital

The Limited-Live system should not have automatic authority to access additional reserve capital.

⸻

8. Capital Expansion Ladder

Capital should be increased through controlled stages.

Conceptually:

L0 — Minimum Live Exposure

↓

L1 — Small Validation Capital

↓

L2 — Expanded Validation Capital

↓

L3 — Pre-Production Capital

↓

L4 — Production Allocation

Capital may move upward only after evidence.

It may move downward immediately when evidence deteriorates.

⸻

9. No Automatic Capital Scaling

The AI may never decide:

“Performance is good, therefore increase capital.”

Capital promotion is governed independently.

Scaling requires:

* Statistical evidence
* Risk review
* Execution review
* Reliability review
* Human/governance approval

⸻

10. Frozen Production Candidate

Before Limited Live begins, the following must be frozen:

* Dataset reference
* Feature version
* Model version
* Strategy version
* Calibration version
* Risk configuration
* Execution policy
* Exit policy
* Asset universe

This creates a genuine forward test.

⸻

11. Live Cohort

Each Limited-Live validation run receives a unique identity.

Example:

LIVE-VAL-001

It records:

* Start timestamp
* End timestamp
* Initial equity
* Capital-at-risk ceiling
* Assets
* Strategies
* Models
* Risk configuration
* Execution configuration
* Infrastructure version

Material modifications create a new cohort.

⸻

12. Shadow Twin Architecture

One of the most important Phase 8 requirements is:

Every real strategy must have a Shadow Twin.

The same market state is passed simultaneously into:

LIVE PIPELINE

and:

SHADOW PIPELINE

The Shadow Twin records what the Phase 7 simulator expected.

The Live system records what actually happened.

⸻

13. Twin Decision Consistency

Before order transmission:

Live Decision

and:

Shadow Decision

should be identical if both use the same:

* Market state
* Features
* Model
* Risk configuration

Unexpected decision divergence indicates an implementation inconsistency and must be investigated.

⸻

14. Shadow vs Real Order

For every live order, store:

Shadow Expected

* Expected order
* Expected price
* Expected fill
* Expected slippage
* Expected fee
* Expected latency

Real Observed

* Actual order
* Actual fill
* Actual price
* Actual slippage
* Actual fee
* Actual latency

The difference becomes:

Execution Reality Gap

⸻

15. Execution Reality Gap

For trade i:

Execution Gap = Real Execution Outcome − Shadow Expected Outcome

Components include:

* Price difference
* Slippage difference
* Fee difference
* Fill-ratio difference
* Latency difference
* Funding difference

This metric is one of Phase 8’s primary outputs.

⸻

16. Implementation Shortfall

Execution quality should also be measured relative to the market state when the strategy decided to trade.

Reference prices may include:

* Decision mid
* Arrival mid
* Best executable quote
* VWAP where appropriate

The objective is to separate:

Strategy Alpha

from:

Execution Loss.

⸻

17. Real Fee Accounting

Every actual fee must be imported from venue records.

Estimated fees are no longer sufficient.

The platform must record:

* Maker fee
* Taker fee
* Any applicable rebate
* Effective fee rate
* Total fee cost

Hyperliquid fee tiers may change with rolling trading volume.

Therefore fee assumptions must be dynamically reconciled with actual account behavior.

⸻

18. Real Funding Accounting

Every funding payment must be captured from actual account events.

Funding must be attributed to:

* Asset
* Position
* Strategy
* Holding interval

The platform must compare:

Expected Funding

vs.

Actual Funding

This is particularly important for positions held across multiple funding intervals.

⸻

19. Funding-Aware Alpha

Strategy performance should be decomposed into:

Price P&L

Funding P&L

−

Fees

−

Execution Cost

=

Net Realized Strategy P&L

This prevents profitable price predictions from hiding economically poor perpetual-futures implementation.

⸻

20. Real Slippage Model

Phase 8 creates the first ground-truth slippage dataset.

For every order:

Decision Price

Submission Price

Arrival Price

Fill Price

must be retained where measurable.

Slippage should then be modeled against:

* Asset
* Direction
* Order size
* Order type
* Spread
* Volatility
* Depth
* Market regime
* Time
* Signal urgency

⸻

21. Slippage Model Recalibration

The Phase 4/7 slippage model must be recalibrated using Phase 8 observations.

If:

Historical assumed slippage = X

while:

Live observed slippage = Y

the historical strategy must be rerun using improved assumptions.

Live execution therefore feeds back into historical research.

⸻

22. Fill Probability Calibration

Limit-order strategies require special validation.

For every Shadow predicted fill probability:

compare against:

Actual fill outcome

This produces a real fill-calibration model.

Optimistic simulated limit fills are a major potential source of false backtest profitability.

⸻

23. Maker/Taker Attribution

Every trade should record whether it actually executed as:

Maker

or:

Taker

The system should then determine whether execution policy behaves as expected.

A strategy designed around maker economics may fail if production behavior frequently converts into taker execution.

⸻

24. Order-Type Validation

Market, Limit, ALO/Post-Only and IOC policies should be evaluated independently.

The system should measure:

* Fill rate
* Cost
* Adverse selection
* Missed opportunity
* Latency sensitivity

The objective is not always minimizing fee.

The objective is:

Maximize Net Execution Quality

⸻

25. Stop-Loss Reality Study

Every triggered Stop Loss must receive detailed analysis.

Record:

Stop Trigger Price

Mark Price at Trigger

Book State

Actual Fill

Slippage

Time to Full Exit

This dataset is critical for estimating real tail risk.

⸻

26. Stop Market vs Stop Limit

The system must explicitly compare the trade-off:

Stop Market

Higher probability of exit.

Potentially substantial slippage.

Stop Limit

Greater price control.

Risk of non-execution during fast markets.

The optimal mechanism may differ by:

* BTC
* ETH
* SOL
* BNB
* volatility regime
* liquidity state
* position size

⸻

27. Stop Is Not Maximum Loss

The system must never assume:

Stop Price = Guaranteed Maximum Loss

Realized loss may exceed the planned stop due to:

* Slippage
* Market gaps
* Liquidity loss
* Trigger mechanics
* API problems
* Venue disruption

Therefore actual:

Loss Beyond Stop

must become a tracked risk metric.

⸻

28. Liquidation Buffer

Every live leveraged position must maintain:

Entry

↓

Intended Risk Exit

↓

Emergency Safety Region

↓

Liquidation Boundary

Liquidation must not be treated as a normal exit mechanism.

⸻

29. Live Liquidation Monitor

Liquidation distance must be recalculated continuously because it can change due to:

* Unrealized P&L
* Funding
* Position changes
* Cross-margin account state
* Margin tiers
* Collateral changes

A liquidation-price estimate made only at entry is insufficient.

⸻

30. Initial Margin Policy

For early Limited Live, the project should favor containment and interpretability over maximum capital efficiency.

Where strategy mechanics permit, isolated risk should be evaluated seriously for initial validation.

Cross margin may later provide capital efficiency but introduces portfolio-level collateral interactions.

The final choice remains strategy-dependent.

⸻

31. Portfolio Margin Exclusion

Experimental or pre-alpha margin systems should not be introduced into initial Limited-Live qualification.

Production validation should initially minimize unnecessary margin complexity.

New margin architectures require their own validation cycle.

⸻

32. Leverage Qualification

Maximum venue-supported leverage is irrelevant to our desired leverage.

The system should determine:

Validated Operational Leverage

which may be substantially below venue maximum.

It depends on:

* Strategy drawdown
* Stop reliability
* Volatility
* Execution quality
* Tail behavior
* Liquidation buffer
* Portfolio concentration

⸻

33. Leverage Escalation Rule

Leverage must not increase simply because early trades are profitable.

Any increase requires evidence that:

* Execution remains stable
* Tail assumptions remain valid
* Stop behavior remains acceptable
* Drawdown remains within expected range
* Alpha survives actual costs

⸻

34. Risk Budget During Limited Live

Initial Limited-Live risk should be intentionally below the eventual validated production risk budget.

The purpose is:

measurement before optimization.

Risk may be expanded only after the system demonstrates stable behavior.

⸻

35. Correlated Exposure Restriction

During early live validation, simultaneous correlated positions should be deliberately constrained.

For example:

BTC LONG

ETH LONG

SOL LONG

BNB LONG

must not be interpreted as four independent experiments.

It may represent one concentrated crypto-market directional exposure.

⸻

36. One Variable at a Time

Early Limited Live should avoid changing multiple dimensions simultaneously.

For example, do not simultaneously:

* Increase capital
* Increase leverage
* Add an asset
* Change model
* Change execution policy

Otherwise the cause of performance changes becomes difficult to identify.

⸻

37. Asset Qualification

BTC, ETH, SOL and BNB should each receive individual live qualification.

A strategy may become:

BTC LIVE-QUALIFIED

while remaining:

SOL SHADOW-ONLY

Asset qualification must not be inherited automatically.

⸻

38. Strategy Qualification

Likewise:

Trend Strategy

may become live-qualified.

while:

Order Flow Strategy

remains Shadow.

Production status belongs to:

Strategy × Asset × Model × Risk Configuration × Execution Policy

not simply to the application.

⸻

39. Production Qualification Unit

The true qualification object is therefore:

Trading Configuration

Example:

Asset: ETH
Strategy: Trend-Meta
Model: M047
Risk: R012
Execution: E008
Version: V1

This exact configuration earns or loses production status.

⸻

40. Real Prediction Logging

Every live prediction remains logged regardless of whether a trade occurs.

This includes:

* LONG
* SHORT
* NO TRADE
* Risk rejected
* Execution rejected
* Expired signal

This allows complete evaluation of decision quality.

⸻

41. Live Counterfactuals

For rejected trades:

the Shadow Twin continues tracking hypothetical performance.

This lets us ask:

Did Risk save money or unnecessarily reject edge?

Similarly, for NO TRADE decisions:

the system can study subsequent market outcomes without changing the original decision.

⸻

42. Risk Engine Attribution

At the end of each validation cohort:

calculate performance for:

AI Candidate Trades

vs.

Risk-Approved Trades

vs.

Actually Executed Trades

This isolates the value contributed by:

* AI
* Risk Engine
* Execution Engine

⸻

43. Alpha Decomposition

Net performance should be decomposed conceptually into:

Signal Alpha

Position-Sizing Effect

Exit Effect

Funding Effect

−

Fee Cost

−

Spread Cost

−

Slippage

−

Execution Failure Cost

This prevents one subsystem from hiding another subsystem’s weakness.

⸻

44. Live Alpha Decay

Compare:

Backtest Alpha

↓

Out-of-Sample Alpha

↓

Shadow Alpha

↓

Limited-Live Alpha

A progressive collapse suggests:

* Overfitting
* Simulation error
* Execution cost underestimation
* Regime shift
* Data leakage
* Capacity issues

The cause must be identified before scaling.

⸻

45. Backtest-to-Shadow-to-Live Gap

Phase 8 extends the Phase 7 metric into:

Research-to-Reality Gap

It includes:

Backtest → Shadow

and:

Shadow → Live

These gaps should be separately measured.

A large Shadow-to-Live gap strongly suggests execution/infrastructure issues.

A large Backtest-to-Shadow gap more strongly suggests research/data/model issues.

⸻

46. Live Expectation Envelope

Before each validation cohort, expected ranges should be defined for:

* Trade frequency
* Win Rate
* Expectancy
* Drawdown
* Slippage
* Holding period
* Exposure
* Funding
* Calibration

The live result is evaluated relative to these distributions.

Not relative to wishful targets.

⸻

47. Sequential Evaluation

Because live evidence arrives over time, the system should support sequential monitoring.

However, continuously looking at P&L and changing the model creates another form of overfitting.

Therefore:

Monitoring

is continuous.

Strategy modification

is governed.

Material modifications restart formal validation.

⸻

48. Early Stop for Harm

Although strategy tuning is restricted during a cohort, safety is never frozen.

A cohort can be terminated immediately for:

* Excessive loss
* Unexpected drawdown
* Execution anomaly
* Model malfunction
* Risk failure
* Reconciliation mismatch
* Infrastructure failure

Statistical purity never overrides capital protection.

⸻

49. Loss Limits

Limited-Live validation requires independent:

Per-Trade Loss Limit

Daily Loss Limit

Cohort Loss Limit

Portfolio Drawdown Limit

Breaching a hard safety threshold stops new risk.

Exact numerical values must be derived from validated strategy distributions before deployment.

⸻

50. Cohort Loss Budget

Every Limited-Live experiment receives a maximum experimental loss budget.

This is the maximum capital the project is willing to spend learning whether that configuration works in reality.

When exhausted:

EXPERIMENT TERMINATED

No revenge trading.

No automatic capital injection.

⸻

51. Consecutive Failure Detection

The system should compare observed losing streaks against the expected distribution from historical and Monte Carlo analysis.

An unusually severe streak may indicate:

* Bad luck
* Regime shift
* Model decay
* Data issue
* Execution issue

The correct response is investigation, not automatic leverage increase.

⸻

52. Execution Failure Budget

Not only financial losses matter.

The cohort should also maintain tolerances for:

* Order rejection
* Unexpected partial fills
* API timeout
* Reconciliation errors
* Protective-order failures

Excessive operational errors can fail the cohort even if P&L is positive.

⸻

53. Reconciliation Requirement

For real capital:

Exchange State is authoritative for actual exposure.

Internal state must continuously reconcile:

* Positions
* Open orders
* Fills
* Funding
* Margin

Any unexplained mismatch is a critical event.

⸻

54. Unknown Position Rule

If the system cannot confidently determine current real exposure:

NO NEW RISK

The platform enters Safe Mode until reconciliation succeeds.

⸻

55. API Wallet Isolation

Automated execution should use dedicated API/agent-wallet credentials where supported.

The primary wallet’s seed phrase/private key must not be exposed to the trading backend.

Different trading processes should avoid unnecessary signer reuse.

Credential compromise must have the smallest practical blast radius.

⸻

56. Credential Rotation

Production execution credentials require:

* Rotation policy
* Expiration handling
* Secure storage
* Access audit
* Revocation procedure

Credential failure must not cause uncontrolled trading behavior.

⸻

57. Dead-Man’s Switch

Venue-side scheduled cancellation should be used where appropriate.

The system periodically refreshes the cancellation deadline.

If the execution infrastructure disappears unexpectedly:

Open Orders Cancel Automatically

This is defense in depth.

⸻

58. Dead-Man’s Switch Limitation

Dead-Man’s Switch does not close existing positions.

It protects primarily against abandoned open orders.

Therefore it cannot replace:

* Protective exits
* Position monitoring
* Emergency close logic
* Reconciliation

⸻

59. Rate-Limit Reserve

The system must reserve API capacity for risk-reducing operations.

Under heavy load:

Cancel

Reduce

Close

Reconcile

must have priority over:

* Analytics queries
* Non-critical history requests
* UI refreshes

Production trading must never consume all available API capacity for low-priority operations.

⸻

60. WebSocket + REST Reconciliation

WebSocket should provide low-latency live state.

REST/info queries provide independent reconciliation.

Neither should be trusted alone.

Architecture:

WebSocket Event Stream

Periodic State Query

↓

Reconciliation Engine

⸻

61. Execution Latency Budget

For every strategy, define acceptable latency boundaries for:

Market Event → Feature

Feature → Prediction

Prediction → Risk

Risk → Order

Order → Venue Ack

Ack → Fill

P50, P95 and P99 should be measured.

Average latency alone is insufficient.

⸻

62. Latency Tail Risk

A system averaging 40 ms but occasionally taking 4 seconds may be unacceptable for a short-horizon strategy.

Therefore tail latency must be explicitly evaluated.

⸻

63. Venue Health Gating

Before any order:

the venue-health system should evaluate:

* API responsiveness
* WebSocket health
* Book freshness
* Spread
* Order rejection rate
* Reconciliation state

Poor venue health can produce:

NO NEW TRADE

even when AI confidence is high.

⸻

64. Market Quality Gating

The Risk Engine should also evaluate:

* Spread
* Depth
* Volatility
* Liquidity
* Expected slippage

A valid signal in an invalid market environment should be rejected.

⸻

65. Live Safe Mode

Safe Mode behavior:

* No new positions
* Existing risk managed
* Reduce-only actions allowed
* Emergency exits allowed
* AI continues observing
* Predictions continue logging

This allows research to continue while capital exposure stops expanding.

⸻

66. Emergency Mode

Emergency Mode may:

* Block all new risk
* Cancel entry orders
* Cancel stale orders
* Reduce/close positions
* Disable automated restart
* Require reconciliation

The exact liquidation policy depends on the nature of the emergency.

⸻

67. Manual Emergency Control

Authorized operators require immediate access to:

PAUSE AUTOPILOT

NO NEW TRADES

CANCEL ORDERS

REDUCE ALL

CLOSE ALL

These controls must not depend on AI availability.

⸻

68. No Manual Strategy Interference

Emergency intervention is allowed.

Emotional discretionary interference is not part of the formal validation protocol.

If an operator manually changes a position for non-emergency reasons:

the event must be recorded and the affected trade flagged.

Otherwise live evidence becomes contaminated.

⸻

69. Production Incident Registry

Every live incident receives an ID.

Example:

LIVE-INC-0007

Record:

* Timestamp
* Severity
* Exposure
* Root cause
* Response
* Financial impact
* Recovery
* Prevention action

⸻

70. Post-Incident Review

Every severe incident should produce:

Root Cause Analysis

↓

Corrective Action

↓

Automated Regression Test

↓

Revalidation

A serious production failure should never remain only a paragraph in a report.

It becomes a permanent test.

⸻

71. Security Incident Boundary

Security incidents receive independent escalation.

Examples:

* Unauthorized signing
* Unexpected API wallet behavior
* Credential exposure
* Unknown transaction
* Unauthorized configuration change

Immediate response:

Freeze Automated Trading

↓

Revoke/Rotate Credentials

↓

Reconcile

↓

Investigate

⸻

72. Live Data Preservation

Phase 8 data is strategically valuable.

Persist:

* Raw market inputs
* Features
* Predictions
* Risk decisions
* Orders
* Exchange acknowledgements
* Fills
* Fees
* Funding
* Positions
* Margin state
* Latencies
* Errors
* Operator actions

This becomes the project’s highest-value validation dataset.

⸻

73. Production Truth Dataset

The project should create a dedicated:

Production Truth Dataset

Unlike historical vendor data, this dataset records exactly what our system:

saw

believed

decided

submitted

and:

received

This becomes the strongest future training and validation resource.

⸻

74. Live Model Calibration

Probability calibration must continue under real observations.

Confidence buckets should be compared with realized outcomes.

If:

80% predictions

behave materially worse than expected,

the system should reduce trust in those probabilities even if headline P&L remains temporarily positive.

⸻

75. Live Drift Monitoring

Monitor:

* Feature drift
* Prediction drift
* Regime drift
* Calibration drift
* Execution drift
* Slippage drift
* Strategy performance drift

These are distinct phenomena and should not be merged into one alarm.

⸻

76. Strategy Decay

A strategy may retain positive lifetime performance while losing current edge.

The system should therefore emphasize rolling evidence.

Possible responses:

Normal

↓

Watch

↓

Reduced Allocation

↓

Shadow Only

↓

Suspended

↓

Retired

⸻

77. Capital Scaling Criteria

Capital may increase only when all major dimensions remain acceptable:

Alpha

Risk

Execution

Calibration

Reliability

Drift

Liquidity Capacity

Operational Safety

Profit alone cannot trigger scaling.

⸻

78. Scaling Should Be Gradual

Capital increases should occur incrementally rather than through large jumps.

After each increase:

execution quality and market impact are re-measured.

This identifies the point at which strategy capacity begins to deteriorate.

⸻

79. Capacity Curve

The project should eventually estimate:

Capital

vs.

Net Strategy Performance

As capital rises:

* Market impact may increase
* Slippage may increase
* Fill probability may decline
* Edge may decrease

The maximum useful capital is therefore not unlimited.

⸻

80. Capacity Ceiling

Each strategy should receive an estimated:

Strategy Capacity Ceiling

Beyond that level:

additional capital should not be allocated unless new evidence supports it.

⸻

81. Promotion Does Not Mean Permanence

A configuration reaching Production remains monitored.

Production status can be revoked.

Possible states:

SHADOW

LIMITED LIVE

PRODUCTION QUALIFIED

PRODUCTION

REDUCED

SUSPENDED

RETIRED

⸻

82. Production Qualification Gate

A Trading Configuration becomes:

PRODUCTION QUALIFIED

only when it demonstrates:

1. Positive or otherwise acceptable real expectancy relative to its hypothesis.
2. Real execution consistent with modeled execution.
3. Fees consistent with expectations.
4. Funding behavior understood.
5. Slippage within validated bounds.
6. Fill behavior within validated bounds.
7. Risk Engine functioning correctly.
8. No unresolved reconciliation issue.
9. No unresolved critical infrastructure failure.
10. Acceptable probability calibration.
11. Acceptable drawdown behavior.
12. Acceptable tail behavior.
13. Acceptable live drift.
14. No evidence of catastrophic research-to-reality collapse.
15. Sufficient live observations.

⸻

83. No Universal Minimum Trade Count

The architecture will not declare:

100 trades = validated

or:

30 days = validated

without statistical justification.

Required evidence depends on:

* Strategy frequency
* Effect size
* Variance
* Regime exposure
* Dependence between trades
* Confidence interval width

The validation window must be determined statistically.

⸻

84. Confidence Intervals

Live performance metrics should include uncertainty.

Example:

Instead of:

Win Rate = 58%

report:

Estimated Win Rate + Confidence Interval

where statistically appropriate.

Likewise for:

* Expectancy
* Slippage
* Fill rate
* Calibration

Small samples must visibly look uncertain.

⸻

85. Bayesian Updating Research

A Bayesian monitoring framework should be investigated for updating belief about strategy quality as live evidence accumulates.

Conceptually:

Prior Evidence from Robust Historical/Shadow Validation

New Real-Money Evidence

↓

Updated Belief About Strategy Edge

This can be more informative than repeatedly asking whether an arbitrary p-value threshold has been crossed.

It must not become a shortcut around robust validation.

⸻

86. Sequential Testing Risk

Repeatedly checking live results and stopping only when they look good introduces bias.

Therefore any sequential statistical framework must explicitly account for repeated observation.

The system must not accidentally turn production qualification into another overfitted backtest.

⸻

87. Profit Withdrawal Is Not Evidence

Withdrawing early profits does not make a strategy safer or statistically validated.

Capital management and evidence quality are separate questions.

The platform must not confuse realized profit with proof of durable edge.

⸻

88. Psychological Isolation

Because this is automated trading, discretionary reactions to short-term P&L should be minimized.

A losing day must not automatically trigger:

* Model changes
* Strategy changes
* Leverage changes

Likewise, a winning streak must not trigger aggressive scaling.

Decisions follow pre-defined governance.

⸻

89. Daily Live Report

Each day the system should report:

Real P&L

Shadow P&L

Execution Reality Gap

Fees

Funding

Slippage

Positions

Risk Rejections

Calibration

Incidents

Data Health

Venue Health

⸻

90. Weekly Qualification Review

The weekly review should examine:

* Live vs Shadow
* Live vs Backtest expectation
* Strategy performance
* Asset performance
* Execution quality
* Risk contribution
* Model calibration
* Drift
* Drawdown
* Incidents
* Capacity
* Evidence sufficiency

⸻

91. Monthly Research Review

For sufficiently active strategies, a broader periodic review should examine whether accumulated production evidence requires:

* Retraining
* Recalibration
* Risk adjustment
* Execution-model update
* Strategy suspension
* Capital scaling

Changes must enter the controlled research pipeline.

⸻

92. Rollback Architecture

Every production release must support rollback.

If a new model/configuration fails:

New Version

↓

Disable

↓

Previous Validated Version

or:

Shadow Only / Safe Mode

Rollback must not require emergency coding.

⸻

93. Canary Deployment

Future model upgrades should initially receive a small fraction of eligible risk.

Conceptually:

Champion: majority

Challenger: small canary allocation

Only after live evidence should allocation migrate.

This reduces model-upgrade risk.

⸻

94. Production Model Upgrade

The process is:

Research

↓

Backtest

↓

Validation

↓

Shadow

↓

Limited Live

↓

Canary

↓

Production

A new model does not inherit the previous model’s production status.

⸻

95. Phase 8 Failure Criteria

Phase 8 fails if evidence demonstrates any critical issue such as:

* Unexplained execution divergence
* Materially underestimated slippage
* Persistent fill-model failure
* Unexpected liquidation risk
* Uncontrolled order duplication
* Reconciliation failure
* Risk limit bypass
* Critical data corruption
* Persistent calibration collapse
* Severe alpha decay
* Unsafe infrastructure behavior
* Security compromise

Failure results in:

CAPITAL REDUCTION / SAFE MODE / SHADOW

not attempts to recover losses aggressively.

⸻

96. Phase 8 Success Definition

Phase 8 success does NOT mean:

“The bot made money.”

It means:

The complete trading configuration demonstrated statistically and operationally acceptable behavior using real capital, with execution, risk, costs, calibration, reliability and observed alpha remaining sufficiently consistent with validated expectations.

⸻

97. Final Phase 8 Architecture

Validated Shadow Configuration

↓

Frozen Live Candidate

↓

Minimum Real Capital

↓

Live + Shadow Twin

↓

Real Orders

↓

Real Fills

↓

Fees + Funding + Slippage

↓

Continuous Reconciliation

↓

Execution Reality Gap

↓

Research-to-Reality Gap

↓

Risk & Alpha Attribution

↓

Drift + Calibration

↓

Statistical Evidence Accumulation

↓

PRODUCTION QUALIFICATION GATE

↓

Fail

Reduce / Suspend / Shadow / Research

Pass

PRODUCTION QUALIFIED

↓

Gradual Capital Scaling

↓

Continuous Monitoring

⸻

98. Strategic Conclusion

Phase 8 should be treated as an experiment whose cost is controlled capital exposure.

The capital is not being deployed primarily to generate income.

It is being deployed to answer a much more valuable question:

Does the system behave in the real market the way our research says it should?

Only after that question has been answered with sufficient evidence should capital scaling begin.

⸻

99. Final Principle

The transition:

Backtest → Paper → Shadow → Live

must progressively reduce uncertainty.

If uncertainty increases after real capital is introduced:

capital should decrease.

If evidence strengthens:

capital may increase gradually.

The direction of capital allocation must therefore follow:

Evidence

not:

Confidence, excitement, or recent P&L.

⸻

Phase 8 Decision

APPROVED AS LIMITED-CAPITAL LIVE VALIDATION ARCHITECTURE

Approval does not authorize immediate real-money deployment.

Real capital may be introduced only after the previous Phase acceptance gates have been implemented and objectively passed.

The next phase is:

Phase 9 — Product Interface, Wallet Integration & Human Control Layer

Phase 9 will define how the validated trading system is exposed to the user through Phantom and Trust Wallet, how Autopilot/Copilot/Research modes operate, how risk and AI decisions are explained, and how emergency human controls are presented without compromising the safety architecture.

⸻

Document: Limited-Capital Live Trading & Production Qualification Specification
Version: 1.0
Phase: 8
Core Assets: BTC / ETH / SOL / BNB
Next Phase: Product Interface, Wallet Integration & Human Control Layer