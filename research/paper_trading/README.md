# Paper trading — EXP-007 candidate portfolio

Validation-ladder stage: **paper trading** (research/README.md). This package
reads public Hyperliquid market data and writes a ledger. It holds no key
and cannot place an order.

## Portfolio (weights fixed in research, not tuned on live data)

| Sleeve | Share of risk | Rule |
|---|---|---|
| Crash reversal | 25% | Among the 20 most liquid coins, buy one that fell more than 12% on the day with 10% of equity; hold 3 days |
| Trend indicators | 25% | Mean of 6 long-only rules (Ichimoku, Bollinger breakout, EMA 50/200, MACD, Supertrend, Donchian) on 4h and 1d, for 10 majors, vol-scaled |
| ML long/short | 50% | LightGBM trained on Binance 2020-01 → 2026-08 (`model/ml_lgbm.txt`); rank-weighted, market-neutral across the 30 most liquid coins |

Overall leverage 1.5x, with at most 50% of equity per coin and 3x gross.
Costs are 0.10% per side, and funding is charged at Hyperliquid's real rates.
Positions are set at the 00:00 UTC daily close and held until the next one.

## Running

```
pip install -r research/paper_trading/requirements.txt
python -m research.paper_trading.trader                          # advance the live ledger
python -m research.paper_trading.trader --backfill-from 2025-01-01  # simulate into ledger_backfill/
python -m research.paper_trading.train_model <dir with C.pkl V.pkl F.pkl>  # retrain (yearly)
```

A run processes every completed UTC day since the last one in
`ledger/state.json`, so a missed day is caught up on the next run.
`ledger/equity.csv` holds the daily equity and its return split into
price, funding and cost; `ledger/trades.csv` holds every weight change.

## Pre-launch replay on Hyperliquid (2025-01-01 → 2026-09-25)

The ML model was trained on data covering this period, so this replay
checks the plumbing, not the edge.

- Portfolio: +6.4% over 21 months, max drawdown −32.7%.
- By sleeve (2025 / 2026 YTD): crash reversal +36% / +21%, trend −7% / +7%,
  ML +11% / −25%.

The weakness of the ML sleeve in 2026 matches its Binance backtest
(−28% YTD).

## Go / no-go for real capital

After at least 60 trading days, compare paper results with the backtest:

- **Continue to small real capital** (1x leverage, capital you can lose) only
  if paper Sharpe > 0.5 and drawdown < 25%.
- **Stop and revisit** if drawdown exceeds 30%, or if any sleeve's
  realised results fall outside its backtest range for two consecutive
  months.

## Dashboard

A Persian dashboard page opens in the Claude app:

https://claude.ai/artifact/Jd7iywb77RL4AeMBsDuDdh

`dashboard/index.html` is the page and `dashboard/data.json` its data,
written by `python -m research.paper_trading.export_dashboard`. The daily
run republishes both to the same URL.
