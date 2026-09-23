"""Fading liquidation-like hours."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from services.lab import reversal
from services.lab.binance import Day

START = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


def hours(n: int, crash_at: int | None = None, volume_spike: float = 5.0) -> list[Day]:
    bars, price = [], 100.0
    for i in range(n):
        move = 0.002 * math.sin(i)
        volume = 1e6
        if i == crash_at:
            move, volume = -0.05, 1e6 * volume_spike
        new = price * (1 + move)
        bars.append(Day(START + HOUR * i, price, max(price, new), min(price, new), new, volume))
        price = new
    return bars


def test_a_crash_on_heavy_volume_is_an_event_to_buy() -> None:
    assert reversal.events(hours(300, crash_at=250)) == {250: 1}


def test_a_crash_on_ordinary_volume_is_not() -> None:
    assert reversal.events(hours(300, crash_at=250, volume_spike=1.0)) == {}


def test_a_trade_stops_at_ten_percent() -> None:
    trade = reversal._Trade("X", 1, 1.0, 100.0, 100.0, START + HOUR * 24)
    bar = Day(START, 99.0, 99.0, 85.0, 86.0, 1.0)
    pnl, cost, _, closed = reversal._step(trade, bar, 0.0)
    assert closed and trade.mark == 90.0
    assert pnl == -10.0 - cost


def test_momentum_takes_the_other_side_of_the_same_events() -> None:
    data = {s: hours(300, crash_at=250) for s in reversal.SYMBOLS}
    fade = reversal.run_reversal(hourly=data)
    follow = reversal.run_momentum(hourly=data)
    assert fade.strategy != follow.strategy
    assert fade.costs == follow.costs  # identical trades, opposite direction
    assert sum(fade.returns) != sum(follow.returns)
