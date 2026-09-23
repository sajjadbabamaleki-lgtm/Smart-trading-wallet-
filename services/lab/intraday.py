"""Bitcoin intraday trend: the noise-area breakout, transplanted unchanged.

Zarattini, Aziz & Barbon (2024, Swiss Finance Institute Research Paper
24-97), "Beat the Market: An Effective Intraday Momentum Strategy for S&P500
ETF (SPY)". Concretum, the authors' firm, reports the same intraday trend
effect in Bitcoin (2018-2025), strongest from the Monday Asian open. Shen et
al. (2022, Financial Review) document intraday momentum in Bitcoin itself.

The rules are the paper's, fixed before any result; only the session is
adapted, since Bitcoin never closes: a day runs 00:00-24:00 UTC.
- the noise area at each half hour of the day: the day's open x (1 ± the
  average absolute move from the open to that half hour over the past 14 days);
- at each half-hour close: long above the upper band, short below the lower
  (and on the right side of VWAP, so an entry never sits already stopped out);
- trailing stop, checked at each half-hour close: a long exits below the
  higher of the upper band and the day's VWAP, a short above the lower of the
  lower band and VWAP; a stopped position may re-enter later in the day;
- flat at the end of every day;
- size: leverage = 2% target daily volatility / the past 14 days' daily
  volatility, at most 4x;
- costs: 0.045% taker fee + 0.02% slippage per side (BTC is the most liquid
  perp), and funding at 08:00 and 16:00 UTC while a position is open.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from services.lab import binance
from services.lab.binance import Day
from services.lab.xsection import XResult

NAME: Final = "btc-noise-breakout"
SYMBOL: Final = "BTCUSDT"
INTERVAL: Final = "30m"
BARS_PER_DAY: Final = 48
NOISE_DAYS: Final = 14
TARGET_DAILY_VOL: Final = 0.02
MAX_LEVERAGE: Final = 4.0
COST_PER_SIDE: Final = 0.00045 + 0.0002
SOURCE: Final = (
    "Zarattini, Aziz & Barbon (2024, SFI RP 24-97) noise-area rules, unchanged; Concretum's "
    "Bitcoin intraday trend study (2018-2025); Shen et al. (2022, Financial Review)."
)
DAY: Final = timedelta(days=1)
PATH: Final = binance.BINANCE_DIR.parent / "binance_30m" / f"{SYMBOL}.json"


def fetch(get: Callable[[str], bytes] = binance._get) -> int:
    """Download BTCUSDT 30-minute candles since 2020. Returns the number cached."""
    prefix = f"{binance.KLINES_PREFIX}{SYMBOL}/{INTERVAL}/"
    keys = [
        k
        for k in binance.list_keys(prefix, delimiter=False, get=get)
        if k.endswith(".zip") and binance._month(k) >= binance.FIRST_MONTH
    ]
    bars: dict[datetime, Day] = {}
    for key in sorted(keys):
        for bar in binance.parse_klines(get(f"{binance.BUCKET}/{key}")):
            bars[bar.time] = bar
    rows = [
        [b.time.isoformat(), b.open, b.high, b.low, b.close, b.quote_volume] for b in bars.values()
    ]
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(sorted(rows)))
    return len(rows)


def load_bars() -> list[Day]:
    if not PATH.exists():
        raise FileNotFoundError("no BTC 30m data; run `python -m services.lab.cli btc-fetch`")
    return [Day(datetime.fromisoformat(r[0]), *r[1:]) for r in json.loads(PATH.read_text())]


def load_funding() -> dict[datetime, float]:
    return binance.funding_by_hour(SYMBOL)


@dataclass(frozen=True)
class Session:
    day: datetime
    bars: list[Day]


def sessions(bars: list[Day]) -> list[Session]:
    """Complete UTC days only: a day with a missing half hour is skipped."""
    by_day: dict[datetime, list[Day]] = {}
    for bar in bars:
        by_day.setdefault(bar.time.replace(hour=0, minute=0), []).append(bar)
    return [
        Session(day, sorted(b, key=lambda x: x.time))
        for day, b in sorted(by_day.items())
        if len(b) == BARS_PER_DAY
    ]


def _trade_day(
    session: Session, sigma: list[float], leverage: float, funding: dict[datetime, float]
) -> tuple[float, float]:
    """One day's return on equity and its costs, following the paper's rules."""
    day_open = session.bars[0].open
    position = 0  # +1 long, -1 short
    entry = 0.0
    ret = cost = 0.0
    value = volume = 0.0
    for i, bar in enumerate(session.bars):
        typical = (bar.high + bar.low + bar.close) / 3
        value += bar.quote_volume
        volume += bar.quote_volume / typical if typical else 0.0
        vwap = value / volume if volume else bar.close
        upper, lower = day_open * (1 + sigma[i]), day_open * (1 - sigma[i])
        close_time = bar.time + timedelta(minutes=30)
        if position and close_time in funding and close_time.hour in (8, 16):
            ret -= position * leverage * funding[close_time]
        last = i == BARS_PER_DAY - 1
        exit_now = last or (
            (position == 1 and bar.close < max(upper, vwap))
            or (position == -1 and bar.close > min(lower, vwap))
        )
        if position and exit_now:
            ret += position * leverage * (bar.close / entry - 1)
            cost += leverage * COST_PER_SIDE
            position = 0
        if not position and not last:
            if bar.close > max(upper, vwap):
                position, entry = 1, bar.close
            elif bar.close < min(lower, vwap):
                position, entry = -1, bar.close
            if position:
                cost += leverage * COST_PER_SIDE
    return ret - cost, cost


def run_btc_noise(_: binance.Market | None = None) -> XResult:
    days = sessions(load_bars())
    funding = load_funding()
    moves = [[abs(bar.close / s.bars[0].open - 1) for bar in s.bars] for s in days]
    daily = [s.bars[-1].close / s.bars[0].open - 1 for s in days]
    out_days, returns, basket = [], [], []
    turnover = costs = 0.0
    for k in range(NOISE_DAYS, len(days)):
        if days[k].day - days[k - NOISE_DAYS].day > DAY * (NOISE_DAYS + 3):
            continue  # a gap in the data: the noise estimate would be stale
        past = moves[k - NOISE_DAYS : k]
        sigma = [statistics.fmean(m[i] for m in past) for i in range(BARS_PER_DAY)]
        vol = statistics.pstdev(daily[k - NOISE_DAYS : k])
        leverage = min(MAX_LEVERAGE, TARGET_DAILY_VOL / vol) if vol else 0.0
        r, c = _trade_day(days[k], sigma, leverage, funding)
        out_days.append(days[k].day)
        returns.append(r)
        basket.append(daily[k])
        costs += c
        turnover += c / COST_PER_SIDE
    return XResult(NAME, out_days, returns, basket, turnover, costs, 0.0)


def trading_days(result: XResult) -> float:
    """Share of days with at least one trade, for the report."""
    return sum(1 for r in result.returns if r != 0) / len(result.returns)
