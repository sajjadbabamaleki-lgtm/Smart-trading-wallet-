# Research Candidates

Component-level research and architecture specifications. These are **not**
approved production signals and **not** part of the Build 0.1 critical path.
Each carries its own promotion gates and its own valid negative outcomes.

Documents are stored verbatim as delivered; status is carried by filename and
this index.

| Component | Version | Status | Production authority | Build 0.1 critical path |
|-----------|---------|--------|----------------------|-------------------------|
| [Trader Behavior Intelligence Engine (TBIE)](trader-behavior-intelligence-engine.md) | 1.1 — evidence-audited | High-Priority Experimental Candidate | None | No — but it constrains recorder and clock design |
| [TBIE v1.0](trader-behavior-intelligence-engine-v1.0-superseded.md) | 1.0 | Superseded by 1.1, retained for traceability | None | — |
| [Market Event Intelligence Engine (MEIE)](market-event-intelligence-engine.md) | 1 | Experimental Candidate | None | No — deferred behind M7 and M9 |

## TBIE in one paragraph

Hyperliquid exposes persistent pseudonymous wallet identities, so it is possible
to ask whether *who* trades carries information beyond price, order book,
derivatives and anonymous order flow. TBIE would estimate the point-in-time,
context-dependent, time-varying informational quality of wallets and cohorts and
emit that as research features. It is explicitly **not** copy trading: observed
behaviour is evidence, never an instruction, and TBIE holds no execution,
leverage, sizing, stop, risk-limit or kill-switch authority (v1.0 §3, §62).

## The distinction v1.1 exists to enforce

> Existing research demonstrates **predictive information**, not **executable
> trading alpha**. (§1, §19)

Three propositions, kept separate (§72):

| | Proposition | Status |
|---|-------------|--------|
| 1 | Trader identity contains predictive information | **Supported** |
| 2 | It contains information beyond anonymous market data | **Supported** |
| 3 | Our system can convert that into durable net profit | **Unproven** |

The entire TBIE engineering programme exists to test proposition 3.

## Evidence audit

v1.1 audits every external claim against primary sources and classifies each as
VERIFIED / VERIFIED WITH QUALIFICATION / PARTIALLY VERIFIED / UNVERIFIED. No
architectural commitment requiring significant spend may rest on an unverified
claim (§2, §65). Full matrix in §36.

**Verified** — the principal study (Zhai, *Public Trader Identity: Adverse
Selection and Return Predictability*, 2026, SSRN/arXiv working paper):

- Scale: 17.1B Level-4 messages, 14.3M aggressive orders, 147,113 wallets,
  $84.3B taker notional (§4). BTC is the largest market in the sample —
  ≈9.75B messages, 98,900 wallets, $46.8B notional, 0.20 bps spread — which
  matters directly for a BTC-only MVP (§5).
- Skill is measured by signed 10-second midpoint markout, not PnL — validating
  v1.0's architectural choice (§6).
- Genuine temporal separation: score on Jul 1–10, test persistence Jul 11–20,
  evaluate prediction Jul 21–27, rankings frozen in between (§8).
- Persistence across adjacent ten-day windows, Spearman ρ = 0.52 (§9).
- Concentration in the upper tail; top-ventile adjusted markout ≈ 3.11 bps (§10).
- Minimum 100 qualifying aggressive orders → 2,314 scored wallets, 231 in the top
  decile; TWAP and liquidations excluded (§7). 91.3% of those wallets traded
  again in the validation window, so persistence is not a survivorship artefact
  (§12).
- The benchmark is **not** price-only: it already carries depth imbalance,
  quote-update OFI, signed taker flow, returns, realized volatility and spread
  (§13).
- Headline: at 1s, ridge R² 10.88% → 12.31%, a **relative** +13.2%, t = 9.2 —
  which is not 13.2% return, alpha, or profitability (§14).
- 200 activity-matched placebo cohorts; identity gain exceeds them at the
  relevant horizons (§15).
- Gradient-boosted trees: 19.48% → 20.65%, +6.0% — nonlinear anonymous features
  absorb part of the identity information, so TBIE must always compete against
  strong nonlinear baselines (§16).
- Temporal replication on a separate December 2025 dataset (26.25B messages) —
  though still the same study and methodology, not independent reproduction
  (§21).
- Level-4 reconstruction feasibility and counterparty/position fields confirmed
  by the Albers et al. paper **and** by Hyperliquid's own node documentation
  (§28, §29).

**Not verified:** executable profitability, receipt-to-fill alpha, profitable
copy trading (§36).

**Rejected:** "Hyperliquid smart money leads Binance" — Binance leads at
aggregate venue level, and even the pooled informed cohort tends to *follow* it;
only wallet-level heterogeneity shows a minority anticipating (§24, §27). Also
rejected: that full-node data is cheap, and that the API alone can reconstruct
long trader history (§36).

## Latency is now Gate 0

The horizon structure (§17) corrects the earlier reading in both directions —
the signal is fast-decaying but demonstrably not confined to one second:

| Horizon | Anonymous R² | + Identity | Relative gain |
|---------|--------------|------------|---------------|
| 0.2s | 6.91% | 8.20% | +18.7% |
| 0.5s | 10.16% | 11.76% | +15.8% |
| 1s | 10.88% | 12.31% | +13.2% |
| 2s | 10.60% | 11.66% | +10.0% |
| 5s | 9.17% | 9.79% | +6.7% |
| 10s | 7.18% | 7.56% | +5.2% |
| 30s | 3.56% | 3.67% | +3.0% |

For trees the increment runs +10.7% at 200 ms down to +2.7% at 30s, remaining
statistically distinguishable from zero through roughly ten seconds (§17).

So the binding constraint is not the horizon — it is that the study indexes time
by **consensus timestamps**, never by an audited **local receipt clock**. Nothing
in it establishes that observe → decode → update state → compute features →
infer → risk-check → submit → fill completes before the remaining information is
gone. The paper itself says an execution model is out of scope (§18, §19).

Hence latency viability is promoted from a late robustness test to **Gate 0**,
ahead of full TBIE development, node infrastructure, embeddings and cohort
modelling (§37). It runs as two experiments — synthetic delay replay across a
0 ms → 30 s ladder to estimate the decay curve, and live measured per-stage
latency at p50/p90/p95/p99/p99.9, because trading systems fail in tails
(§39–41, §62–63) — then shadow executability (§64). Receipt-time and monotonic
clock instrumentation become mandatory to answer it at all (§42, §43).

## Four outcomes, not pass/fail

| Outcome | Meaning |
|---------|---------|
| `TBIE_ALPHA_VALIDATED` | executable incremental alpha |
| `TBIE_RISK_ONLY` | improves adverse-selection / execution-risk estimation, no directional alpha |
| `TBIE_RESEARCH_ONLY` | real statistical structure, insufficient economic value |
| `TBIE_NO_EDGE` | nothing durable survives rigorous testing |

A feature can fail as alpha while succeeding as risk intelligence (§45, §46) —
which is why the broader objective is no longer "can we follow successful
traders" but whether behavioural identity improves estimates of return, adverse
selection, execution quality or regime (§47). Accordingly a single global
`TraderScore` is to be avoided in favour of a `TraderInformationVector` across
direction, adverse selection, liquidity, execution and regime (§48, §49).

**Kill rule (§78):** if PIT-correct experiments repeatedly show the information
disappears before realistic execution, cannot survive costs, depends on a few
wallets, or fails outside the original period, alpha development stops. No
founder override, and no model-complexity rescue without a new falsifiable
hypothesis.

## Infrastructure gates

- **Node is an economic decision, not a default.** Hyperliquid's own docs put
  default node operation at ≈100 GB of logs per day — ≈3 TB/month, ≈36.5 TB/year
  uncompressed, before retention, replication, backups, indexes or derived
  datasets (§34). Approved only if Gate 0 suggests actionable value, or Level-4
  data proves independent execution/risk value, or the cost is low enough to
  justify preserving an otherwise irrecoverable asset — otherwise **defer**
  (§58, §59). Privileged Foundation connectivity must not be assumed available
  (§35).
- **Own recorder stays mandatory.** API history is bounded (2,000 fills per
  response, only the 10,000 most recent; 2,000 most recent historical orders),
  and the official archive uploads roughly monthly with no guarantee of
  timeliness or completeness (§32, §33).
- **Rejected-order and TWAP research is interesting, not yet justified.**
  Rejected post-only orders were ≈67% of message traffic in one BTC study; that
  does not license Build 0.1 to ingest every rejected order (§30, §31).

## What this changes in the build

Nothing on the critical path: M0 → M1 → M2 → M3 → BTC dataset → baseline
strategy → risk/execution stands as-is, and TBIE Experiment 0 begins only once
recorder, integrity and replay all pass (§57, §77, §81).

- **M0 (§74):** register TBIE's research status, resolve the ADR namespace,
  make event schemas capable of carrying optional identity-linked fields, make
  the clock architecture capable of future latency measurement, and take no
  production dependency on TBIE.
- **M2 (§75, §56):** still just the BTC recorder — but do not discard
  `wallet`, `counterparty`, `side`, `price`, `size`, `order_id`,
  `start_position`, `twap_id`, `cloid`, event time, receive time or the raw event
  reference when they are available at reasonable cost. Preserve optionality;
  avoid irreversible information loss. M2 must **not** become a trader-ranking
  engine, wallet profiler, copy-trading system, cross-venue predictor or
  Level-4 research cluster (§76).
- **ADR (§73):** the number is repository-assigned — inspect `docs/ADR/` during
  M0 and take the next canonical number. v1.0's hardcoded "ADR-004" is
  withdrawn. Title: *Trader Behavior Intelligence as an Experimental Feature
  Family*.

## Experiment order (§61)

```
0  Latency viability      — does identity survive realistic delay?
1  PIT wallet persistence — reproducible without future leakage?
2  Incremental information — beats strong anonymous baselines?
3  Economic value         — survives costs?
4  Cohort construction    — does skill weighting beat raw flow?
5  Weak-trader divergence — does informed-minus-weak add value?
6  Cross-venue            — do selected wallets lead other venues?
```

Mandatory throughout: concentration tests removing the top 1/5/10 wallets and
top 1%/5% (§52), wallet-turnover measurement (§53), placebos including a
future-leaked control that quantifies how much false performance PIT violation
would manufacture (§67), cost stress at 2× fees / 2× slippage / 2× latency
(§68), regime decomposition (§69), and full experiment provenance (§70).

## Governing principle (§82)

> Capture what may become irrecoverable. Verify what can be verified. Measure
> latency before assuming executability. Buy infrastructure only after evidence
> earns it. Treat predictive information and profitable execution as two
> different hypotheses.

---

## MEIE in one paragraph

MEIE asks whether a market-moving event still contains *executable* information
by the time this system could act on it. Not "is this news bullish" but: given
the event, the market state, how much of the reaction has already happened, the
age of the information, and what execution costs — does defensible edge remain?
`NO TRADE` and `NEWS_NO_EDGE` are first-class results. It proposes; the Risk
Kernel disposes (§2.2), which matches the boundary this repository already
enforces between the Risk Engine and execution.

## What this project's own measurements say about it

Recorded in the document itself, under *What this project has already
measured*, and summarised here because it applies to TBIE identically.

**Four rungs of MEIE's latency ladder do not exist for us.** §24 replays every
candidate at 0, 50, 100 and 250 ms. The venue's publication delay to a public
subscriber is p50 425 ms, min 325 ms — measured, and shown to be neither our
clock (root dispersion 274 µs) nor our network (≈28 ms one way). Two independent
specifications arrived at sub-second ladders without either having measured the
floor.

**Cost is the binding constraint, not latency.** A round trip costs 9.99 bps,
of which 9 is fees. BTC's mid moves a median 0.066 bps over those 322 ms. So
there is no fast edge of the required size to be taxed by the delay — which
makes §16 (Already-Priced-In) and §17 (Information Decay) the load-bearing
components, and makes `NEWS_RISK_ONLY` (§36) the most probable useful outcome
rather than the consolation prize.

Neither finding invalidates MEIE. Both relocate it: CPI prints, FOMC decisions,
exchange incidents and regulatory rulings decay over minutes and hours, where
the horizons are reachable and ten basis points is an ordinary move.

## Why it is deferred rather than started

Its cheapest and probably most valuable part is §30, Risk-Only Mode: block new
entries and reduce exposure around scheduled releases. That needs no NLP, no
LLM and no taxonomy — only a macro calendar. It is deferred anyway, because the
system has no strategy to block yet, and a risk control with nothing to restrain
cannot be shown to help. See [ADR-010](../ADR/ADR-010-market-event-intelligence-experimental.md).

## What MEIE forbids, which this repository should hold to regardless

§38 lists what must not be built. Three of them are live risks for any system
that later adds an LLM anywhere near a trading decision:

- `headline → GPT → BUY/SELL`, and `positive sentiment = LONG`
- counting reposts as independent confirmation — five sites repeating one rumour
  are not five sources (§13)
- letting an LLM control risk, or return an executable command as an
  authoritative action (§14)
