"""Short newly listed perpetuals.

The hypothesis, stated before any result: new coins list with a small
circulating supply and a large fully diluted value; over the following
months team and investor tokens unlock, launch hype fades, and the steady
supply pushes the price down, the crypto analogue of long-run IPO
underperformance (Ritter, 1991, Journal of Finance). The trade is too small
for large funds, which is why it might survive.

Rules, fixed here:
- a listing is a symbol's first day in the Binance data, from February 2020
  (the data starts in January 2020, so earlier coins are not new);
- short at the close of the listing's 7th day, skipping the first week's
  squeezes; hold 60 days, then buy back at the close;
- each short is 5% of equity at entry, at most 20 at once (100% gross);
  listings that arrive while 20 are open are skipped;
- a catastrophic stop buys back if the price doubles from entry, filled at
  the stop or at the open if the price gaps through it;
- costs: 0.045% taker fee + 0.30% slippage per side (new listings are thin),
  and daily funding: a short receives a positive rate and pays a negative one;
- a coin that stops trading is bought back at its last close.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from services.lab.binance import Day, Market
from services.lab.xsection import XResult

NAME: Final = "short-listings"
FIRST_LISTING: Final = datetime.fromisoformat("2020-02-01T00:00:00+00:00")
ENTRY_DAY: Final = 7
HOLD_DAYS: Final = 60
SLOT: Final = 0.05
MAX_OPEN: Final = 20
STOP_MULTIPLE: Final = 2.0
FEE: Final = 0.00045
SLIPPAGE: Final = 0.003
MAX_DRAWDOWN: Final = -0.30
"""Pre-registered risk limit for this strategy: a book of shorts has no
long-only basket to compare with, so the bar is fixed instead."""
SOURCE: Final = (
    "Hypothesis: token unlocks, low float / high FDV and fading launch hype push new "
    "listings down over their first months; the IPO analogue is Ritter (1991, JF)."
)
DAY: Final = timedelta(days=1)


@dataclass
class Short:
    symbol: str
    units: float
    entry: float
    mark: float
    exit_day: datetime


def listings(market: Market) -> dict[datetime, list[str]]:
    """Symbols by the day the short opens (the listing's 7th day)."""
    out: dict[datetime, list[str]] = {}
    for symbol, days in market.days.items():
        if days[0].time < FIRST_LISTING or len(days) <= ENTRY_DAY:
            continue
        out.setdefault(days[ENTRY_DAY].time, []).append(symbol)
    return out


@dataclass
class _Book:
    market: Market
    bars: dict[str, dict[datetime, Day]]
    last_day: dict[str, datetime]
    costs: float = 0.0
    funding: float = 0.0
    turnover: float = 0.0

    def trade_cost(self, notional: float) -> float:
        cost = notional * (FEE + SLIPPAGE)
        self.costs += cost
        self.turnover += notional
        return cost

    def step(self, pos: Short, day: datetime) -> tuple[float, bool]:
        """One day of a short: its PnL, and whether it is still open."""
        bar = self.bars[pos.symbol].get(day)
        if bar is None:
            if day > self.last_day[pos.symbol]:  # stopped trading: out at the last close
                return -self.trade_cost(pos.units * pos.mark), False
            return 0.0, True
        stop = pos.entry * STOP_MULTIPLE
        exit_price = None
        if bar.open >= stop:
            exit_price = bar.open
        elif bar.high >= stop:
            exit_price = stop
        elif day >= pos.exit_day or day == self.last_day[pos.symbol]:
            exit_price = bar.close
        price = exit_price if exit_price is not None else bar.close
        received = pos.units * price * self.market.funding.get(pos.symbol, {}).get(day, 0.0)
        self.funding += received
        pnl = pos.units * (pos.mark - price) + received
        pos.mark = price
        if exit_price is None:
            return pnl, True
        return pnl - self.trade_cost(pos.units * price), False


def run_short_listings(market: Market) -> XResult:
    book = _Book(
        market,
        {s: {d.time: d for d in days} for s, days in market.days.items()},
        {s: days[-1].time for s, days in market.days.items()},
    )
    entries = listings(market)
    end = max(book.last_day.values())

    equity = 1.0
    open_: list[Short] = []
    days_out: list[datetime] = []
    returns: list[float] = []
    day = min(entries)
    while day <= end:
        start_equity = equity
        still = []
        for pos in open_:
            pnl, keep = book.step(pos, day)
            equity += pnl
            if keep:
                still.append(pos)
        open_ = still
        for symbol in entries.get(day, []):
            if len(open_) >= MAX_OPEN or equity <= 0:
                break
            price = book.bars[symbol][day].close
            notional = SLOT * equity
            equity -= book.trade_cost(notional)
            open_.append(Short(symbol, notional / price, price, price, day + DAY * HOLD_DAYS))
        days_out.append(day)
        returns.append(equity / start_equity - 1 if start_equity > 0 else 0.0)
        day += DAY
    zeros = [0.0] * len(returns)
    return XResult(NAME, days_out, returns, zeros, book.turnover, book.costs, -book.funding)
