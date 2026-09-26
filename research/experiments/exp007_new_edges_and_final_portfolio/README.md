# EXP-007 — New edges and the combined candidate portfolio

**Status:** candidate for paper trading. Not approved for capital.

Data as in EXP-004…006: Binance USDT-M perps 2020-01 → 2026-08, all 865
symbols including delisted ones; point-in-time top-N liquidity; real
funding.

## Ideas tested

| Idea | Result | Verdict |
|---|---|---|
| Short new listings (start day 1/3/7, hold 14–120 d, ± stop) | Negative CAGR in both periods for nearly all 24 variants; spikes of 3–10x | Rejected |
| Hour-of-day / day-of-week seasonality | Pattern correlation between periods −0.15; hourly trading destroyed by costs | Rejected |
| Pairs mean reversion (45 pairs, z-score) | −27% … −83%/yr in both periods | Rejected |
| **Crash reversal** (buy after a daily drop > X%, hold H days) | All 27 variants positive per trade in both periods (+1.3% … +8.3% net per trade) | **Accepted** |
| **Walk-forward LightGBM** (15 features ×2, retrained yearly, 30 liquid coins) | Daily rank IC 0.11, positive every year 2022–26; rank-weighted long/short 27%/yr | **Accepted** |

### Crash reversal (top 20 liquid, drop > 12%, hold 3 days, 10% of capital per event, gross ≤ 1x)

| Cost per side | 2020–23 CAGR | 2024–26 CAGR | Max DD |
|---|---|---|---|
| 0.07% | 38.9% | 44.8% | −46% / −36% |
| 0.20% | 34.8% | 39.6% | −47% / −37% |
| 0.40% | 28.9% | 32.0% | −50% / −39% |

Per-event results by year (avg / win rate): 2020 +7.5%/78%, 2021 +9.3%/70%,
2022 +0.2%/55%, 2023 −1.3%/41%, 2024 +3.4%/57%, 2025 +5.8%/57%,
2026 +2.7%/47%. Weak in bear markets. A BTC-above-200-day-MA filter
removed 2022 losses but halved the 2024–26 return, so it was not adopted.

### ML model (LightGBM, fully walk-forward: trained only on data before each test year)

Features: 1–60 day returns, 7/30-day volatility, volume change, 1/7-day
funding, distance from the 50-day MA, their cross-sectional ranks, and the
market return. The target is the next-day cross-sectional return rank.
Trading only the extreme picks (top/bottom 3–5) gives 70–91% drawdowns.
Rank-weighting across all 30 coins by inverse volatility gives a
market-neutral book: 27.1%/yr 2022–26, Sharpe 1.11, max DD −44%. By year:
+65%, +14%, +91%, +19%, 2026 YTD −28%.

## Candidate portfolio

Sleeve A = 50% crash reversal + 50% trend-indicator ensemble (EXP-006);
correlation between the two 0.20. Sleeve B = ML long/short; correlation
with sleeve A −0.00. The two sleeves are equal-weighted.

| Leverage | 2022–26 CAGR | 2024–26 CAGR | Sharpe | Max DD |
|---|---|---|---|---|
| 1x | 21.5% | 26.9% | 1.13 | −25% |
| 1.5x | 32.2% | 40.7% | 1.13 | −37% |
| **2x** | **42.7%** | **54.4%** | 1.13 | **−47%** |
| 2.5x | 52.6% | 67.8% | 1.13 | −55% |

At 2x by year: 2022 +22%, 2023 +35%, 2024 +167%, 2025 +60%, 2026 YTD −25%.
Monthly at 2x: median +2.4%, mean +3.6%, 59% of months positive, best
+63%, worst −17%.

## Caveats

- Across EXP-001…007 the 2024–26 period has been looked at many times, so
  it is no longer truly unseen. The ML sleeve is walk-forward by
  construction; the other sleeves' parameters were fixed in advance or are
  robust across every variant tested, but only live paper trading is a
  genuinely new test.
- Daily-close execution is assumed. Crash-day slippage is tested up to
  0.4% per side, and the edge survives.
- 2026 YTD is negative for the portfolio.
