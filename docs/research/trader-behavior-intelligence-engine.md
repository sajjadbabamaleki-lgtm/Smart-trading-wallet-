Trader Behavior Intelligence Engine

Evidence-Audited Research & Architecture Specification

Project: AI-Powered Automated Perpetual Futures Trading Platform
Component: Trader Behavior Intelligence Engine (TBIE)
Initial Market: BTC Perpetual Futures
Initial Venue: Hyperliquid
Document Version: 1.1
Supersedes: Version 1.0
Document Class: Research & Architecture Specification
Research Status: HIGH-PRIORITY EXPERIMENTAL CANDIDATE
Production Signal Status: NOT APPROVED
Real-Capital Authority: NONE
Evidence Audit Date: September 2026

⸻

1. Purpose of This Revision

Version 1.1 performs an evidence audit of the empirical claims used to justify the Trader Behavior Intelligence Engine.

The purpose is to separate:

* independently verified source claims,
* claims supported only by working papers,
* architectural inference,
* unresolved execution questions,
* and hypotheses that must be reproduced internally.

The central conclusion remains:

Persistent pseudonymous trader identity on Hyperliquid is a scientifically credible candidate source of incremental market information.

However, this revision introduces an important qualification:

Existing research demonstrates predictive information, not executable trading alpha.

The distinction is fundamental.

TBIE therefore remains a research feature family until the project independently demonstrates that trader-identity information survives realistic observation delay, computation latency, network latency, execution latency, fees, spread, slippage, queue effects, and market impact.

⸻

2. Evidence Classification Standard

Every external claim supporting TBIE is assigned one of four states:

VERIFIED

The claimed number or methodology was found directly in the primary paper or official documentation.

VERIFIED WITH QUALIFICATION

The claim is correct, but its interpretation requires an important limitation.

PARTIALLY VERIFIED

Evidence supports the general claim but not every detail required for production decisions.

UNVERIFIED / PROJECT HYPOTHESIS

The claim has not been demonstrated sufficiently and must be tested internally.

No architectural commitment requiring significant infrastructure expenditure should depend solely on an UNVERIFIED claim.

⸻

3. Primary Evidence Audit

The principal study supporting TBIE is:

Daojing Zhai, “Public Trader Identity: Adverse Selection and Return Predictability,” 2026.

The paper is currently available as an SSRN/arXiv working paper.

It should therefore be treated as serious research evidence, but not as settled scientific consensus or equivalent to independently replicated peer-reviewed evidence.

⸻

4. Dataset Size

The paper reports:

17.1 billion Level-4 messages
14.3 million aggressive orders
147,113 wallets
27.9 million taker fills
$84.3 billion taker notional

across the ten most active perpetual markets in its July 2026 dataset.

Audit Result

VERIFIED

The reported figures are directly supported by the paper.

⸻

5. BTC-Specific Relevance

The dataset is not merely a broad altcoin sample.

BTC is the largest market in the July dataset.

The paper reports approximately:

BTC Level-4 messages:     9.75 billion
BTC aggressive orders:   4.02 million
BTC taker fills:          8.66 million
BTC wallets:              98,900
BTC taker notional:       $46.8 billion
BTC spread:               0.20 bps

The principal predictive analysis focuses on:

BTC
ETH
SOL

because these were the three markets with the greatest message activity.

Audit Result

VERIFIED

This materially strengthens relevance to the BTC-only Lean Quant MVP.

⸻

6. Definition of Trader Informativeness

The paper does not classify wallets using realized PnL.

Instead, it measures post-trade adverse selection using signed midpoint markout.

For aggressive order (e):

[
x_e =
10^4 q_e
\frac{m_{t_e+10s}-m_{t_e^-}}
{m_{t_e^-}}
]

where:

* (q_e=+1) for buy,
* (q_e=-1) for sell,
* (m_{t_e^-}) is the midpoint immediately before the event,
* (m_{t_e+10s}) is the midpoint ten seconds later.

A positive markout means price subsequently moved in the aggressor’s direction.

Wallet skill is then estimated using a notional-weighted average of these markouts.

Audit Result

VERIFIED

This validates the architectural decision in TBIE v1.0 to treat markout as a central measure of informational timing rather than relying exclusively on PnL.

⸻

7. Minimum Wallet Sample

The principal wallet-ranking experiment includes wallets with at least:

100 qualifying aggressive orders

during the scoring period.

The July experiment produced:

2,314 scored wallets

with:

231 wallets

in the top decile.

TWAP and liquidation events were excluded from the benchmark scoring procedure.

Audit Result

VERIFIED

This also confirms that meaningful trader ranking requires minimum sample requirements.

TBIE must not rank wallets after only a handful of observations.

⸻

8. Point-in-Time Ranking

The paper uses:

July 1–10

as the scoring window.

Wallet rankings are then frozen before subsequent evaluation.

Persistence is evaluated during:

July 11–20

and the predictive model is ultimately evaluated during:

July 21–27.

Audit Result

VERIFIED

This is materially important.

The paper does not simply identify successful wallets using future performance and then retroactively label their earlier trades as informed.

Its principal design contains a genuine temporal separation.

⸻

9. Persistence of Trader Informativeness

Across adjacent ten-day windows, wallet informativeness rankings show:

[
\rho = 0.52
]

Spearman rank correlation.

The paper additionally reports split-half reliability analysis suggesting that the observed persistence is substantial relative to the estimated measurement reliability of the score.

Audit Result

VERIFIED

However:

[
\rho=0.52
]

does not imply permanent trader skill.

It indicates meaningful persistence over the tested horizon.

TBIE must therefore continue to model skill as time-varying.

⸻

10. Concentration in the Upper Tail

The paper finds that trader informativeness is highly concentrated.

After controlling for market, time, order size, volatility, and spread, markouts remain relatively flat across most wallet ventiles and increase sharply in the upper tail.

The reported top-ventile adjusted markout reaches approximately:

[
3.11\text{ bps}
]

Audit Result

VERIFIED

This supports a key architectural conclusion:

Trader identity should not be treated uniformly.

The potential information appears concentrated in a relatively narrow subset of wallets.

⸻

11. Persistence Beyond Immediate Price Pressure

The paper reports that top-decile wallet markout rises from approximately:

1.25 bps at 0.5 seconds

to:

2.11 bps at 10 seconds

and remains elevated at longer horizons including five minutes.

Audit Result

VERIFIED WITH QUALIFICATION

This suggests the measured effect is not merely an instantaneous mechanical price reaction.

However, the authors explicitly acknowledge that persistent market impact, repeated directional flow, and latent metaorders remain possible explanations.

Therefore:

Persistent markout must not automatically be interpreted as private information or superior forecasting skill.

⸻

12. Wallet Continuity

Of the 231 top-decile wallets identified during the July scoring period:

91.3%

traded again during the validation period.

Audit Result

VERIFIED

This reduces the possibility that the persistence result is purely an artifact of disappearing wallets.

⸻

13. Anonymous Benchmark

The primary predictive experiment compares an anonymous market model against an identity-augmented model.

The anonymous model includes standard market-microstructure information such as:

Best-quote depth imbalance
Near-touch depth imbalance
Quote-update order-flow imbalance
Latest signed trade
Signed taker flow
Recent return
Recent realized volatility
Quoted spread

The identity model adds analogous information specifically associated with previously ranked high-informativeness wallets plus identity-only features such as:

Net distinct informed buyers
Informed-wallet share of best-quote depth
Informed-wallet contribution to quote imbalance

Audit Result

VERIFIED

This is critical because TBIE is not being compared against a trivial price-only benchmark.

Trader identity is tested for incremental information beyond substantial anonymous microstructure information.

⸻

14. Headline One-Second Result

At the one-second prediction horizon, the linear ridge benchmark reports:

Anonymous model R²:       10.88%
Identity model R²:        12.31%
Relative improvement:     +13.2%
Reported t-statistic:     9.2

Audit Result

VERIFIED

The number previously used in TBIE v1.0 is correct.

However:

+13.2% is a relative improvement in predictive R².

It is NOT:

* 13.2% return,
* 13.2% alpha,
* 13.2% profitability,
* or 13.2% trading performance.

⸻

15. Placebo Cohorts

The paper constructs:

200 activity-matched placebo cohorts

matched to the high-informativeness wallets using scoring-window order count and notional.

The identity gain exceeds the placebo cohorts through the relevant short horizons.

Audit Result

VERIFIED

This is an important robustness test because it reduces the likelihood that the result is merely caused by tracking highly active or large traders.

⸻

16. Nonlinear Model Test

The paper also evaluates gradient-boosted trees.

At one second:

Anonymous R²:        19.48%
Identity R²:         20.65%
Relative gain:       +6.0%

Audit Result

VERIFIED

The smaller incremental improvement indicates that nonlinear anonymous market features absorb some of the information associated with trader identity.

However, identity still contributes additional information.

This suggests TBIE should always compete against strong nonlinear market baselines.

⸻

17. Critical Latency Finding

The original TBIE document emphasized the one-second headline result.

The full paper reveals a more nuanced horizon structure.

For the ridge model:

Horizon	Anonymous R²	+ Identity R²	Relative Gain
0.2s	6.91%	8.20%	+18.7%
0.5s	10.16%	11.76%	+15.8%
1s	10.88%	12.31%	+13.2%
2s	10.60%	11.66%	+10.0%
5s	9.17%	9.79%	+6.7%
10s	7.18%	7.56%	+5.2%
30s	3.56%	3.67%	+3.0%

For gradient-boosted trees, the incremental identity gain falls from approximately:

+10.7% at 200 ms

to:

+2.7% at 30 seconds.

The tree-model identity increment remains statistically distinguishable from zero through approximately ten seconds, but not at thirty seconds in the reported specification.

Audit Result

VERIFIED

This materially updates the previous interpretation.

The signal is:

FAST DECAYING

but it is not demonstrated only at one second.

⸻

18. Revised Latency Interpretation

The previous concern:

“If the signal only survives below 100 ms, TBIE is unusable.”

is not supported by the paper.

The evidence suggests identity information remains measurable at multi-second horizons.

However, another limitation is more important.

The paper indexes timing using:

CONSENSUS TIMESTAMPS

rather than an independently audited:

LOCAL RECEIPT-TIME CLOCK

Therefore the study does not establish that our system can:

observe event
↓
decode event
↓
update trader state
↓
calculate features
↓
run inference
↓
run risk checks
↓
submit order
↓
receive execution

before the remaining predictive information disappears.

Audit Result

EXECUTABILITY UNVERIFIED

This becomes the most important TBIE research question.

⸻

19. Paper’s Own Execution Limitation

The primary study explicitly states that implementable profitability would require modeling factors including:

Latency
Queue priority
Fill probability
Fees
Inventory
Dynamic execution

and that such an execution model is outside the scope of the paper.

Audit Result

VERIFIED

Therefore the paper proves:

PREDICTIVE INFORMATION

It does not prove:

EXECUTABLE ALPHA

This distinction is now mandatory throughout TBIE documentation.

⸻

20. Feature Delay Robustness

The paper additionally reports robustness tests where the feature vector is shifted backward by additional delays.

This is useful evidence against extremely fragile timestamp leakage.

However, it still does not substitute for an actual end-to-end receipt-to-fill latency experiment.

Audit Result

PARTIALLY SUPPORTIVE

⸻

21. Independent Historical Replication

The primary study repeats its design on a separately collected December 2025 Hyperliquid dataset.

That dataset includes approximately:

26.25 billion Level-4 messages
9.53 million aggressive orders
21.86 million taker fills
89,800 wallets
$127.5 billion taker notional

across:

BTC
ETH
SOL

The same broad persistence and predictive results reportedly recur.

Audit Result

VERIFIED WITH QUALIFICATION

This is a meaningful temporal replication.

However, it is still replication performed within the same research study and methodology.

It is not equivalent to independent reproduction by a separate research group.

⸻

22. Data Integrity Audit in the Primary Study

The study reports explicit collection auditing.

Among approximately:

27,902,380 crossed fill records

every taker record was paired with its maker-side counterpart.

The archive also used SHA-256 manifests for collected shards and documented collection gaps and node failures.

Audit Result

VERIFIED

This raises confidence in the dataset engineering.

However, the paper also documents real collector failures and gaps.

This reinforces our own architectural requirement:

Recorder health and gap detection are first-class research infrastructure.

⸻

23. Cross-Venue Study

The second important study is:

Boon Chuan Lim, “Binance Leads, but Some Wallets Anticipate: Wallet-Level Cross-Venue Informed Flow in BTC Perpetual Futures,” 2026.

The study covers approximately:

25 May 2026
to
22 June 2026

and compares Hyperliquid BTC perpetual activity with Binance BTC perpetual price discovery.

Evidence Status

SUPPORTIVE BUT LOWER CONFIDENCE

The study is a recent working paper by an independent researcher.

It should not carry the same evidentiary weight as multiple independent replications.

⸻

24. Aggregate Cross-Venue Result

The cross-venue study finds:

Binance leads Hyperliquid at the aggregate venue level.

Even the pooled informed Hyperliquid cohort tends to follow Binance.

For the pooled cohort, Binance price movement before Hyperliquid trades exceeds subsequent movement at:

2 seconds
5 seconds
10 seconds

Audit Result

VERIFIED

This is important because it prevents a simplistic interpretation that Hyperliquid smart-money flow universally predicts Binance.

It does not.

⸻

25. Wallet-Level Heterogeneity

The same study reports substantial variation across wallets.

The informed cohort contains:

658 wallets

and more than:

2.3 million cohort trades.

Hundreds of individual wallets have sufficient observations for wallet-level analysis.

Audit Result

VERIFIED

⸻

26. Cross-Venue Persistence

The paper performs a split-sample test.

Wallets are ranked during the first half and evaluated during the second half.

The strongest first-half lead-score quintile remains the only quintile with positive second-half leadership across all tested horizons.

The study reports:

588 wallets

with at least 100 qualifying cohort trades in each half for this persistence analysis.

Audit Result

VERIFIED WITH QUALIFICATION

This is evidence of persistence.

However:

* the sample period is short,
* the paper is recent,
* it is not yet a broad independent replication,
* and execution profitability is not established.

Therefore it should motivate experiments, not production architecture.

⸻

27. Revised Cross-Venue Conclusion

The correct conclusion is:

Hyperliquid is generally not the dominant BTC price-discovery venue, but wallet-level heterogeneity may reveal a minority of traders whose actions precede subsequent movement elsewhere.

The incorrect conclusion would be:

Hyperliquid smart money leads Binance.

The latter is not supported.

⸻

28. Level-4 Data Verification

The paper:

“An Open Book: Level 4 Order Book Data from the Hyperliquid Exchange”

by Jakob Albers, Mihai Cucuringu, Sam Howison, and Alexander Y. Shestopaloff documents reconstruction of highly granular Hyperliquid data using a non-validating node.

The dataset includes:

Order placement
Order cancellation
Rejected orders
Failed cancellation attempts
Pseudonymous wallet identity
Counterparty identity
Post-transaction inventory

Audit Result

VERIFIED

This supports the technical feasibility of TBIE’s richer behavioral-data architecture.

⸻

29. Official Hyperliquid Schema Verification

Hyperliquid’s official node documentation confirms that trade records may contain:

buyer
seller
starting position
order ID
TWAP ID
client order ID

for each side of a trade.

The node can also produce full-information L4 book snapshots and order-status streams.

Audit Result

VERIFIED FROM PRIMARY OFFICIAL SOURCE

This is stronger evidence than relying solely on academic reconstruction.

⸻

30. Rejected-Order Research

A separate 2026 Hyperliquid study examines approximately:

4.5 billion BTC perpetual messages

including rejected orders.

It reports that rejected post-only orders accounted for approximately:

67%

of message traffic in its sample and identifies behavior consistent with anticipatory liquidity replenishment by a small number of market makers.

Audit Result

VERIFIED AS REPORTED RESEARCH

This is highly relevant for future market-microstructure research.

It is NOT yet justification for Build 0.1 to ingest every rejected order.

⸻

31. TWAP and Hidden Metaorder Evidence

Another 2026 study reconstructs approximately:

4.3 million hidden metaorders

and compares them with approximately:

465,000 visible TWAP executions.

The study reports substantial differences in execution behavior, market impact, and liquidity response.

Audit Result

VERIFIED

This supports the decision to distinguish trader behavioral classes rather than treating all large directional flow identically.

⸻

32. API Historical Limitations

Hyperliquid’s official API documentation currently states:

userFills:
up to 2,000 recent fills
userFillsByTime:
up to 2,000 per response
only 10,000 most recent fills available
historicalOrders:
up to 2,000 most recent historical orders

Audit Result

VERIFIED FROM OFFICIAL DOCUMENTATION

Therefore API-only retrospective trader reconstruction is structurally limited.

⸻

33. Historical Archive Limitations

Hyperliquid’s official historical-data documentation states that archive uploads occur approximately monthly and:

timely updates are not guaranteed and data may be missing.

Historical node fills and L1 transaction data are available through separate archive paths.

Audit Result

VERIFIED

Therefore:

OUR OWN RECORDER REMAINS MANDATORY

⸻

34. Node Storage Cost

Official Hyperliquid documentation states that default node operation can generate approximately:

100 GB of logs per day

Audit Result

VERIFIED

Approximate uncompressed implication:

~3 TB / month
~36.5 TB / year

before retention, compression, replication, backups, indexes, or derived datasets.

Therefore full-node ingestion must not be activated casually.

⸻

35. Low-Latency Node Access Qualification

Official Hyperliquid documentation describes additional eligibility requirements for certain Foundation non-validating-node connectivity arrangements.

Therefore the architecture must not assume privileged Foundation connectivity is automatically available.

Decision

The project must benchmark the actual data-access path available to the deployment environment before making latency claims.

⸻

36. Updated Evidence Matrix

Claim	Status
17.1B messages	VERIFIED
14.3M aggressive orders	VERIFIED
147,113 wallets	VERIFIED
$84.3B taker notional	VERIFIED
BTC is strongly represented	VERIFIED
Wallet rank persistence ρ=0.52	VERIFIED
10-second markout ranking	VERIFIED
100-order minimum in main scoring design	VERIFIED
Top-decile concentration	VERIFIED
3.11 bps top-ventile adjusted markout	VERIFIED
1s R² = 12.31%	VERIFIED
+13.2% relative R² gain	VERIFIED
t=9.2	VERIFIED
200 activity-matched placebos	VERIFIED
Identity adds information beyond anonymous order flow	VERIFIED
Effect exists beyond 1 second	VERIFIED
Tree-model significance through ~10s	VERIFIED
Ridge improvement through 30s	VERIFIED
December 2025 replication	VERIFIED
Executable profitability	NOT VERIFIED
Receipt-to-fill alpha	NOT VERIFIED
Profitable copy trading	NOT VERIFIED
Cross-venue aggregate HL leadership	REJECTED
Minority-wallet cross-venue anticipation	SUPPORTED
Persistent wallet-level cross-venue heterogeneity	SUPPORTED
Full Level-4 reconstruction feasibility	VERIFIED
Counterparty identity availability	VERIFIED
Full-node data is cheap	REJECTED
API alone sufficient for long historical trader reconstruction	REJECTED

⸻

37. Major Revision: Latency Becomes Gate 0

TBIE v1.0 placed latency testing among later robustness tests.

This is changed.

LATENCY VIABILITY IS NOW TBIE GATE 0.

Before:

* full TBIE development,
* expensive node infrastructure,
* large-scale trader embeddings,
* sophisticated cohort modeling,
* or production integration,

the project must determine whether the identity signal survives realistic system latency.

⸻

38. Gate 0 Objective

The experiment must answer:

How much incremental trader-identity information remains after the delay between public event availability and the moment our order could realistically reach the market?

The delay must include:

Event becomes observable
↓
Network transport
↓
Event decoding
↓
State update
↓
Feature calculation
↓
Model inference
↓
Risk evaluation
↓
Order construction
↓
Order transmission
↓
Exchange acknowledgement / fill

⸻

39. Gate 0 Delay Ladder

Minimum synthetic delay tests:

0 ms
50 ms
100 ms
250 ms
500 ms
1 second
2 seconds
5 seconds
10 seconds
30 seconds

The 50 ms level is included for curve estimation.

It does not imply the initial Python system can reliably achieve 50 ms end-to-end latency.

⸻

40. Latency Curve

For every delay (d), estimate:

[
Edge(d)
]

and:

[
IncrementalInformation(d)
]

The goal is to estimate the signal’s decay curve rather than ask whether one arbitrary delay works.

Conceptually:

Signal
│\
│ \
│  \
│   \
│    \____
│
└────────────────
     Latency

We need to know where the economically usable portion disappears.

⸻

41. Two Latency Experiments

Latency testing must be divided into:

Experiment A: Synthetic Delay

Replay historical events while intentionally delaying trader-identity features.

Purpose:

Estimate theoretical decay.

Experiment B: Live Measured Delay

Measure actual:

source → receive
receive → feature
feature → decision
decision → order
order → acknowledgement
acknowledgement → fill

Purpose:

Estimate operational feasibility.

Synthetic delay alone is insufficient.

⸻

42. Receipt Time Becomes Mandatory

TBIE requires a clock distinction that the primary paper did not provide.

Every live event should preserve, where available:

consensus_time
exchange_time
block_time
local_receive_time
decode_complete_time
feature_ready_time
decision_time
order_send_time
exchange_ack_time
fill_time

Without this instrumentation we cannot answer the central executability question.

⸻

43. Clock Discipline

Use a monotonic local clock for latency measurement.

Wall-clock timestamps remain necessary for synchronization and auditability.

The system should therefore preserve both:

UTC timestamp

and:

monotonic process timestamp

where appropriate.

Clock synchronization quality must itself be monitored.

⸻

44. Gate 0 Pass Condition

Exact numerical thresholds must be determined before seeing final results.

Conceptually, Gate 0 passes only if trader identity retains:

1. measurable incremental information at realistic latency,
2. sufficient economic magnitude to plausibly survive costs,
3. robustness across multiple periods,
4. no dependence on one or two wallets,
5. sufficient observation frequency for the intended strategy.

⸻

45. Gate 0 Failure

If identity information disappears before our realistic execution latency:

TBIE_FAST_ALPHA_REJECTED

The project must then NOT:

* build low-value trader-following infrastructure,
* operate expensive Level-4 storage solely for TBIE,
* build complex trader embeddings,
* or force the feature into the AI.

The data may still remain useful for:

Risk intelligence
Adverse-selection detection
Market-regime analysis
Execution protection
Liquidity analysis

This distinction is important.

A feature can fail as alpha while succeeding as risk intelligence.

⸻

46. New TBIE Outcome Taxonomy

TBIE now has four possible research outcomes.

Outcome A

TBIE_ALPHA_VALIDATED

Trader identity provides executable incremental alpha.

Outcome B

TBIE_RISK_ONLY

Trader identity improves adverse-selection or execution-risk estimation but does not produce actionable directional alpha.

Outcome C

TBIE_RESEARCH_ONLY

Interesting statistical structure exists but has insufficient economic value.

Outcome D

TBIE_NO_EDGE

No durable incremental information survives rigorous testing.

This is more informative than a binary pass/fail system.

⸻

47. Revised Trader Intelligence Objective

TBIE should no longer be framed only as:

Can we follow successful traders?

The broader and better question is:

Can persistent pseudonymous behavioral identity improve our estimate of future return, adverse selection, execution quality, or market regime beyond anonymous market data?

This substantially increases the scientific usefulness of the experiment.

⸻

48. Revised Smart-Money Architecture

The system should distinguish:

Directional Information
Adverse-Selection Information
Execution Information
Liquidity Information
Regime Information

A wallet may be valuable for one dimension and useless for another.

Therefore a single global:

TraderScore

should eventually be avoided.

Prefer:

TraderInformationVector

⸻

49. Trader Information Vector

Conceptually:

[
T_i(t)=
[
I^{direction},
I^{adverse},
I^{liquidity},
I^{execution},
I^{regime}
]
]

conditioned on:

Asset
Direction
Horizon
Regime
Recency
Sample confidence

This is a more defensible architecture than ranking traders with one permanent number.

⸻

50. Weak Traders Remain Valuable

Nothing in the audit invalidates the Weak Trader hypothesis.

Persistently poorly timed traders may still provide information.

However, this remains:

PROJECT HYPOTHESIS

It has not been validated by the principal evidence reviewed here to the same degree as high-markout trader identity.

Therefore weak-trader inversion must be tested separately.

⸻

51. Smart Consensus Remains Experimental

The proposed:

[
Consensus_t=
\frac{\sum_i w_{i,t}s_{i,t}}
{\sum_i|w_{i,t}|}
]

remains architecturally valid.

But no external paper reviewed here proves that this exact weighting scheme produces alpha.

Status

UNVERIFIED PROJECT HYPOTHESIS

It must compete against:

Anonymous flow
Unweighted wallet flow
Top-decile flow
Skill-weighted flow
Regime-weighted flow

⸻

52. Concentration Test Becomes Mandatory

Because the evidence suggests informational value is concentrated in an upper tail, every TBIE experiment must run:

All informed wallets
minus top 1 wallet
minus top 5 wallets
minus top 10 wallets
minus top 1%
minus top 5%

The system must measure how much edge disappears.

A signal dependent on one wallet is not a robust platform-level edge.

⸻

53. Wallet Turnover Test

The system must measure:

new informed wallets entering
old informed wallets disappearing
wallet skill decay
wallet inactivity
wallet replacement rate

This determines whether the intelligence universe is renewable.

⸻

54. Wallet Identity Constraint

TBIE continues to treat:

wallet

as:

pseudonymous behavioral identifier

not:

verified human trader.

The primary research itself explicitly warns against equating wallet identity with a single human trader.

Therefore wallet clustering remains separate future research.

⸻

55. Hidden Hedge Problem

The evidence audit does not resolve hidden cross-venue hedging.

A Hyperliquid wallet may represent one leg of:

Spot hedge
Futures hedge
Options hedge
Cross-exchange hedge
Market-making inventory
OTC exposure

Therefore:

POSITION ≠ BELIEF

TBIE should learn empirical conditional outcomes rather than infer psychological intent.

⸻

56. Data Capture Decision

The audit strengthens the decision to preserve identity-linked information early.

M2 should preserve, where available and economically reasonable:

wallet
counterparty
side
price
size
order_id
start_position
twap_id
cloid
event_time
receive_time
raw_event_reference

This does NOT mean building the complete TBIE in M2.

It means avoiding irreversible information loss.

⸻

57. Important Scope Control

The project must not allow TBIE excitement to derail the Lean BTC MVP.

Therefore:

TBIE IS NOT ON THE BUILD 0.1 CRITICAL PATH.

The critical path remains:

M0
↓
M1 Storage
↓
M2 BTC Recorder
↓
M3 Integrity / Replay
↓
BTC Dataset
↓
Baseline Strategy
↓
Risk / Execution

TBIE experiments begin only when the underlying data pipeline is trustworthy.

⸻

58. Full Node Decision

A full Level-4-style node feed offers substantial research value.

However:

~100 GB/day default logs

creates meaningful infrastructure cost.

Therefore the node decision becomes a formal economic gate.

Before full deployment, estimate:

Raw GB/day
Compressed GB/day
Monthly storage
Replication
Backup
ClickHouse footprint
Object-storage footprint
Network egress
CPU
Replay cost
Retention policy

⸻

59. Node Gate

Full node infrastructure is approved only if at least one of the following is true:

Condition A

Gate 0 suggests actionable TBIE value.

Condition B

Level-4 data demonstrates independent value for execution/risk research.

Condition C

The infrastructure cost is sufficiently low to justify preserving an otherwise irrecoverable research asset.

Otherwise:

DEFER NODE

⸻

60. API-Only Limitation

Because user fill and historical-order endpoints expose bounded history, the project must not assume future API calls can reconstruct complete historical wallet behavior.

Therefore:

Capture-first architecture remains correct.

But capture scope must be proportional to evidence.

⸻

61. Revised Initial TBIE Experiment Order

The previous experiment sequence is changed.

New order:

Experiment 0

LATENCY VIABILITY

Does identity information survive realistic delay?

Experiment 1

PIT WALLET PERSISTENCE

Can we reproduce wallet-skill persistence without future leakage?

Experiment 2

INCREMENTAL INFORMATION

Does identity beat strong anonymous market baselines?

Experiment 3

ECONOMIC VALUE

Does the incremental information survive costs?

Experiment 4

COHORT CONSTRUCTION

Does skill weighting improve over raw flow?

Experiment 5

WEAK-TRADER DIVERGENCE

Does informed-vs-weak divergence add value?

Experiment 6

CROSS-VENUE INTELLIGENCE

Do selected Hyperliquid wallets predict future movement on other venues?

⸻

62. Experiment 0A: Historical Delay Replay

Construct:

[
X^{identity}_{t-d}
]

for:

[
d \in
{
0,
50ms,
100ms,
250ms,
500ms,
1s,
2s,
5s,
10s,
30s
}
]

Compare:

[
MarketModel
]

against:

[
MarketModel + Identity_{delayed}
]

The output is:

Identity Decay Curve

⸻

63. Experiment 0B: Live Latency Benchmark

Before claiming feasibility, record empirical latency distributions.

Required percentiles:

p50
p90
p95
p99
p99.9

for every stage of the pipeline.

Average latency is insufficient.

Tail latency matters because trading systems fail in tails.

⸻

64. Experiment 0C: Shadow Executability

Eventually:

Trader event observed
↓
TBIE feature generated
↓
Hypothetical trade generated
↓
Risk approved
↓
Shadow order timestamped
↓
Market execution simulated

Compare theoretical signal value with realistic shadow execution.

This is the first meaningful bridge from academic predictability to our trading system.

⸻

65. Benchmark Requirement

TBIE must never be evaluated against price-only models.

Minimum benchmark:

Price
BBO
L2 imbalance
Order-flow imbalance
Signed taker flow
Volatility
Spread
Funding
Open interest

where available and PIT-correct.

Only incremental value beyond this benchmark counts.

⸻

66. Model Complexity Rule

Initial TBIE research should begin with:

Linear / Ridge
Logistic models where appropriate
Gradient-boosted trees

before:

Transformers
Deep sequence models
Trader embeddings
Graph neural networks

If simple models extract the signal sufficiently, complexity is unnecessary.

If simple models show no robust information, deep learning must not be used as a fishing expedition.

⸻

67. Required Placebos

At minimum:

Activity-matched random wallets
Random wallet labels
Shuffled wallet ranking
Randomized event directions
Delayed identity
Future-leaked identity control
Random cohort sizes

The future-leaked control is particularly valuable because it quantifies how much false performance could be manufactured by violating point-in-time discipline.

⸻

68. Required Cost Stress

Any candidate TBIE trading signal must survive:

Base fees
2× fees
Base slippage
2× slippage
Expected latency
2× latency
Normal spread
Stress spread
Normal volatility
High volatility

A signal surviving only ideal execution is rejected.

⸻

69. Required Regime Tests

Evaluate independently under:

Trend
Range
High volatility
Low volatility
Funding extremes
High open interest
Low liquidity
Stress / liquidation events

Trader skill may be regime-specific.

That is acceptable.

What is prohibited is hiding regime dependence.

⸻

70. Research Reproducibility

Every TBIE experiment must store:

experiment_id
dataset_id
dataset_checksum
feature_version
wallet_score_version
model_version
code_commit
training_window
validation_window
test_window
latency_assumption
fee_assumption
slippage_assumption
random_seed
results

No result without provenance may influence architecture.

⸻

71. Updated Architectural Status

Following the evidence audit:

Scientific Plausibility: HIGH

Primary Evidence Verification: STRONG

Independent Replication: LIMITED

BTC Relevance: HIGH

Data Availability: HIGH

Point-in-Time Feasibility: HIGH

Latency Risk: VERY HIGH

Execution Uncertainty: VERY HIGH

Infrastructure Cost Risk: MEDIUM/HIGH

Potential Differentiation: HIGH

Production Readiness: NONE

Research Priority: HIGH

⸻

72. Updated Decision

TBIE remains:

ACCEPTED AS A HIGH-PRIORITY EXPERIMENTAL FEATURE FAMILY

The evidence audit strengthens the case that trader identity contains real market information.

It does NOT justify deployment.

The project must distinguish three propositions:

Proposition 1

Trader identity contains predictive information.

SUPPORTED

Proposition 2

Trader identity contains information beyond anonymous market data.

SUPPORTED

Proposition 3

Our system can convert that information into durable net trading profit.

UNPROVEN

The entire TBIE engineering program exists to test Proposition 3.

⸻

73. ADR Numbering Correction

The TBIE architecture decision must not hardcode:

ADR-004

until the repository’s actual ADR namespace is inspected.

The correct procedure during M0 is:

Inspect docs/ADR/
↓
Determine next canonical ADR number
↓
Create TBIE ADR
↓
Update index

The ADR title should be:

Trader Behavior Intelligence as an Experimental Feature Family

The number is repository-assigned.

⸻

74. M0 Impact

M0 does not require architectural redesign.

It requires only:

1. TBIE research status registration.
2. ADR namespace resolution.
3. Event schemas capable of preserving optional identity-linked information.
4. Clock architecture capable of future latency measurement.
5. No production dependency on TBIE.

⸻

75. M2 Impact

M2 remains the BTC Hyperliquid Recorder.

However, M2 must now satisfy an additional requirement:

Do not discard identity-linked fields or receive-time information when they are available at reasonable cost.

This preserves optionality without expanding M2 into a full trader-intelligence system.

⸻

76. What M2 Must Not Become

M2 must NOT become:

Trader ranking engine
AI model
Copy trading system
Wallet profiler
Cross-venue predictor
Full Level-4 research cluster

Its responsibility remains:

RELIABLE EVIDENCE CAPTURE

⸻

77. Research Trigger

After M2 and M3 demonstrate reliable capture and deterministic replay, TBIE Experiment 0 may begin.

The trigger is:

Recorder PASS
+
Integrity PASS
+
Replay PASS

Only then:

START LATENCY VIABILITY TEST

⸻

78. TBIE Kill Rule

The project adopts an explicit kill rule.

If repeated PIT-correct experiments show that trader-identity information:

* disappears before realistic execution,
* cannot survive costs,
* depends excessively on a few wallets,
* fails outside the original period,
* or provides no incremental value over strong market baselines,

then:

TBIE ALPHA DEVELOPMENT STOPS.

No founder override.

No model-complexity rescue attempt without a new falsifiable hypothesis.

⸻

79. TBIE Promotion Rule

TBIE can progress toward production only through:

External Evidence
↓
Internal Replication
↓
Latency Gate
↓
Incremental-Information Gate
↓
Economic Gate
↓
Robustness Gate
↓
Paper
↓
Shadow
↓
Limited Live

Skipping a gate is prohibited.

⸻

80. Final Evidence-Audited Conclusion

The evidence audit changes the interpretation of TBIE in an important way.

The original idea was:

Professional-trader behavior might be useful training data.

The evidence now supports a more precise proposition:

Persistent pseudonymous trader identity on Hyperliquid appears to contain measurable short-horizon information that is not fully captured by anonymous price, quote, and order-flow variables.

The strongest current evidence demonstrates:

* persistent wallet-level markout differences,
* out-of-sample predictive improvement,
* placebo resistance,
* nonlinear-model robustness,
* multi-second signal persistence,
* and temporal replication.

But the research does not establish:

* executable profitability,
* receipt-to-fill viability,
* sustainable alpha after costs,
* scalability,
* or production robustness.

Therefore the project’s next scientific question is no longer:

Is trader identity interesting?

The evidence suggests that it is.

The question is:

CAN WE GET THERE IN TIME?

More formally:

After accounting for the actual delay between a Hyperliquid trader event becoming observable and our own executable order reaching the market, does point-in-time trader identity still provide economically meaningful incremental information beyond price, L2, anonymous order flow, derivatives state, and realistic trading costs?

Until that question is answered:

TBIE = HIGH-PRIORITY RESEARCH

not:

TBIE = TRADING EDGE

⸻

81. Immediate Engineering Decision

Proceed with:

M0 Rev.2
↓
M1 Storage Foundation
↓
M2 BTC Recorder
↓
M3 Data Integrity + Replay

while preserving:

Trader identity
Counterparty identity where available
Position context where available
Raw events
Consensus/event timestamps
Local receive timestamps
Monotonic receive timestamps

Then run:

TBIE EXPERIMENT 0 — LATENCY VIABILITY

before committing to expensive full-node TBIE infrastructure.

⸻

82. Governing Principle

Capture what may become irrecoverable.
Verify what can be verified.
Measure latency before assuming executability.
Buy infrastructure only after evidence earns it.
Treat predictive information and profitable execution as two different hypotheses.