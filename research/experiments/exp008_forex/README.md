# EXP-008 — Forex with leverage

**Status:** rejected. No forex strategy tested is worth trading.

## Data

- Daily Federal Reserve H.10 noon rates for EUR, GBP, AUD, JPY, CAD, MXN
  and ZAR against USD, 2000 → 2026-09 (GitHub mirror `datasets/exchange-rates`).
- BIS monthly central-bank policy rates for swap/carry, through 2025-01 and
  carried forward after that.
- Costs: spread of 0.02–0.03% per side on G10 and 0.10–0.15% on MXN and
  ZAR, plus the rate differential and a 1%/yr broker markup on gross
  exposure (retail swap markup).
- Close-only data, so the rules use closes.
- Selection period 2000–2014, holdout 2015–2026.

## Results (10% annual volatility target, about 1.5–2x leverage)

| Strategy | 2000–14 CAGR | 2015–26 CAGR | Sharpe (2015–26) |
|---|---|---|---|
| Trend 20/60/120 | −1.2% | −7.7% | −0.59 |
| Trend 120/250 | −0.4% | −3.7% | −0.21 |
| MA 50/200 cross | −2.3% | −5.0% | −0.27 |
| RSI 30/70 mean reversion | −12.5% | −6.2% | −0.37 |
| Carry (long top 2, short bottom 2) | +0.7% | +1.1% | 0.18 |
| Carry + trend filter | +0.2% | −1.0% | −0.16 |

With no broker markup, carry reaches +2.3% / +2.6% (Sharpe about 0.3) and
trend is roughly flat before 2015 and negative after.

Leverage makes it worse. Carry at 6x: CAGR about 0%, drawdown −78%.
Long-term trend at 9x: −23%/yr, drawdown −99%.

## Conclusion

Forex majors against USD have moved little and trended weakly since the
2000s, consistent with the documented decay of FX trend-following. With
retail swap markups there is no edge worth leverage here. Crypto (EXP-007)
is the better candidate.
