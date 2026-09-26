# EXP-003 — Large strategy search with an untouched holdout

**Status:** rejected. The search reached ~100%/yr on the data used to choose
the strategies and lost money on the holdout.

## Protocol

- 40 directional strategies on 12 majors: time-series momentum at 9
  lookbacks (long-only and long/short), MA crosses, Donchian breakouts,
  cross-sectional momentum and reversal, top-k rotation with a BTC filter,
  low-volatility, and a funding-contrarian BTC rule. BTC cash-and-carry was
  also built, then excluded from the portfolios.
- Costs 0.15%/turnover; longs pay 2x BTC funding.
- Selection period 2018–2024: rank by Sharpe, build an inverse-vol
  portfolio of the top N, and lever it to 60% annual volatility. Weights
  and leverage are fixed on this period only.
- Holdout 2025-01 → 2026-05: evaluated once, after selection.

## Results

| Portfolio | Selection period CAGR | Sharpe | Holdout CAGR | Holdout Sharpe | Holdout Max DD |
|---|---|---|---|---|---|
| Top 3 | 106.6% | 1.50 | −12.3% | −0.23 | −31.1% |
| Top 5 | 104.7% | 1.48 | −10.3% | −0.14 | −32.0% |
| Top 10 | 102.1% | 1.47 | −13.8% | −0.13 | −42.5% |
| Top 20 | 97.4% | 1.43 | −18.4% | −0.18 | −47.7% |

Individually, 32 of the 40 strategies had a holdout Sharpe below 0.3. The
only standouts were BTC cash-and-carry (smooth but ~2–5%/yr) and the
funding-contrarian rule (Sharpe 1.5, but in-sample only 0.97, and it trades
BTC only).

## Conclusion

A search tuned on past data can show ~100%/yr and then lose money on data
it has not seen. That is the direct evidence against simply "testing more
strategies until one reaches 100%". EXP-001 is still the most robust
candidate. The 2025–26 holdout was a weak, trendless market, and EXP-001's
simple trend rules also struggled in it.
