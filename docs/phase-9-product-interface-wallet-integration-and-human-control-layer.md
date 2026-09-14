Product Interface, Wallet Integration & Human Control Layer

Version: 1.0
Phase: 9 — Product Interface, Wallet Integration & Human Control Layer
Core Assets: BTC, ETH, SOL, BNB
System: AI-Powered Automated Trading Platform
Initial Wallets: Phantom + Trust Wallet
Primary Execution Venue: Hyperliquid, subject to final production validation
Status: Product & Security Architecture
Criticality: Maximum

⸻

1. Purpose

Phase 9 defines the human-facing control layer of the trading system.

Its purpose is to provide a professional trading interface without weakening the safety architecture established in previous phases.

The product must allow users to:

* Connect a wallet
* Authenticate ownership
* Authorize trading
* Fund or access the trading account
* Observe AI intelligence
* Understand active risk
* Use Autopilot
* Use Copilot
* Use Research Mode
* Inspect positions
* Inspect performance
* Understand why a trade exists
* Pause automation
* Reduce exposure
* Close positions
* Revoke trading authorization

The interface must not allow the user, AI or presentation layer to bypass hard Risk Engine limits.

⸻

2. Product Philosophy

The application should feel like:

an intelligent trading terminal

rather than:

a crypto bot dashboard.

The visual hierarchy should prioritize:

1. Current Risk
2. Current Positions
3. System State
4. AI Intelligence
5. Market Context
6. Performance
7. Controls

Decorative information must not compete with capital-critical information.

⸻

3. Three-Layer Account Model

The interface must distinguish three concepts.

Layer A — User Wallet

Examples:

Phantom

Trust Wallet

Purpose:

* Identity
* Ownership
* Authorization
* Funding interactions

Layer B — Trading Authorization

Permission allowing the automated system to perform defined trading actions.

Layer C — Trading Account

The actual venue account/subaccount where:

* Collateral
* Positions
* Margin
* Funding
* Orders
* P&L

exist.

These must not be presented as one indistinguishable object.

⸻

4. Wallet Is Not the Trading Engine

The connected wallet should not become the backend execution credential.

Architecture:

User Wallet

↓

User Authorization

↓

Restricted Trading Authorization

↓

Execution Infrastructure

The application must never require the backend to store the seed phrase or private key of the user’s primary wallet.

⸻

5. Phantom Integration

Phantom’s current Connect SDK supports existing wallet connections through its browser extension and mobile flows.

For the web application, the preferred architecture should evaluate:

Phantom React SDK

with:

* Existing Phantom wallet
* Injected extension
* Phantom mobile flow
* Ethereum address access

The application should initially favor connecting an existing user-controlled wallet rather than silently creating a new embedded wallet.

⸻

6. Phantom Chain Requirement

Our execution architecture requires careful attention to address type.

Hyperliquid account interaction is based on an EVM-style account address.

Therefore Phantom integration must request and validate the appropriate:

Ethereum address

for trading-account authorization.

The UI must not accidentally display the user’s Solana address as though it were the execution account.

⸻

7. Phantom Capability Detection

The wallet adapter should detect:

* Wallet installed
* Wallet connected
* Correct account selected
* Required address type available
* Account changed
* Connection lost
* Authorization expired

Any account change should trigger:

Trading Freeze

↓

Identity Revalidation

↓

Authorization Check

↓

Risk Reconciliation

before new trades are permitted.

⸻

8. Phantom Session Behavior

Auto-reconnection may improve usability.

However:

Wallet Connected

must not automatically mean:

Autopilot Authorized

A restored wallet session should restore identity state only.

Trading authorization must be independently validated.

⸻

9. Trust Wallet Integration

Trust Wallet currently supports WalletConnect v2 for mobile dApp integration and supports both:

EVM

and:

Solana

connections.

For our initial product, Trust Wallet integration should primarily use:

WalletConnect

with direct wallet-provider support where appropriate.

⸻

10. Trust Wallet Mobile UX

Mobile connection should support:

Deep Link

rather than requiring users to manually copy connection information.

Expected flow:

Connect Wallet

↓

Trust Wallet

↓

Open Trust Wallet

↓

Approve Connection

↓

Return to App

The interface must handle:

* User rejection
* App switching
* Session timeout
* Missing wallet
* Wrong account
* Connection interruption

cleanly.

⸻

11. Wallet Adapter Layer

The application should not scatter Phantom-specific and Trust-specific logic throughout the UI.

Instead:

Phantom Adapter

Trust Wallet Adapter

↓

Unified Wallet Interface

The rest of the application consumes normalized states such as:

CONNECTED

DISCONNECTED

ADDRESS

CHAIN

SIGN

SESSION

This makes future addition of:

* MetaMask
* WalletConnect-compatible wallets
* Native wallet

substantially easier.

⸻

12. Wallet-Agnostic Core

The trading system must not know whether the user originally connected through:

Phantom

or:

Trust Wallet

except where a wallet-specific signature flow is required.

Trading logic consumes:

Verified User Identity

and:

Trading Authorization

not wallet-brand-specific state.

⸻

13. Wallet Authentication

Wallet connection alone is insufficient for application authentication.

The preferred pattern is:

Connect Wallet

↓

Server Issues Nonce

↓

User Signs Authentication Message

↓

Server Verifies Signature

↓

Session Created

The signed message must be domain-bound and time-bound.

⸻

14. Authentication Message

The authentication message should clearly state that the signature:

authenticates wallet ownership

and:

does not execute a trade or transfer funds.

This distinction should be visible to the user.

⸻

15. Replay Protection

Authentication challenges should include:

* Unique nonce
* Domain
* Wallet address
* Issue time
* Expiration
* Chain/context identifier where required

A used or expired challenge must not authenticate another session.

⸻

16. Session Architecture

Application sessions should have:

* Expiration
* Rotation
* Revocation
* Device/session identification
* Server-side invalidation

Disconnecting the UI and revoking trading authorization are separate actions.

⸻

17. Trading Authorization

The system must distinguish:

Login Permission

from:

Trading Permission

Autopilot requires explicit trading authorization.

The UI should explain:

Connecting your wallet does not give the AI unrestricted control over your wallet.

⸻

18. API / Agent Wallet Authorization

Where Hyperliquid API wallets are used, the trading process should use dedicated agent/API credentials rather than the primary wallet.

The user authorizes the trading relationship.

The automation layer signs permitted trading actions through its dedicated execution credential.

⸻

19. Authorization Scope

The product should make the effective trading scope understandable.

Where technically enforceable, the user should be able to understand:

* Which trading account is authorized
* Which environment is active
* Whether Autopilot is enabled
* Current risk policy
* Authorization status
* How to revoke access

The UI must not imply restrictions that are not actually enforced at the protocol/backend level.

⸻

20. Revocation

The application must provide an obvious:

REVOKE TRADING ACCESS

control.

Revocation is distinct from:

Pause Autopilot

and:

Disconnect Wallet

The interface must explain the difference.

⸻

21. Disconnect vs Pause vs Revoke

These three actions have different meanings.

Disconnect Wallet

Disconnects the current UI wallet session.

It does not necessarily cancel existing orders or positions.

Pause Autopilot

Stops creation of new automated exposure.

Existing positions continue to be managed according to safety policy.

Revoke Trading Access

Removes the automation’s trading authorization where supported.

This distinction must be explicit.

⸻

22. Main Operating Modes

The product has three principal modes.

AUTOPILOT

AI can propose trades and the validated automated pipeline may execute them after Risk approval.

COPILOT

AI produces trade candidates.

User approval is required before execution.

RESEARCH

No trade execution.

Market intelligence, models, backtests and analysis remain available.

⸻

23. Mode State Must Be Obvious

The current operating mode should always be visible.

The user must never wonder:

“Can the system currently place trades?”

Recommended persistent state:

AUTOPILOT — ACTIVE

AUTOPILOT — PAUSED

COPILOT

RESEARCH ONLY

⸻

24. Mode Switching

Switching into a more permissive mode requires stronger confirmation than switching into a safer mode.

Example:

Autopilot → Paused

Immediate.

Paused → Autopilot

Requires confirmation and risk-state validation.

Safety-reducing actions should be easier than risk-increasing actions.

⸻

25. Autopilot Activation

Autopilot activation should require:

1. Wallet authenticated
2. Trading authorization valid
3. Risk profile valid
4. Trading account funded
5. Venue healthy
6. Data healthy
7. Model approved
8. No Safe Mode
9. User confirmation

If any critical condition fails:

AUTOPILOT CANNOT START

⸻

26. Autopilot Activation Summary

Before first activation or material risk-policy changes, the interface should summarize:

Assets

BTC / ETH / SOL / BNB

Maximum permitted risk

Maximum leverage policy

Current trading strategies

Emergency controls

Authorization

The user should understand what is being enabled.

⸻

27. Copilot Flow

A Copilot opportunity should display:

Asset

LONG / SHORT

Entry

Stop

Take Profit / Exit Plan

Estimated Risk

Expected R:R

AI Probability

Market Regime

Trade Expiration

Buttons:

APPROVE

REJECT

Approval does not bypass Risk Engine.

⸻

28. Copilot Expiration

Trade recommendations must expire.

If the user approves after the market has materially changed:

the system must perform a new:

Data Freshness Check

Risk Check

Price Deviation Check

before execution.

The original recommendation is not an unconditional order ticket.

⸻

29. Research Mode

Research Mode should provide:

* Market intelligence
* Historical analysis
* Model outputs
* Backtests
* Strategy comparisons
* Regime analysis
* Feature explanations
* Shadow performance

but no trading permission.

This makes the application useful even when capital is not exposed.

⸻

30. Information Architecture

Recommended primary navigation:

Overview

Markets

AI

Positions

Activity

Research

Settings

On mobile, the most important destinations may be condensed into a bottom navigation.

⸻

31. Overview Screen

The Overview should answer within seconds:

How much capital do I have?

How much is currently at risk?

Am I making or losing money?

What positions exist?

What does the AI currently see?

Is Autopilot active?

Is the system healthy?

⸻

32. Overview Hierarchy

Recommended top section:

Equity

Available Margin

Today’s P&L

Current Drawdown

Capital at Risk

Then:

BTC

ETH

SOL

BNB

with compact intelligence states.

Then:

Active Positions

Then:

Portfolio Risk

Then:

System Health

⸻

33. Avoid Vanity Metrics

The primary dashboard should not emphasize:

Win Rate

as the dominant success metric.

More important information includes:

* Net P&L
* Drawdown
* Risk-adjusted performance
* Current exposure
* Capital at risk
* Execution costs

Win Rate can appear in analytics.

It should not dominate the product.

⸻

34. Asset Intelligence Card

Each asset card may show:

BTC

Price

24h movement

AI State

Market Regime

Tradeability

Uncertainty

Example:

BTC

NO TRADE

Bullish structure

Moderate uncertainty

The UI should avoid implying certainty.

⸻

35. Confidence Presentation

Do not display:

AI IS 87% SURE BTC WILL RISE

unless that statement exactly matches the calibrated target.

Preferred representation:

Model Probability: 67%

with accessible explanation:

Historical outcomes with comparable model scores have shown approximately this level of success for the defined prediction target.

Even this wording is allowed only when calibration evidence supports it.

⸻

36. Confidence vs Risk

Confidence and risk must be visually separate.

Example:

Model Probability

72%

Trade Risk

0.35% of equity

Leverage

2.1×

The interface must not visually suggest:

72% confidence → high leverage

⸻

37. Uncertainty Display

Where meaningful, display:

Low

Moderate

High

uncertainty alongside probability.

Example:

Probability: 68%

Uncertainty: High

can legitimately produce:

NO TRADE

⸻

38. Market Regime

Each asset should display the detected regime.

Example:

BTC

Bull Trend

Moderate Volatility

Normal Liquidity

Regime should be treated as context, not a trade instruction.

⸻

39. AI Screen

The AI screen should explain the system’s current market interpretation.

Recommended sections:

Current Opportunities

Market Regimes

Model Agreement

Rejected Opportunities

NO TRADE States

Prediction History

⸻

40. WHY THIS TRADE?

Every active or proposed trade should have:

WHY THIS TRADE?

This panel exposes the actual quantitative evidence behind the decision.

Example:

Trend
Strong Positive

Momentum
Positive

Order Flow
Moderate Positive

Funding
Neutral

Open Interest
Constructive

BTC Context
Supportive

Volatility
Acceptable

Regime
Bull Trend

⸻

41. Explanation Integrity

The explanation panel must consume actual model/risk evidence.

An LLM may convert structured evidence into readable language.

It may not invent reasons after the trade occurred.

Architecture:

Quantitative Evidence

↓

Structured Explanation Object

↓

Optional LLM Translation

↓

Human-Readable Explanation

⸻

42. WHY NOT TRADE?

NO TRADE should also be explainable.

Example:

WHY NO TRADE?

Trend:
Positive

Momentum:
Positive

But:

Uncertainty:
High

Spread:
Elevated

Expected Edge After Costs:
Insufficient

Decision:

NO TRADE

This helps users understand that inactivity is intentional intelligence.

⸻

43. WHY WAS THIS REJECTED?

When Risk rejects an AI candidate:

display the distinction.

Example:

AI

SOL LONG Candidate

Risk Engine

REJECTED

Reason:

Portfolio crypto-beta exposure already above permitted level.

This reinforces the architecture:

AI ≠ Risk Authority

⸻

44. Position Screen

Each position should display:

Asset

LONG / SHORT

Position Size

Entry

Mark Price

Unrealized P&L

Stop

Take Profit / Exit Plan

Leverage

Margin Mode

Liquidation Price

Liquidation Distance

Funding

Fees

Strategy

Model

⸻

45. Risk-First Position Design

Liquidation information must not be hidden behind multiple screens.

For leveraged positions, the user should easily see:

Stop Distance

and:

Liquidation Distance

as different concepts.

⸻

46. Position Timeline

A position should have an event timeline:

Signal Generated

↓

Risk Approved

↓

Order Submitted

↓

Filled

↓

Protection Confirmed

↓

Position Managed

↓

Exit

This provides understandable auditability.

⸻

47. Position Attribution

After closing a trade, the interface may explain:

Signal P&L

Funding

Fees

Execution Cost

Net P&L

This teaches the user why gross market movement and actual result differ.

⸻

48. Portfolio Risk Screen

The Risk screen should show:

Current Capital at Risk

Portfolio Exposure

Long Exposure

Short Exposure

Crypto Beta

Asset Concentration

Strategy Concentration

Current Drawdown

Daily Loss Usage

Distance to Risk Limits

⸻

49. Correlation Visualization

The interface should communicate when several positions are effectively one risk.

Example:

BTC LONG

ETH LONG

SOL LONG

Warning:

High correlated directional exposure

The user should not be given a false sense of diversification from position count.

⸻

50. Global Risk State

The system should display one persistent global risk state:

NORMAL

ELEVATED

RISK REDUCTION

NO NEW TRADES

SAFE MODE

EMERGENCY

This should be generated from actual Risk Engine state.

⸻

51. System Health

The UI should separately display operational health:

Market Data

AI Engine

Risk Engine

Execution Engine

Venue

Wallet Authorization

Example:

All Systems Operational

or:

Execution Degraded

The user must know when automation is impaired.

⸻

52. Autopilot Control

Autopilot should have a prominent control.

States:

ACTIVE

PAUSED

SAFE MODE

The action:

PAUSE AUTOPILOT

should be immediately accessible.

⸻

53. Pause Semantics

Pause should mean:

No new automated exposure

but should not blindly abandon existing positions.

Existing risk remains under management unless the user explicitly chooses another action.

⸻

54. Emergency Controls

The interface should expose clearly separated controls:

PAUSE AUTOPILOT

CANCEL ENTRY ORDERS

REDUCE EXPOSURE

CLOSE POSITION

CLOSE ALL POSITIONS

REVOKE TRADING ACCESS

They must not be merged into one ambiguous red button.

⸻

55. Destructive Confirmation

Actions such as:

CLOSE ALL POSITIONS

require explicit confirmation.

The confirmation should show:

* Number of positions
* Estimated exposure
* Potential execution implications
* Whether open orders will also be cancelled

The UI should not bury emergency action under excessive friction, but accidental activation must be difficult.

⸻

56. Emergency UX Principle

Normal risk-increasing actions can tolerate deliberate friction.

Emergency risk-reducing actions must remain quickly accessible.

The system should never require multiple obscure menus to stop new trading.

⸻

57. Activity Screen

Activity should provide a unified chronological ledger.

Event types include:

* AI prediction
* NO TRADE
* Risk rejection
* Order submission
* Fill
* Partial fill
* Stop update
* TP update
* Funding
* Fee
* Position close
* Autopilot pause
* Authorization change
* System incident

⸻

58. Filterable Audit History

Users should be able to filter by:

Asset

Strategy

Event

Date

Result

This turns the Activity screen into an understandable audit trail.

⸻

59. Performance Screen

Performance should emphasize:

Net Return

Net P&L

Maximum Drawdown

Sharpe

Sortino

Profit Factor

Expectancy

Fees

Funding

Slippage

Exposure

Win Rate remains secondary.

⸻

60. Performance Decomposition

Users should be able to inspect:

BTC Performance

ETH Performance

SOL Performance

BNB Performance

and:

Strategy Performance

and:

Regime Performance

This prevents aggregate profitability from hiding weak components.

⸻

61. Benchmarking

Where useful, performance may be compared against:

BTC Buy-and-Hold

Asset Buy-and-Hold

Cash

or other validated benchmarks.

Comparisons must use matching periods and avoid misleading scale differences.

⸻

62. AI Performance vs Trading Performance

The interface should distinguish:

Model Accuracy / Calibration

from:

Trading Performance

A model can be statistically useful while execution destroys its edge.

Likewise, temporary trading profit does not prove model quality.

⸻

63. Notification Architecture

Notifications should be categorized.

Critical

* Safe Mode
* Position protection failure
* Reconciliation failure
* Emergency close
* Authorization revoked
* Critical system failure

Trading

* Position opened
* Position closed
* Stop triggered
* Take Profit
* Copilot approval required

Informational

* Market regime change
* Research report
* Model update

Critical alerts must not be drowned in ordinary notifications.

⸻

64. Notification Fatigue

The system should avoid notifying the user for every minor model fluctuation.

Too many alerts make important alerts invisible.

Notification severity and rate limiting should therefore be designed deliberately.

⸻

65. Mobile UX

Mobile should prioritize:

Risk State

Equity

P&L

Positions

Autopilot

Emergency Controls

Deep research analytics may remain richer on desktop.

⸻

66. Desktop UX

Desktop can provide the full trading terminal:

Chart

Order/Position Intelligence

AI Evidence

Portfolio Risk

Activity

Research

without requiring constant page switching.

⸻

67. Responsive Rather Than Reduced Safety

Mobile may simplify presentation.

It must not simplify safety information.

Critical information such as:

* Position
* Stop
* Liquidation
* Risk state
* Autopilot state

must remain visible.

⸻

68. Chart Architecture

The main chart should support overlays for:

* Entry
* Stop
* Take Profit
* Position
* AI signal
* Relevant regime transitions

Avoid turning the chart into a decorative constellation of dozens of indicators.

⸻

69. AI Signal History

Historical signals may be shown on the chart.

But the UI must distinguish:

Actual historical prediction generated at the time

from:

Retrospectively calculated signal

These are not equivalent.

⸻

70. Research Interface

Advanced users should be able to inspect:

* Strategy
* Model version
* Dataset
* Backtest
* Shadow results
* Limited-Live results
* Calibration
* Regime behavior
* Feature contribution

This preserves transparency without overloading the main trading interface.

⸻

71. Model Version Visibility

Every live position should be traceable to:

Strategy Version

and:

Model Version

The normal user interface may show simplified names.

The detailed audit panel exposes full identifiers.

⸻

72. Risk Configuration

Users may be allowed to choose among validated risk profiles.

Potential examples:

Conservative

Balanced

Advanced

However, these labels must map to explicit validated configurations.

They must not merely change leverage cosmetically.

⸻

73. No Arbitrary Risk Sliders

Avoid a slider such as:

Risk: 1–100

unless its economic meaning is rigorously defined.

Risk controls should correspond to understandable concepts.

Example:

Maximum permitted capital at risk

Maximum portfolio exposure

Maximum leverage policy

⸻

74. Hard Safety Ceiling

User-selected settings may reduce risk below system limits.

They may not exceed hard validated safety ceilings.

Conceptually:

User Limit ≤ System Hard Limit

⸻

75. Risk Profile Change

Increasing risk requires:

* Explicit confirmation
* Recalculation
* Configuration version
* Audit record

Reducing risk should be easier.

⸻

76. Wallet Balance vs Trading Equity

The UI must clearly distinguish:

Wallet Balance

from:

Trading Account Equity

from:

Available Margin

from:

Capital at Risk

These are not interchangeable.

⸻

77. Funding Flow

If the user needs to fund the trading account, the interface should make the destination and amount explicit.

The user must know:

* Source wallet
* Destination/account
* Asset
* Network
* Amount
* Expected result

Ambiguous deposit UX is unacceptable.

⸻

78. Withdrawal UX

Withdrawals should remain user-controlled.

Automated trading logic should not initiate discretionary withdrawals.

Withdrawal controls should be separated from trading automation.

⸻

79. Builder Fee Transparency

If the product eventually uses Hyperliquid builder codes to monetize execution, any builder fee must be clearly disclosed before authorization.

The user should be able to understand:

Trading Fee

and:

Application/Builder Fee

as separate economic concepts.

Hidden execution fees are unacceptable.

⸻

80. Monetization Must Not Distort Trading

If revenue is based partly on trading volume, a conflict of interest exists.

The product must never optimize trade frequency simply to generate builder fees.

The AI objective remains:

Net Risk-Adjusted User Outcome

not:

Maximum Order Count

⸻

81. User Consent

The application should explicitly distinguish consent for:

* Authentication
* Trading authorization
* Autopilot activation
* Risk configuration
* Builder/application fee
* Data/privacy policy

One generic acceptance checkbox should not silently authorize everything.

⸻

82. Product Language

Avoid claims such as:

Guaranteed Profit

AI Never Misses

Safe Returns

95% Accurate Trading

unless a narrowly defined statistical statement is demonstrably supported.

The interface must communicate probabilistic uncertainty.

⸻

83. Explainable Losses

After a losing trade, the application should not fabricate an excuse.

It should show:

Original hypothesis

Original probability

Original risk

What actually happened

A probabilistic system can make a valid decision that loses.

This should be explainable without rewriting history.

⸻

84. No Retrospective Confidence

The UI must preserve the confidence that existed:

before the trade

not recompute a prettier confidence score afterward.

Historical decision records are immutable.

⸻

85. Data Freshness Indicator

Advanced views should expose data freshness.

If a critical source becomes stale:

AI Trading Suspended

should be visible.

The user should not see a normal-looking interface while the backend has stopped receiving reliable data.

⸻

86. Degraded State UX

When a subsystem is degraded:

do not simply show:

Something went wrong.

Show:

What’s affected

and:

What the system is doing about it.

Example:

Order Book Feed Delayed

New trades paused

Existing positions remain protected

⸻

87. Offline UX

If the user’s device loses internet:

the UI becomes unavailable,

but server-side risk management must continue operating.

The product must communicate this architecture clearly.

User-device connectivity must not be required for protective risk management.

⸻

88. Server Independence

The trading engine, Risk Engine and protective systems run independently of the frontend.

Closing the browser or phone application must not:

* Cancel risk protection
* Stop position monitoring
* Corrupt trading state

unless the user explicitly requests an appropriate control action.

⸻

89. Accessibility

Critical states must not rely solely on color.

For example:

RED

should also include:

SAFE MODE

and an icon/state label.

This improves accessibility and reduces ambiguity.

⸻

90. Confirmation Design

Confirmations should focus on consequences.

Weak:

Are you sure?

Better:

Enable Autopilot?

The system may open and close leveraged perpetual positions within your validated risk limits without asking for individual confirmation.

This confirmation is materially informative.

⸻

91. Security Center

Settings should contain a dedicated:

Security & Authorization

section showing:

* Connected wallet
* Trading account
* Trading authorization
* Session status
* Authorized execution credential status
* Last authorization
* Revoke control
* Recent security events

⸻

92. Session Management

Future versions should support viewing and revoking active application sessions.

Examples:

iPhone

MacBook

Browser

Unexpected sessions should be revocable.

⸻

93. Wallet Change Protection

Changing the connected wallet while Autopilot is active should not silently transfer control context.

Required flow:

Detect Account Change

↓

Freeze New Risk

↓

Invalidate UI Trading Session

↓

Reauthenticate

↓

Reconcile Trading Account

↓

Explicit Resume

⸻

94. Wrong-Network Protection

Where wallet operations require a specific chain/network:

the UI should detect incorrect network state before requesting signatures.

Never rely on the user to infer the required network from a failed transaction.

⸻

95. Signature Transparency

Before requesting a wallet signature, the interface should state the purpose.

Examples:

Sign to Log In

Sign to Authorize Trading

Sign to Approve Builder Fee

Sign Transaction

Different actions must not look identical.

⸻

96. Signature Minimization

The product should minimize unnecessary wallet-signature requests.

Excessive signatures:

* Damage UX
* Increase phishing habituation
* Make important authorization signatures less distinguishable

Every signature request must have a clear purpose.

⸻

97. Progressive Disclosure

The interface should serve both normal and advanced users.

Primary view:

Simple.

Detailed view:

Deep.

Example:

Risk: Normal

Tap:

Portfolio exposure, correlation, drawdown, margin, liquidation metrics.

This avoids both extremes:

oversimplification

and:

terminal overload.

⸻

98. Default Safety

Default product state after onboarding should be:

AUTOPILOT OFF

The user explicitly enables automation after configuration and authorization.

⸻

99. First-Run Flow

Recommended onboarding:

Welcome

↓

Connect Wallet

↓

Verify Ownership

↓

Trading Account Detection / Setup

↓

Funding Status

↓

Risk Profile

↓

Trading Authorization

↓

Product Tour

↓

Research / Copilot Available

↓

Explicit Autopilot Activation

Autopilot should not become active merely because onboarding completed.

⸻

100. Risk Education

Before enabling Autopilot for the first time, the user should understand:

* Perpetual futures can lose capital
* Leverage increases risk
* Stop orders are not guaranteed execution prices
* AI probabilities are not guarantees
* Safe Mode may stop new trading
* Losses remain possible even when the system operates correctly

This should be concise, not buried inside legal text.

⸻

101. Mode Recommendation

For new users, the safest progression should be:

Research

↓

Copilot

↓

Autopilot

The product may recommend this progression.

It should not force experienced users through arbitrary gamification.

⸻

102. Product State Machine

The overall product should maintain explicit states such as:

DISCONNECTED

CONNECTED

AUTHENTICATED

AUTHORIZED

READY

AUTOPILOT ACTIVE

PAUSED

SAFE MODE

EMERGENCY

The UI renders from authoritative backend state.

⸻

103. Backend Is Source of Truth

The frontend must never infer critical state from button appearance.

For example:

A green Autopilot button does not prove Autopilot is active.

The backend returns:

actual system state

and the UI renders it.

⸻

104. Optimistic UI Restriction

Optimistic UI updates should not be used for critical trading actions.

After:

Close Position

the interface should display:

Closing…

until venue confirmation exists.

It must not immediately show:

Closed

based solely on button press.

⸻

105. Real-Time Updates

Live state should use streaming updates where appropriate for:

* Orders
* Fills
* Positions
* P&L
* Risk
* System health

Periodic reconciliation remains necessary behind the interface.

⸻

106. Stale UI Protection

If the frontend loses its live state stream:

show:

LIVE DATA DISCONNECTED

Do not leave old P&L and position information looking current.

⸻

107. Frontend Technology

The current recommended web stack remains:

Next.js

React

TypeScript

with:

* Server-authenticated sessions
* Real-time state streaming
* Wallet adapters
* Strong typed API contracts

Final library selection should be benchmarked before implementation.

⸻

108. Wallet Integration Strategy

Initial recommendation:

Phantom

Use official Phantom Connect React/Browser SDK for supported existing-wallet flows.

Trust Wallet

Use WalletConnect v2 / supported Trust provider flows.

Internal Application

Normalize both behind a unified Wallet Adapter interface.

This avoids coupling the trading product to one wallet vendor.

⸻

109. Native Mobile Strategy

The first product does not necessarily require separate native iOS and Android codebases.

A responsive web application can validate product-market and trading UX first.

Native applications should be introduced when they provide measurable value such as:

* Better notifications
* Better wallet deep-link flow
* Biometric control
* Mobile reliability

This remains a product decision, not an architectural requirement.

⸻

110. Native Wallet Boundary

The future native non-custodial wallet must remain a separate major project layer.

Do not mix:

building a secure wallet

with:

proving the trading engine

during V1.

Native wallet architecture introduces:

* Key management
* Backup/recovery
* Secure enclave considerations
* Transaction simulation
* Wallet security
* Chain support
* Additional audit requirements

It should begin only after the trading product demonstrates value.

⸻

111. Future Wallet Migration

Because the core uses a Wallet Adapter abstraction:

Phantom

Trust Wallet

Future Native Wallet

all connect to the same higher-level product identity/authorization architecture.

This avoids rewriting the trading system later.

⸻

112. Auditability

Every user action affecting capital or authorization should be logged.

Examples:

* Wallet connected
* Authentication
* Autopilot enabled
* Autopilot paused
* Risk profile changed
* Copilot trade approved
* Position manually closed
* Trading authorization revoked

This allows reconstruction of human/system interaction.

⸻

113. Human vs AI Attribution

For every position, record initiation source:

AUTOPILOT

COPILOT APPROVED

MANUAL RISK REDUCTION

This allows later performance analysis by operating mode.

⸻

114. User Intervention Analysis

Manual intervention should be measurable.

The system may eventually compare:

Original automated outcome

vs.

Outcome after human intervention

This provides evidence about whether intervention improves or harms performance.

It must not be used to shame or manipulate the user.

⸻

115. Product Analytics Boundary

Product analytics may measure:

* Screen usage
* Feature usage
* Errors
* Onboarding completion

Sensitive trading and wallet information should not be casually sent to third-party analytics platforms.

Security and privacy review is required before instrumentation.

⸻

116. Error Messages

Trading errors must be actionable.

Bad:

Transaction failed.

Better:

Order not submitted. Current market price moved beyond the approved execution range. No position was opened.

The user should know whether capital was affected.

⸻

117. Unknown State Error

If the system does not know whether an order executed:

do not display:

Failed

Display:

Execution status being verified

and block conflicting actions until reconciliation.

Unknown is a distinct state.

⸻

118. UI Security Principle

The interface must never claim:

Safe

when the underlying Risk Engine is unavailable.

UI state is subordinate to backend truth.

⸻

119. Regulatory Architecture

Because the product may eventually be offered publicly, jurisdiction and product-access rules must remain separable from the trading engine.

The architecture should support:

* Geographic availability policy
* Feature restrictions
* Disclosure versions
* Consent records

without hard-coding regulatory assumptions into strategy code.

Legal analysis remains a separate workstream before public launch.

⸻

120. Phase 9 Deliverables

Implementation must eventually produce:

Design System

Responsive Trading Terminal

Unified Wallet Adapter

Phantom Integration

Trust Wallet Integration

Wallet Authentication

Trading Authorization UX

Autopilot Interface

Copilot Interface

Research Interface

WHY THIS TRADE?

WHY NO TRADE?

Risk Dashboard

Position Management

Activity Ledger

Performance Dashboard

System Health Interface

Emergency Controls

Security & Authorization Center

Notification Architecture

⸻

121. Phase 9 Acceptance Gate

Phase 9 cannot pass until:

1. Phantom connection works reliably.
2. Trust Wallet connection works reliably.
3. Wallet ownership is cryptographically authenticated.
4. Primary wallet private keys are never handled by the application backend.
5. Wallet connection and trading authorization are separate.
6. Autopilot is OFF by default.
7. Autopilot activation requires explicit consent.
8. AI cannot bypass Risk Engine limits.
9. User cannot exceed hard Risk Engine ceilings through UI.
10. Wallet/account change freezes new trading.
11. Current operating mode is always visible.
12. Current risk state is always visible.
13. Active positions expose stop and liquidation information.
14. NO TRADE decisions can be explained.
15. Risk rejections can be explained.
16. Emergency controls are immediately accessible.
17. Pause does not abandon existing risk.
18. Critical actions use authoritative backend confirmation.
19. Stale frontend state is visibly identified.
20. All capital-affecting user actions are auditable.
21. Mobile and desktop safety behavior is equivalent.
22. Wallet-specific logic remains isolated from the trading core.

⸻

122. Final Product Architecture

Phantom / Trust Wallet

↓

Unified Wallet Adapter

↓

Authentication

↓

Trading Authorization

↓

PRODUCT CONTROL LAYER

↓

Research / Copilot / Autopilot

↓

AI Intelligence

↓

Risk Engine

↓

Execution Engine

↓

Hyperliquid

↓

Orders / Positions / Fills

↓

Real-Time State

↓

Risk + Position + AI + Performance UI

with independent:

PAUSE

REDUCE

CLOSE

REVOKE

controls.

⸻

123. Strategic Conclusion

The product should not attempt to make automated leveraged trading feel harmless.

It should make sophisticated trading:

understandable

controllable

auditable

and:

risk-bounded.

The best interface is not the interface that hides complexity.

It is the interface that exposes the right complexity at the right moment.

⸻

Phase 9 Decision

APPROVED AS PRODUCT & WALLET ARCHITECTURE

Subject to:

* Wallet integration testing
* Security review
* Mobile deep-link testing
* Hyperliquid authorization testing
* UX usability testing
* Public-product legal review

The next phase is:

Phase 10 — Security Architecture, Independent Audit & Production Launch Gate

Phase 10 determines whether the entire system is technically and operationally safe enough to move from a validated trading product into real production.

⸻

Document: Product Interface, Wallet Integration & Human Control Layer
Version: 1.0
Phase: 9
Core Assets: BTC / ETH / SOL / BNB
Next Phase: Security Architecture, Independent Audit & Production Launch Gate