# EXP-006 — Combined system: indicators + trend + funding harvest

**Status:** rejected as specified. This experiment also corrects EXP-004's
funding-harvest result.

## Correction to EXP-004

EXP-004 booked funding only. This run adds the daily return difference
between the long spot leg and the short perp leg (real Binance spot
klines). A coin is tradable only when its perp and spot closes agreed
within 3% the day before; without that filter, mismatched pairs (RAY,
GLMR, MDT) dominate the result.

| Hedged funding harvest | 2020–23 CAGR | 2024–26 CAGR | 2024–26 Max DD |
|---|---|---|---|
| Funding only (EXP-004) | 13–15% | 5–16% | < 4% |
| **Funding + basis (realistic)** | 13–14% | **−5% … +1%** | −15% … −28% |

High-funding coins are the ones where the perp can gain on spot by 5–10%
in a day. In 2024–26 those days cancelled the funding income.
Liquidation risk on the short leg (days a held coin's high exceeded the
margin): 25 days at 2x perp leverage, 72 at 3x, 221 at 5x.

## Combined portfolios (risk-parity weights fixed on 2020–23)

| Portfolio | Leverage | 2020–23 CAGR | 2024–26 CAGR | 2024–26 Max DD |
|---|---|---|---|---|
| Indicators + trend + harvest | 1x | 15.7% | −1.6% | −24.8% |
| Indicators + trend + harvest | 3x | 54.3% | −8.4% | −60.4% |
| Indicator ensemble only (6 long-only trend rules, 4h + 1d, 10 majors) | 1x | 33.0% | **11.6%** | −32.1% |
| Indicator ensemble only | 2x | 68.5% | 18.0% | −55.4% |
| Indicator ensemble only | 3x | 103.5% | 18.4% | −72.2% |
| Indicator ensemble + EXP-001 trend, 50/50 | 2x | 51.0% | 13.7% | −42.0% |

Indicator ensemble at 2x by year: 2020 +88%, 2021 +269%, 2022 −42%,
2023 +99%, 2024 +106%, 2025 −20%, 2026 YTD −6%.

Choosing only the three indicators that won in 2024–26 changed nothing
(within 0.3 pp), so the ensemble result is not a product of cherry-picking.

## Conclusion

- Trend indicators on 4h and daily charts are the one edge that held up
  on unseen data: about 10–18%/yr on the holdout, with 30–55% drawdowns.
- Individual years above 100% occur (2021, 2023, 2024 at 2x), but so do
  −20% to −42% years. The multi-year average on unseen data is not near
  100%.
- Funding harvest, once basis risk is included, adds nothing after 2023.
