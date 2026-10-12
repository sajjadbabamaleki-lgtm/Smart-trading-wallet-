"""Daily paper trader for gold: Ichimoku long/short on Hyperliquid PAXG at 2x.

Paper only, like trader.py: public market data in, a ledger out, no orders.
Rule and leverage were chosen by the owner after EXP-010, which found that
gold indicator rules follow gold's trend and lose in flat markets. This run
is the live test of that.

    python -m research.paper_trading.gold_trader
    python -m research.paper_trading.gold_trader --backfill-from 2025-07-01
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from research.paper_trading import hl_data
from research.paper_trading.trader import report, step_days

HERE = Path(__file__).resolve().parent
COIN = "PAXG"
LEVERAGE = 2.0


def ichimoku_long_short(bars: pd.DataFrame) -> pd.Series:
    """+1 above the cloud with Tenkan over Kijun, -1 for the mirror image, else 0.

    The owner asked for both directions on 2026-10-12. On Binance PAXG at 2x
    this was worse than long-only in 2020-23 (-13% vs -2%) and 2024-25
    (+32% vs +107%) and better in 2026 YTD (+30% vs +21%).
    """
    h, lo, c = bars["high"], bars["low"], bars["close"]
    tenkan = (h.rolling(9).max() + lo.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + lo.rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((h.rolling(52).max() + lo.rolling(52).min()) / 2).shift(26)
    up = (c > span_a) & (c > span_b) & (tenkan > kijun)
    down = (c < span_a) & (c < span_b) & (tenkan < kijun)
    return up.astype(float) - down.astype(float)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-from", help="simulate from this date into ledger_gold_backfill/")
    args = ap.parse_args()
    ledger = HERE / ("ledger_gold_backfill" if args.backfill_from else "ledger_gold")
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    bars = hl_data.candles(COIN, "1d")
    bars = bars[(bars["close_ms"] < now_ms) & (bars["v"] > 0)]
    close = bars[["close"]].rename(columns={"close": COIN})
    since = (
        int(pd.Timestamp(args.backfill_from, tz="UTC").timestamp() * 1000)
        if args.backfill_from
        else now_ms - 90 * hl_data.DAY_MS
    )
    funding = hl_data.daily_funding(COIN, since).reindex(close.index).fillna(0.0).to_frame(COIN)
    signal = ichimoku_long_short(bars)
    weights = (signal * LEVERAGE).to_frame(COIN)
    start = args.backfill_from or f"{close.index[-1]:%Y-%m-%d}"
    rows = step_days(ledger, close, funding, weights, start)
    print(
        report(ledger, rows).replace(
            "leverage 1.5x", f"gold, Ichimoku long/short, leverage {LEVERAGE}x"
        )
    )


if __name__ == "__main__":
    pd.set_option("display.width", 120)
    main()
