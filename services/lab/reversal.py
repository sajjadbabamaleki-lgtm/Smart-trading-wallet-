"""Buy the forced-selling overshoot (and sell the forced-buying one).

The hypothesis, stated before any result: when a cascade of liquidations
forces traders out, prices overshoot and partly recover; whoever supplies
liquidity at that moment is paid for it. The liquidity-provision return is
documented in equities and rises with volatility (Nagel, 2012, Review of
Financial Studies, "Evaporating Liquidity"); crypto liquidation cascades are
the extreme case. Trades are rare, so costs matter far less than in the
intraday breakout.

A cascade leaves a signature that candles show: an hour far outside the
coin's recent range, on volume far above its recent level. Rules, fixed here:
- coins: the lab's ten (BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, DOT),
  Binance hourly candles since 2020;
- event: an hourly return beyond 4 standard deviations of the past 7 days'
  hourly returns, on volume at least 3x the past 7 days' median hour;
- trade: against the move (long after a crash, short after a spike) at the
  close of that hour; out 24 hours later at the close, or at a 10% stop;
- one position per coin; each 10% of equity at entry;
- costs: 0.045% taker fee + 0.10% slippage per side (these are violent
  hours), and funding every 8 hours while open.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Final

from services.lab import binance
from services.lab.binance import Day
from services.lab.data import ASSETS
from services.lab.xsection import XResult

NAME: Final = "liquidation-reversal"
INTERVAL: Final = "1h"
LOOKBACK_HOURS: Final = 7 * 24
SIGMA_MULTIPLE: Final = 4.0
VOLUME_MULTIPLE: Final = 3.0
HOLD_HOURS: Final = 24
STOP: Final = 0.10
SLOT: Final = 0.10
COST_PER_SIDE: Final = 0.00045 + 0.0010
SOURCE: Final = (
    "Liquidity provision to forced sellers: Nagel (2012, RFS) in equities; crypto "
    "liquidation cascades as the extreme case. Event = 4-sigma hour on 3x volume."
)
HOUR: Final = timedelta(hours=1)
DIR: Final = binance.BINANCE_DIR.parent / "binance_1h"
SYMBOLS: Final = tuple(f"{a}USDT" for a in ASSETS)


def fetch(get: Callable[[str], bytes] = binance._get) -> int:
    """Download hourly candles for the ten coins. Returns the candles cached."""
    DIR.mkdir(parents=True, exist_ok=True)

    def one(symbol: str) -> int:
        prefix = f"{binance.KLINES_PREFIX}{symbol}/{INTERVAL}/"
        keys = [
            k
            for k in binance.list_keys(prefix, delimiter=False, get=get)
            if k.endswith(".zip") and binance._month(k) >= binance.FIRST_MONTH
        ]
        bars: dict[datetime, Day] = {}
        for key in sorted(keys):
            for bar in binance.parse_klines(get(f"{binance.BUCKET}/{key}")):
                bars[bar.time] = bar
        rows = sorted(
            [b.time.isoformat(), b.open, b.high, b.low, b.close, b.quote_volume]
            for b in bars.values()
        )
        (DIR / f"{symbol}.json").write_text(json.dumps(rows))
        return len(rows)

    with ThreadPoolExecutor(max_workers=len(SYMBOLS)) as pool:
        return sum(pool.map(one, SYMBOLS))


def load() -> dict[str, list[Day]]:
    out = {}
    for symbol in SYMBOLS:
        path = DIR / f"{symbol}.json"
        if not path.exists():
            raise FileNotFoundError("no hourly data; run `python -m services.lab.cli hourly-fetch`")
        out[symbol] = [
            Day(datetime.fromisoformat(r[0]), *r[1:]) for r in json.loads(path.read_text())
        ]
    return out


def events(bars: list[Day]) -> dict[int, int]:
    """Index of each event hour -> the trade direction (+1 long after a crash).
    Only the 7 days before the hour are used, never the hour itself."""
    out: dict[int, int] = {}
    returns = [0.0] + [b.close / a.close - 1 for a, b in pairwise(bars)]
    sums, squares = [0.0], [0.0]
    for r in returns:
        sums.append(sums[-1] + r)
        squares.append(squares[-1] + r * r)
    n = LOOKBACK_HOURS
    for i in range(n + 1, len(bars)):
        if bars[i].time - bars[i - n].time != HOUR * n:
            continue  # a gap in the data
        mean = (sums[i] - sums[i - n]) / n
        variance = (squares[i] - squares[i - n]) / n - mean * mean
        if variance <= 0 or abs(returns[i]) < SIGMA_MULTIPLE * variance**0.5:
            continue
        typical_volume = statistics.median(b.quote_volume for b in bars[i - n : i])
        if typical_volume and bars[i].quote_volume >= VOLUME_MULTIPLE * typical_volume:
            out[i] = -1 if returns[i] > 0 else 1
    return out


@dataclass
class _Trade:
    symbol: str
    direction: int
    units: float
    entry: float
    mark: float
    exit_at: datetime


def _step(trade: _Trade, bar: Day, rate: float) -> tuple[float, float, float, bool]:
    """One hour of an open trade: (PnL, costs, funding paid, closed?)."""
    stop = trade.entry * (1 - trade.direction * STOP)
    exit_price = None
    if (bar.low <= stop) if trade.direction == 1 else (bar.high >= stop):
        gapped = bar.open <= stop if trade.direction == 1 else bar.open >= stop
        exit_price = bar.open if gapped else stop
    elif bar.time >= trade.exit_at:
        exit_price = bar.close
    price = exit_price if exit_price is not None else bar.close
    pnl = trade.direction * trade.units * (price - trade.mark)
    trade.mark = price
    paid = trade.direction * trade.units * price * rate
    cost = trade.units * price * COST_PER_SIDE if exit_price is not None else 0.0
    return pnl - paid - cost, cost, paid, exit_price is not None


def run_reversal(
    _: binance.Market | None = None, hourly: dict[str, list[Day]] | None = None
) -> XResult:
    return _run(NAME, 1, hourly)


MOMENTUM_NAME: Final = "cascade-momentum"
MOMENTUM_SOURCE: Final = (
    "The mirror of liquidation-reversal, registered AFTER that strategy lost: every rule is "
    "the same, but the trade goes with the move. Because the idea came from the development "
    "data, only its holdout counts as evidence."
)


def run_momentum(
    _: binance.Market | None = None, hourly: dict[str, list[Day]] | None = None
) -> XResult:
    """Same events, stop, hold, sizing and costs as run_reversal; opposite side."""
    return _run(MOMENTUM_NAME, -1, hourly)


def _run(name: str, side: int, hourly: dict[str, list[Day]] | None) -> XResult:
    data = hourly or load()
    funding = {s: binance.funding_by_hour(s) for s in data}
    by_time = {s: {b.time: b for b in bars} for s, bars in data.items()}
    signals = {
        s: {bars[i].time: side * d for i, d in events(bars).items()} for s, bars in data.items()
    }
    hours = sorted({b.time for bars in data.values() for b in bars})

    equity = 1.0
    open_: dict[str, _Trade] = {}
    daily: dict[datetime, float] = {}
    basket_close: dict[datetime, dict[str, float]] = {}
    costs = turnover = paid = 0.0
    for t in hours:
        start = equity
        for symbol in list(open_):
            bar = by_time[symbol].get(t)
            if bar is None:
                continue
            trade = open_[symbol]
            pnl, cost, fee, closed = _step(trade, bar, funding[symbol].get(t + HOUR, 0.0))
            equity += pnl
            costs += cost
            paid += fee
            if closed:
                turnover += trade.units * trade.mark
                del open_[symbol]
        for symbol, direction in ((s, sig[t]) for s, sig in signals.items() if t in sig):
            if symbol in open_ or equity <= 0:
                continue
            price = by_time[symbol][t].close
            notional = SLOT * equity
            cost = notional * COST_PER_SIDE
            equity -= cost
            costs += cost
            turnover += notional
            open_[symbol] = _Trade(
                symbol, direction, notional / price, price, price, t + HOUR * HOLD_HOURS
            )
        day = t.replace(hour=0)
        daily[day] = (1 + daily.get(day, 0.0)) * (equity / start) - 1 if start > 0 else 0.0
        for symbol in data:
            bar = by_time[symbol].get(t)
            if bar is not None:
                basket_close.setdefault(day, {})[symbol] = bar.close

    days = sorted(daily)
    basket = [0.0]
    for a, b in pairwise(days):
        moves = [
            basket_close[b][s] / basket_close[a][s] - 1
            for s in basket_close[b]
            if s in basket_close[a]
        ]
        basket.append(statistics.fmean(moves) if moves else 0.0)
    return XResult(name, days, [daily[d] for d in days], basket, turnover, costs, paid)
