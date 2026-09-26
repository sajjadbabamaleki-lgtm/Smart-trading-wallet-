# EXP-002 — Search for a strategy above 100% a year

**Status:** rejected. No candidate reached 100%/yr out of sample.
Recorded because failed experiments stay recorded (Phase 4 §5).

Same data, costs (0.15%/turnover) and funding assumptions as EXP-001.
Out of sample = 2022-01-01 onward.

## 1. More leverage on EXP-001

| Gross cap | Full-period CAGR | Max DD | OOS CAGR | OOS Max DD |
|---|---|---|---|---|
| 4x | 67.5% | −77.9% | 25.3% | −62.0% |
| 5x | 72.9% | −87.3% | 22.0% | −72.6% |
| 6x | 69.6% | −94.3% | 11.9% | −82.7% |
| 8x | 55.9% | −97.8% | −2.5% | −89.7% |
| 10x | 2.9% | −99.8% | −39.8% | −97.0% |

Growth peaks near 5x and then falls: volatility drag grows with the square
of leverage. Liquidations are not modelled, so live results would be worse.
With Sharpe S, the best achievable log growth is S²/2. That makes 100%/yr
(log growth 0.69) need a sustained Sharpe of about 1.2 at full Kelly, with
Kelly-sized drawdowns of 50–90%. EXP-001's out-of-sample Sharpe is 0.68.

## 2. Cross-sectional momentum rotation (long top-k coins by L-day return)

48 variants: k ∈ {2,3,5}, L ∈ {7,14,28,56}, with or without a BTC > 100-day
MA filter, on 12 majors (2018+) and on 54 coins (2021+).

- Many variants show 100–216% CAGR over the full period. All of that comes
  from 2019–2021: in-sample Sharpe runs up to 4.0.
- The best out-of-sample result was 31% CAGR (top-2, 14-day, BTC filter,
  majors), with a −62% drawdown. Without the BTC filter, most variants lose
  money out of sample.

## 3. 4-hour trend (BTC, ETH; the only multi-year intraday data reachable was 2024-01 → 2026-03)

40 variants (EMA / Donchian, n ∈ {10…200}, long-only or long/short).

- Best: ETH EMA-200 long/short at 88.6% CAGR, −37% DD. The same rule on BTC
  returned −10%/yr.
- As the best of 40 variants on 2.25 years of data, that result is
  indistinguishable from data mining. Rejected.

## Conclusion

On this data, every strategy showing ≥100%/yr owes it to the 2019–2021 bull
market or to picking the best of many variants. EXP-001, at about 16% OOS
with 2x, remains the most credible candidate. Higher returns come only with
higher risk of ruin.
