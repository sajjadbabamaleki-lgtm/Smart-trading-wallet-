# EXP-009 — Intraday (day-trading) strategies

**Status:** rejected. No intraday rule is profitable in 2024–26 at taker
cost, and only one barely breaks even at maker cost.

Data: Binance USDT-M perps, 1-hour bars for 10 majors, 2020-01 → 2026-08.
Each coin is sized at 10% of equity. Two cost levels per side: 0.07%
(taker + slippage) and 0.03% (maker).

| Strategy | Cost | 2020–23 CAGR | 2024–26 CAGR | 2024–26 Max DD |
|---|---|---|---|---|
| Intraday momentum, entry at 06:00 | taker / maker | −55% / −40% | −53% / −37% | −87% / −72% |
| Intraday momentum, entry at 12:00 | taker / maker | −34% / −12% | −35% / −13% | −75% / −58% |
| Intraday momentum, entry at 18:00 | taker / maker | +1% / +32% | −42% / −22% | −78% / −59% |
| Opening-range breakout 00–04 UTC | taker / maker | −25% / +5% | −55% / −34% | −89% / −71% |
| Opening-range breakout, long only | taker / maker | +26% / +48% | −31% / −17% | −69% / −52% |
| Reversal after a 3σ hour (hold 3h) | taker / maker | −7% / +3% | −19% / −10% | −53% / −41% |
| Reversal after a 4σ hour (hold 3h) | taker / maker | +9% / +14% | −12% / −8% | −39% / −33% |
| Volatility breakout k=0.5, long | taker / maker | +28% / +39% | −6% / +4% | −34% / −28% |
| Long only 13–21 UTC (US session) | taker / maker | −28% / −4% | −33% / −10% | −75% / −58% |
| Short the hour before funding | taker / maker | −82% / −57% | −80% / −52% | −99% / −87% |

## Why

A strategy that opens and closes every day pays 0.14% (taker) or 0.06%
(maker) per round trip, which comes to 20–50% a year before any edge. The
hourly patterns are smaller than that, and several that worked in
2020–23 (long breakouts, volatility breakout, late-day momentum) were
largely bull-market effects that did not survive into 2024–26.

Together with EXP-005 (13 indicator rules on 1h, 11 of 13 negative in
2024–26), there is no evidence of a profitable day-trading rule in this data.
