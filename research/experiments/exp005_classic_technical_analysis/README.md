# EXP-005 — Classic technical analysis, textbook settings

**Question:** do the standard chart indicators and candlestick patterns
predict crypto moves well enough to trade profitably, and how often are
they right?

## Protocol

- Binance USDT-M perps, 10 majors (BTC ETH BNB SOL XRP ADA DOGE LINK LTC
  AVAX), 1-hour data 2020-01 → 2026-08, resampled to 4h and 1d.
- 13 rules with textbook parameters, none tuned: RSI 14 (30/70), MACD
  12/26/9 (long-only and long/short), Bollinger 20/2 (bounce and
  breakout), EMA 50/200 cross (long-only and long/short), Supertrend
  10/3, Ichimoku 9/26/52, Donchian 20, Stochastic 14/3 (20/80), and the
  bullish engulfing and hammer patterns (hold 5 bars).
- Costs 0.07% per side; longs pay the coin's real funding.
- Equal-weight portfolio across the 10 coins. Win rate = share of trades
  closed with a profit after costs. Full table in `results.csv`.

## Findings

1. **No indicator is right 90% of the time in the sense that matters.**
   RSI and Bollinger-bounce rules win 73–82% of trades, but most of them
   still lose money: many small wins, a few large losses. Win rate alone
   does not show whether a rule makes money.
2. **Trend-following indicators do work, modestly, on 4h and daily.**
   2024–26 CAGR: daily Supertrend +28%, daily Ichimoku +14%, daily
   Bollinger breakout +12%, 4h Ichimoku +11%. Equal-weight buy & hold of
   the same 10 coins made +3.4%. These rules win only 27–45% of trades
   and profit from a few large trends.
3. **They are not stable.** Daily Supertrend was the best rule in 2024–26
   but lost 16%/yr in 2020–23. Many rules that made 70–100%/yr in the
   2020–21 bull market are flat or negative since.
4. **On the 1-hour chart almost everything loses after costs.** 11 of 13
   rules are negative in 2024–26; MACD long/short lost 62%/yr.
5. None of the 39 rule × timeframe combinations reaches 100%/yr in
   2024–26. The best is 28%, with a −43% drawdown.
