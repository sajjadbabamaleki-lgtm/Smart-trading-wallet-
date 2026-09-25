# EXP-001 — Volatility-targeted trend following on crypto perpetuals

**Status:** historical backtest passed, out-of-sample passed (modestly).
Not yet walk-forward on a registered dataset, paper traded, or live. Per the
validation ladder this is step 2 of 8, **not** approval to trade capital.

## Hypothesis

Time-series momentum (Moskowitz, Ooi & Pedersen 2012; Liu & Tsyvinski 2021)
earns a positive return on liquid crypto after realistic perpetual-futures
costs, and does so out of sample.

## Strategy (parameters fixed from the literature, not optimised)

| Item | Rule |
|---|---|
| Universe | BTC ETH BNB SOL XRP ADA DOGE TRX LINK LTC DOT AVAX (USDT perps) |
| Signal | mean of sign(return over 20, 60, 120 days) per coin, clipped to [0, 1] — **long or flat, never short** |
| Sizing | equal risk per coin: `signal × target_vol / 30d realised vol`, 60% target, gross exposure capped at **2x** |
| Timing | computed at the daily close, executed at the next bar — no look-ahead |
| Costs | 0.15% per unit of turnover (taker fee + slippage) |
| Funding | net long exposure pays **2× BTC's** historical Binance funding (pessimistic proxy for altcoins) |

## Results (daily, Binance data, 2018-01-01 → 2026-05)

| Period | Strategy CAGR | Sharpe | Max DD | BTC buy & hold CAGR | Sharpe | Max DD |
|---|---|---|---|---|---|---|
| Full 2018+ | **30.3%** | **1.06** | −38.7% | 23.7% | 0.66 | −81.2% |
| In-sample 2018–21 | 48.1% | 1.42 | −26.8% | 35.5% | 0.79 | −81.2% |
| **Out-of-sample 2022+** | **15.8%** | **0.68** | **−28.3%** | 13.8% | 0.51 | −66.9% |

Mean gross exposure 0.32x, peak 1.57x, worst day −11.9%.
Calendar years: 2018 −12%, 2019 +56%, 2020 +91%, 2021 +84%, 2022 −15%,
2023 +34%, 2024 +73%, 2025 −5%, 2026 YTD +1%.

### Robustness

All 7 lookback sets tested are positive over the full period, and **all 7
long-only variants are positive out of sample** (OOS Sharpe 0.20–0.68). The
long/short versions are consistently worse: the short side loses money in
crypto after funding and costs, so it is dropped. Doubling costs and tripling
funding still leaves OOS Sharpe 0.37.

Leverage scales return and drawdown together; Sharpe is unchanged (0.68 OOS):

| Cap | OOS CAGR | OOS Max DD |
|---|---|---|
| 1x | 11.1% | −19.6% |
| 2x (recommended) | 15.8% | −28.3% |
| 3x | 24.5% | −50.1% |

## Rejected / secondary findings

- **Long/short trend**: OOS Sharpe −0.09 to 0.52. Rejected.
- **BTC cash-and-carry (long spot, short perp, collect funding)**: positive
  every year 2020–2026, max DD < 2%, but only ~6%/yr on capital and decaying
  (2025: 2.6%, 2026 YTD: 0.3%). Useful for idle capital, not a primary engine.
- **54-coin wider universe** (2021+): long-only trend Sharpe 0.72–0.84 but
  that universe is chosen with hindsight (survivorship bias), so it is
  treated as supportive, not as evidence.

## Known weaknesses — read before trading

1. OOS Sharpe 0.68 over ~4.3 years has a t-stat of ~1.4: encouraging, not
   statistically conclusive. Losing years (2018, 2022, 2025) happen.
2. The universe is today's survivors (no LUNA, FTT); real results would be
   somewhat worse.
3. Spot prices stand in for perp prices; funding for altcoins is a proxy.
4. The long-only choice was made after seeing the grid — a mild selection
   effect, mitigated by it holding for every lookback.
5. Leverage above ~2x makes drawdowns of 50%+ likely.

## Next steps on the validation ladder

Walk-forward on a registered dataset (M4) → stress tests → testnet → paper
trading → shadow → limited-capital live, with the Risk Engine's hard limits.

## Reproduce

```
pip install pandas numpy
python research/experiments/exp001_trend_following/run.py
```

Data sources (pinned commits) are listed in `run.py`.
