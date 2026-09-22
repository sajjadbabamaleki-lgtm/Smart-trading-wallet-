"""One analysis: chart signal, then funding, calendar and news filters.

The chart decides direction, stop and target. Every other input can only
remove a trade. The result says whether it may be executed automatically;
that requires every check to have actually run — an unavailable news check
or an out-of-date calendar blocks automation instead of being ignored.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from services.analyst import calendar
from services.analyst.candles import Candle, fetch_hyperliquid
from services.analyst.news import NewsCheck
from services.analyst.strategy import Signal, StrategyParams, TrendIndicators
from services.trader.venue import Direction

NewsChecker = Callable[[str, Direction, datetime], NewsCheck]


@dataclass(frozen=True)
class Analysis:
    symbol: str
    interval: str
    as_of: datetime
    """Open time of the last closed candle the signal used."""
    signal: Signal
    funding_hourly: float | None
    calendar: calendar.CalendarCheck
    news: NewsCheck | None
    vetoes: list[str] = field(default_factory=list)
    automation_blockers: list[str] = field(default_factory=list)

    @property
    def direction(self) -> Direction | None:
        return None if self.vetoes else self.signal.direction

    @property
    def may_auto_execute(self) -> bool:
        return self.direction is not None and not self.automation_blockers


def current_funding(info: Any, symbol: str) -> float | None:
    meta, contexts = info.meta_and_asset_ctxs()
    for asset, context in zip(meta["universe"], contexts, strict=False):
        if asset["name"] == symbol:
            funding = context.get("funding")
            return float(funding) if funding is not None else None
    return None


def analyse_candles(  # noqa: PLR0913 — keyword-only analysis inputs
    candles: list[Candle],
    *,
    symbol: str,
    interval: str,
    now: datetime,
    funding_hourly: float | None,
    news_checker: NewsChecker | None,
    params: StrategyParams | None = None,
) -> Analysis:
    indicators = TrendIndicators(candles, interval, params or StrategyParams())
    last = len(candles) - 1
    signal = indicators.signal(last, funding_hourly=funding_hourly)
    events = calendar.check(now)

    vetoes: list[str] = []
    blockers: list[str] = []
    if events.blocking is not None:
        vetoes.append(
            f"{events.blocking.name} at {events.blocking.at:%Y-%m-%d %H:%M %Z}: "
            "no new positions in the window around it"
        )
    if events.stale:
        blockers.append("the macro calendar is out of date; extend services/analyst/calendar.py")

    news: NewsCheck | None = None
    if signal.direction is not None:
        if news_checker is None:
            blockers.append("news was not checked")
        else:
            news = news_checker(symbol, signal.direction, now)
            vetoes.extend(news.vetoes)
            if not news.available:
                blockers.append("news could not be checked")

    return Analysis(
        symbol=symbol,
        interval=interval,
        as_of=candles[last].open_time,
        signal=signal,
        funding_hourly=funding_hourly,
        calendar=events,
        news=news,
        vetoes=vetoes,
        automation_blockers=blockers,
    )


def analyse(  # noqa: PLR0913 — keyword-only analysis inputs
    info: Any,
    *,
    symbol: str,
    interval: str,
    now: datetime,
    news_checker: NewsChecker | None,
    params: StrategyParams | None = None,
) -> Analysis:
    candles = fetch_hyperliquid(info, symbol, interval, now=now)
    return analyse_candles(
        candles,
        symbol=symbol,
        interval=interval,
        now=now,
        funding_hourly=current_funding(info, symbol),
        news_checker=news_checker,
        params=params,
    )
