# EXP-010 — Gold (PAXG) with indicator rules and leverage

**Status:** no stable edge. Results follow gold's direction.

Data: Binance PAXGUSDT (a token backed 1:1 by gold), 1h and 1d bars,
2020 → 2026-08. The rules are EXP-005's, with 0.05% per side
(CFD-like spread and commission).

Gold buy and hold: 2020–23 **+0.7%/yr**, 2024–26 **+29.9%/yr**.

| Rule (1d) | 2020–23 at 1x | 2024–26 at 1x | 2020–23 at 5x | 2024–26 at 5x |
|---|---|---|---|---|
| EMA 50/200 golden cross | −4.8% | +28.6% | −28.9% (DD −78%) | +119.9% (DD −88%) |
| Ichimoku long | +0.1% | +19.7% | −8.0% | +88.2% (DD −61%) |
| Donchian 20 L/S | −13.0% | +25.4% | −60.2% (DD −95%) | +80.9% (DD −77%) |
| Bollinger breakout | −1.2% | +13.9% | −14.5% | +47.1% (DD −71%) |
| Stochastic 20/80 | +6.1% | +7.4% | +23.1% (DD −53%) | +16.4% (DD −75%) |
| RSI 30/70 | +3.9% | +1.0% | +7.8% (DD −57%) | −6.3% (DD −67%) |
| MACD long/short | +2.3% | −3.4% | −10.6% | −50.9% (DD −94%) |
| Supertrend long/short | 0.0% | −32.4% | 0.0% | wiped out |

1h and 4h rules lose in both periods after costs.

## Conclusion

Every long-biased rule made money in 2024–26 because gold itself rose
about 30% a year; the same rules lost in 2020–23 when gold was flat. At 5x
leverage a gold bot started in 2024 looks like it makes 80–120% a year,
and the same bot started in 2021 would have lost most of its account. A
few months of good results from a leveraged gold bot during a gold rally
says little about skill.
