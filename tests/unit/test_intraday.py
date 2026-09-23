"""The BTC noise-area breakout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.lab import intraday
from services.lab.binance import Day

START = datetime(2024, 1, 1, tzinfo=UTC)


def session(closes: list[float]) -> intraday.Session:
    bars, previous = [], closes[0]
    for i, c in enumerate(closes):
        t = START + timedelta(minutes=30 * i)
        bars.append(Day(t, previous, max(previous, c), min(previous, c), c, 1e6))
        previous = c
    return intraday.Session(START, bars)


def test_a_steady_rally_is_bought_and_closed_at_the_end_of_the_day() -> None:
    closes = [100 + i * 0.1 for i in range(48)]
    sigma = [0.001] * 48
    ret, cost = intraday._trade_day(session(closes), sigma, 1.0, {})
    entry_close = closes[1]  # first close above both the band and VWAP
    expected = closes[-1] / entry_close - 1 - 2 * intraday.COST_PER_SIDE
    assert ret == pytest.approx(expected, rel=0.05)
    assert cost == pytest.approx(2 * intraday.COST_PER_SIDE)


def test_a_quiet_day_inside_the_noise_area_does_not_trade() -> None:
    ret, cost = intraday._trade_day(session([100.0] * 48), [0.01] * 48, 2.0, {})
    assert ret == 0.0 and cost == 0.0


def test_incomplete_days_are_skipped() -> None:
    full = session([100.0] * 48).bars
    assert len(intraday.sessions(full)) == 1
    assert intraday.sessions(full[:-1]) == []
