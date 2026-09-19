# ADR-011 — The decision horizon is hours to days, not seconds

**Status:** Accepted · **Date:** 2026-09-19 · **Build:** 0.1

Number assigned from `docs/ADR/`, following ADR-010.

## Context

The product owner restated the objective of the platform in their own words:
the system should behave like a trader — read the chart, read the news, study
how the asset has behaved over the last one to two years, study market signals,
and decide to open long, open short, or stay out.

Nothing in that statement is new. Phase 1 §1 already says it, and says it
first:

> The system is not designed to maximize trading frequency. Its primary
> objective is: Maximize risk-adjusted returns while prioritizing capital
> preservation. The system must explicitly recognize NO TRADE as a valid and
> potentially optimal decision whenever sufficient statistical edge is absent.

Phase 1 §3 names the position-level decisions as LONG, SHORT, HOLD, REDUCE,
CLOSE. Phase 5 §20 organises the Feature Engine into Price, Trend, Momentum,
Volatility, Volume, Order Flow, Derivatives, Cross-Market and Regime families —
which is the chart-reading the objective describes, written as an engineering
requirement. MEIE (ADR-010) is the news layer. The specification library has
described this product from the start.

**What was missing was a number, and the implementation supplied one by
default.** Build 0.1 Rev.2 §3 scopes the first experiment to "one initial
trading horizon" and does not say which. M5 and M6 were built on the recorded
tick stream, on holding periods of seconds, because that is what the tick
stream is good for — not because any document asked for it. That was a drift,
and it is this ADR's job to name it rather than leave it as an unstated
assumption in the code.

The measurements taken along the way are what settle the question. Median
unsigned BTC mid movement, measured over 57,584 recorded quotes on 2026-09-19,
against a measured round-trip cost of 9.62 bps taker and 3.41 bps maker:

| Holding period | Typical move | Clears cost? |
|----------------|--------------|--------------|
| 1 second       | 0.00 bps     | no           |
| 10 seconds     | 0.31 bps     | no           |
| 30 seconds     | 1.04 bps     | no           |
| 1 minute       | 1.85 bps     | no           |
| 5 minutes      | 4.63 bps     | resting only |
| 30 minutes     | 10.36 bps    | both         |
| 1 hour         | 13.82 bps    | both         |

The first baseline strategy (M6) confirmed it from the other direction: over
1,689 trades at a 30-second hold, gross profit and loss was approximately flat
(−0.59 bps per trade) and fees were +9.62, for a net of −10.21. The loss was
not a failure of the signal. There was nothing at that horizon to be right
about.

The move is unsigned, so each figure is a **ceiling** — what a strategy calling
direction perfectly could have captured. Below the cost, a horizon is closed to
every possible signal.

## Decision

**1. The initial trading horizon is fixed at hours to days.** Specifically:
decisions are taken on closed candles of one hour or longer, and a position is
expected to be held between roughly one hour and one week. This is the value
Build 0.1 Rev.2 §3 left open, chosen now on measured evidence rather than
inherited from whichever data source happened to exist first.

**2. Sub-minute strategy research is closed, and its results are kept.** The M5
cost calibration and the horizon ladder are retained in
`docs/evidence/build-0.1/` and in `services/research/`. They are not deleted and
not treated as wasted: they are the evidence that closed a branch, which is a
result and not a detour. Rev.2 §25 asked for exactly this discipline — a
strategy profitable before costs and unprofitable after has demonstrated no
edge — and the answer it produced was "not at this horizon".

**3. Every governing invariant stays in force, unchanged.** The horizon is a
research parameter. It grants nothing and relaxes nothing:

- **Risk Engine > AI** (Phase 1 §6, §8; Phase 6 §2, §31). A longer holding
  period does not let a signal reach `place_order`. The Risk Engine still
  issues intents and the Execution Engine still re-validates them
  independently.
- **NO TRADE remains a valid decision** (Phase 1 §1). It is now also the
  owner's explicit requirement — "or that this is not a good time to trade" —
  and must be a first-class output, never a fallback.
- **Point-in-time correctness** (Phase 2, Phase 3, Phase 5 §23:
  `Feature Timestamp ≤ Decision Timestamp`). Longer horizons make lookahead
  *easier* to commit and harder to notice, because a daily feature computed
  from a daily close silently includes the whole day. This constraint becomes
  more load-bearing, not less.
- **Costs are always charged** (Rev.2 §25). Cost stops being the binding
  constraint at this horizon; it does not stop being charged. Funding in
  particular becomes material where it was negligible: Hyperliquid settles
  hourly, and a position held for a day crosses twenty-four boundaries.
- **Real capital prohibited, mainnet execution hard-blocked** (Rev.2 header).
- **No claim before a backtest.** A decision engine is not evidence of an edge.
  Phase 4's promotion gates, PBO and DSR apply, and `NO_EDGE_FOUND` remains a
  valid and publishable outcome.

**4. The phase requirements that now become load-bearing** — previously
deferred as not on the critical path:

- **Phase 3 — Historical Data Engine.** A trader reasoning over one to two
  years needs history that predates the recorder. Implemented as the `candles`
  table and `libs/exchange/hyperliquid/candles.py`, with archive holes declared
  rather than filled, on the same terms as the recorder's own gap registry.
- **Phase 5 §20 — Feature Groups.** Price, Trend, Momentum, Volatility, Volume
  and Regime are the chart-reading layer and are now the next thing to build.
  Order Flow stays available from the recorder but is no longer the primary
  family.
- **Phase 4 — Research & Backtesting Laboratory.** With hundreds of trades
  instead of thousands, overfitting becomes the dominant risk and the
  statistical gates are what stand against it.
- **ADR-010 / MEIE — news and market events.** Previously deferred partly
  because sub-second event edges do not exist to be captured. At this horizon
  the event classes MEIE describes decay over minutes and hours, which is
  reachable, and news analysis is an explicit owner requirement.

**5. Asset scope: history for both, first experiment on BTC, SOL as the
out-of-sample check.** Phase 1 §2 includes BTC, ETH, SOL and BNB. Build 0.1
Rev.2 §3–§4 defers SOL from the initial *experimental* pipeline, and that
deferral is kept: the safeguards, the cost measurements and the recorded stream
are all BTC. But Phase 3 is asset-agnostic, downloading history costs nothing,
and the owner's stated interest is SOL. So history is stored for both, the
first strategy experiment runs on BTC as the program requires, and the same
strategy is then re-run **unchanged** on SOL. A rule that works on one asset
and not the other has demonstrated a property of that asset's recent past, not
an edge — and that test is worth more than either run alone.

**6. The tick recorder keeps running, with a changed purpose.** It is Phase 3's
continuous recorder and the only point-in-time-safe record this project has of
execution-relevant microstructure. It no longer feeds signal generation. It
feeds cost measurement, execution-quality analysis and the slippage model that
Phase 8 §477 requires be recalibrated against observation — all of which remain
necessary at any horizon.

## Consequences

**Accepted:**

- Evidence arrives more slowly per unit of data. A year of hourly candles is
  8,760 decisions where a day of ticks was millions. Statistical power now
  comes from years of history and from cross-asset agreement, not from
  frequency, and the Phase 4 gates exist for exactly this.
- Overfitting replaces cost as the principal danger. This is the harder danger,
  because a cost error is arithmetic and visible while an overfit is a
  compelling story about the past.
- Funding, weekend behaviour, regime change and macro conditions enter the
  model. All were negligible at thirty seconds.

**Rejected:**

- *Keep pursuing the sub-minute horizon with a maker strategy.* Resting orders
  cost 3.41 bps against 9.98 for crossing, and at five minutes the typical move
  does clear it. But a resting order is a request, not a fill; the project has
  no fill model; the measured adverse selection is a lower bound with queue
  position unmodelled; and none of it serves the stated objective. A cheaper
  route to a horizon we have no reason to want is not progress.
- *Discard the tick recorder and the microstructure work.* The recorder is a
  Phase 3 requirement and the cost measurements are what make any backtest at
  any horizon honest. Deleting the evidence that closed a branch is how the
  same branch gets reopened.
- *Skip BTC and go straight to SOL.* It would contradict Rev.2 §3 without
  cause, discard the only asset this project has recorded and calibrated, and
  give up a free out-of-sample control.

## What would justify revisiting

- A measurement showing the typical move at some horizon between one and thirty
  minutes reliably exceeding a **modelled** maker cost including fill
  probability — not the fee-plus-adverse-selection lower bound used here.
- A change in venue fees large enough to move the cost floor by an order of
  magnitude.
- A demonstrated edge at this horizon, which would make the horizon *below* it
  worth asking about again with a working pipeline rather than with a guess.
- `NO_EDGE_FOUND` at this horizon across both assets and the full history, which
  would mean the question is not the horizon.
