"""Binance, as a source of historical candles and nothing else.

**No execution, no credentials, no order path.** This package exists because
Hyperliquid retains about 5,000 candles per interval — 208 days of hours, 833
days of 4h — and a rule that depends on the market's regime cannot be tested
over a window containing roughly one regime change. Binance publishes years of
free public klines, which is the only thing wanted here.

The prices are a different venue's. For research into *patterns* that is
acceptable — BTC, ETH, SOL and BNB track closely across major venues — and it
is not acceptable for costs or execution, which stay Hyperliquid's throughout.
Rows are stored with `venue = "binance"` so the two can never be silently
mixed, and a backtest says which it used.
"""

from libs.exchange.binance.candles import VENUE, fetch_candles

__all__ = ["VENUE", "fetch_candles"]
