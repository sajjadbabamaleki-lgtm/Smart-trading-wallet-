"""Daily paper trader for gold: Ichimoku long-only on Hyperliquid PAXG at 2x.

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
from research.paper_trading.strategies import _rsi_free_trend_signals
from research.paper_trading.trader import report, step_days

HERE = Path(__file__).resolve().parent
COIN = "PAXG"
LEVERAGE = 2.0


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
    signal = _rsi_free_trend_signals(bars)["ichimoku"]
    weights = (signal * LEVERAGE).to_frame(COIN)
    start = args.backfill_from or f"{close.index[-1]:%Y-%m-%d}"
    rows = step_days(ledger, close, funding, weights, start)
    print(report(ledger, rows).replace("leverage 1.5x", f"gold, Ichimoku, leverage {LEVERAGE}x"))


if __name__ == "__main__":
    pd.set_option("display.width", 120)
    main()
