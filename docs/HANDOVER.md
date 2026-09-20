# Handover — state of the project, 2026-09-20

Written at the end of a long session so the next one starts informed rather
than guessing. `CLAUDE.md` holds the rules; this holds the state, the results
and the reasoning behind what to do next.

---

## 1. What this is for

The owner wants a system that reads the BTC and SOL chart, applies indicators,
reads fundamental news, and decides **long, short, or not now** — stated in
their own words, and identical to what Phase 1 §1 of the specification library
already required:

> The system is not designed to maximize trading frequency. Its primary
> objective is: maximize risk-adjusted returns while prioritizing capital
> preservation. The system must explicitly recognize NO TRADE as a valid and
> potentially optimal decision.

The specification library (`docs/`, Phases 1–10) governs. It was delivered
before any code existed and is stored verbatim. ADR-011 records the one thing
it left open — the decision horizon — and fixes it at hours-to-days on
measured evidence.

---

## 2. What exists and works

| layer | where | state |
|-------|-------|-------|
| tick recorder | `services/market_data/` | running continuously on the server |
| watchdog | `infrastructure/scripts/watch_recording.py` | every 5 min, restarts a dead recorder |
| gap registry | `services/market_data/registry.py` | silences written through to PostgreSQL before the process can die |
| candle history | `libs/domain/candles.py`, two venues | Hyperliquid 2y, Binance 9y, four assets |
| funding history | `libs/domain/funding.py` | ~7,500 settlements per asset from 2019 |
| sentiment | `libs/information/fear_greed.py` | Fear & Greed, daily, from 2018 |
| headlines | `libs/information/headlines.py` | four RSS feeds, collecting forward from 2026-09-20 |
| indicators | `services/strategy_engine/indicators.py` | RSI, MACD, Bollinger, SMA 20/50/200 |
| features | `services/strategy_engine/features.py` | trend, momentum, volatility, volume, levels, regime |
| decisions | `services/strategy_engine/decisions.py` | eight rules and five controls |
| candle backtest | `services/strategy_engine/candle_backtest.py` | decide at close, fill at next open |
| paper trading | `services/strategy_engine/paper.py` | every 4h on the server, forward record |
| risk + execution | `services/risk_engine/`, `services/execution_engine/` | built; signing proven against live testnet |

`make help` lists every command. The ones that matter most:

```
make signal ASSET=BTC        # what the bot thinks right now, with reasons
make paper-report            # what the paper trader has done
make evaluate-all RULE=... PERIODS=4 SHUFFLES=200   # test a rule
make evaluate-summary FILE=...  # compress a long evaluation to one line per run
make history-table           # what history is stored
```

---

## 3. What has been measured

Every figure here is from this project's own data, and each is recorded with
its method in `docs/evidence/build-0.1/acceptance-attempts.md`.

### Venue and cost facts

| | |
|---|---|
| Data arrival floor | **322 ms** median, 325 min — Hyperliquid's own publication delay, not our clock or network |
| Taker round trip | **9.98 bps** (4.5 fee each way + 0.49 half-spread) |
| Maker round trip | **3.41 bps** (1.5 fee each way + 0.20 adverse selection) |
| Funding, BTC/ETH | longs paid in **~85%** of settlements, median 0.81 bps — roughly **9% a year** to hold a long |
| Funding, BNB | **shorts** paid in 75% of settlements — the exception |

### The horizon ladder

Median unsigned BTC move, measured per horizon rather than extrapolated:

| horizon | move | clears 9.98 bps? |
|---------|------|------------------|
| 1 s | 0.00 | no |
| 30 s | 1.04 | no |
| 1 min | 1.85 | no |
| 5 min | 4.63 | resting only |
| 30 min | 10.36 | yes |
| 1 h | 13.82 | yes |

This closed the sub-minute branch permanently. At a 30-second hold the ceiling
on a perfect-direction strategy is a ninth of the cost of trading it.

### Rules tested — all NO_EDGE_FOUND

`trend-following`, `trend-following-calm`, `trend-confirmed`,
`trend-confirmed-3`, `mean-reversion`, `reversion-confirmed`,
`funding-extreme`, `funding-with-trend`. On 1h/4h/1d, BTC/ETH/SOL/BNB,
Hyperliquid 2y and Binance 6y and 9y, with and without funding charged, split
in two and in four.

Two added and **not yet tested**: `sentiment-extreme`,
`sentiment-with-funding`.

### The single most important result

`funding-extreme` on 4h, nine years, split four ways:

| period | BTC | ETH | BNB |
|--------|-----|-----|-----|
| ~2019–2021 | +7.9% | −3.9% | +13.9% |
| **~2021–2023** | **+2.1%** (beat hold by 4.2) | **+4.0%** (by 8.8) | **+0.8%** (by 2.2) |
| ~2023–2026 | −0.2% | −9.9% | −3.9% |

Gross profit per trade in time order: **BTC +43.35 → +18.34 → +8.58**, **BNB
+66.80 → +7.51 → −13.78**. Two of three decay monotonically.

A regime explanation predicts oscillation, because trends and ranges alternate.
Monotonic decay across three consecutive multi-year periods is what an edge
being competed away looks like. **The edge was real — it beat buy-and-hold on
three assets through 2021–2023 at better than 1-in-50 against its own
shuffles — and it is gone.**

This is why the direction changed. Every signal tested is computed from public
data by a published formula, so everyone who wants it has it. The one with the
best mechanism was arbitraged away in four years. Looking for a ninth such
rule is not the move.

---

## 4. Method that earned its place

Keep these. Each caught something.

**The shuffle control.** The candidate's own decisions replayed in random
order, 200 times. Same mix, same trade count, same fee bill, no information
about *when*.

**But it misleads in a trending market**, and that was my error. Over six years
where the market rose ~55%, shuffling separates a long-biased rule from the
drift, so the shuffles lose more — BTC read `0/200` next to a 10% loss. Fixed
by `LongWhenActive`: the candidate's own positions with direction removed, LONG
wherever it wanted anything. A candidate that cannot beat that has short calls
worth nothing.

**Period splits.** `--periods N`. Two parts answer "did it work throughout";
three or four answer "when did it stop", which is a different and more useful
question.

**The criterion written first.** Every evaluation had its pass bar recorded
before the numbers were seen. It failed two rules that looked good.

**Controls that must be there:** buy-and-hold, always-flat (proves the harness
invents nothing), shuffled, direction-free.

---

## 5. Where I was wrong, so it is not repeated

- **Extrapolated a horizon by √t** from one measurement. Two quantiles of the
  same distribution gave answers 50× apart. Withdrawn; the ladder replaced it.
- **Told the owner a faucet needed no mainnet balance.** They checked and it
  did. They were right.
- **Caused the 39-hour recorder outage** by telling them to put a testnet key
  in `.env`, which the recorder also reads.
- **Over-weighted `0/200`** and under-weighted `vsBH −65`. See above.
- **Broke the reporting path four times in an hour** — ignored directory,
  Makefile flags that never reached the command, two periods collapsed into one
  row, a header format the parser no longer matched. All from shipping without
  exercising. The summariser's test now builds its sample from the CLI's own
  formatters so a format change fails locally first.
- **Said "the token fixed it"** when it fixed one direction only. It made the
  server able to send; it did not make me able to run.
- **Called it a "robot"** when nothing was connected or automatic. The loop
  exists now; before it did not.

---

## 6. Parked, not forgotten

| item | state |
|------|-------|
| Hyperliquid testnet deposit | Pending for many hours; parked by agreement. `make testnet-order` waits on it. Signing is already proven. |
| Email alerts | Coded in `libs/observability/email.py`; needs a Gmail App Password in `.env`, then `make watch-test-email`. |
| M3 acceptance run | Owed. Must not run while the recorder is live — same stack, same stores, duplicate events. |
| Server on old branch | Fixed; it tracks `claude/limit-reached-76jutr` now. |

---

## 7. What to do next, in order

**1. Test the sentiment rules on eight years.** They are built and untested.
The Fear & Greed index has history, unlike the headlines, so this is testable
today. Criterion first, as always.

```
make sentiment
make evaluate-all RULE=sentiment-extreme VENUE=binance DAYS=2900 PERIODS=4 SHUFFLES=200
```

Be honest in the write-up: about half that index is volatility and momentum,
which this project has already mined. The social and search half is the part
worth testing. Do not present it as an independent signal.

**2. Let the headlines accumulate.** They started 2026-09-20 and cannot be
judged for weeks. Check `make news` occasionally for feed health — the median
claimed-to-received lag is the number that says whether an outlet's timestamps
can be trusted.

**3. Then the language-model reading of news.** This is the one input left
that is not a statistic everyone derives identically, and it is what the owner
asked for first. It needs an API key and a decision about cost. Design it so
the *judgement* is separable from the *collection*, which is already true of
the storage.

**4. Watch the paper loop.** In the early weeks the number that matters is not
the profit — it is whether the loop ran at all. It trades `funding-extreme`,
which failed its backtest, on purpose: if the backtests are sound it should
lose, and if it wins, the backtests have a defect. Both outcomes teach
something.

**5. Do not spend the holdout** until a rule passes the training period on
three of four assets across every sub-period. Nothing has.

---

## 8. If the loop stops

```
make paper-status      # when did it last run, and what did it say
make paper-tick        # one turn by hand, with full output
make record-status     # is the recorder alive
make watch-status      # what has the watchdog seen
```

The paper report names its own staleness. A tick that refuses on stale data is
the engine working correctly and the download failing — check
`make history-table` for coverage.
