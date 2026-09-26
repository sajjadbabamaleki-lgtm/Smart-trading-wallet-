# EXP-004 — Full Binance perp universe: trend, rotation, funding

**Status:** no strategy passed at 100%/yr. Hedged funding harvest passes at
roughly 10–15%/yr on the holdout. Everything else loses most or all of its
selection-period edge.

## Data (removes the biases of EXP-001…003)

- `data.binance.vision`: daily perp klines and the full funding history for
  all 865 USDT-M perps, delisted ones included. January 2020 → August 2026.
- Universe chosen point in time: top N by 30-day quote volume, at least 60
  days listed. A delisted coin takes a −30% final day.
- Real per-coin funding and real perp prices; costs 0.10% per turnover.
- Selection period 2020–2023, holdout 2024-01 → 2026-08.

## Directional strategies (24 variants)

| Family | Selection CAGR | Holdout CAGR | Holdout Max DD |
|---|---|---|---|
| Top-k momentum rotation + BTC filter | 59–143% | −48% … +21% | −66% … −95% |
| Cross-sectional funding (long low, short high) | −4% … 72% | −14% … +13% | −54% … −77% |
| Long-only trend (EXP-001 style) | 16–25% | −3% … +13% | −16% … −30% |
| BTC buy & hold (reference) | 56% | 26% | −53% |

The rotation strategies that looked like 100%+ on survivor data (EXP-002)
do not survive once delisted coins and point-in-time liquidity are
included. No directional strategy beat BTC buy & hold on the holdout.

## Hedged funding harvest

Each day, hold up to k coins whose trailing 3-day funding exceeds a
threshold: short the perp and buy the same amount of spot (no price
exposure), and collect funding. Round trip costs 0.40% of notional;
notional = 0.75 × capital.

- All coins: selection 12–17%/yr, holdout 19–40%/yr, max DD < 4%.
- **Only coins with a Binance spot market when chosen (the only version you
  can actually trade):** selection 12–15%/yr, **holdout 4.5–15.6%/yr**,
  max DD < 4%. With k = 5: 2024 +15%, 2025 +14%, 2026 YTD +3%.
- Not modelled: perp–spot basis moves, short-squeeze margin calls, and
  exchange/counterparty risk. More notional per unit of capital requires
  portfolio margin, where those risks become the binding constraint.

## Conclusion

On unbiased data, no tested strategy reaches 100%/yr on unseen data. The
robust edges are small: hedged funding harvest (~10–15%/yr, low volatility)
and long-only trend (single digits to low teens, mainly as drawdown
control).
