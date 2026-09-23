"""Shorting new listings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.lab import listings
from services.lab.binance import Day, Market

START = datetime(2021, 1, 1, tzinfo=UTC)
DAY = timedelta(days=1)


def coin(first: int, n: int, path: list[float] | None = None) -> list[Day]:
    prices = path or [100.0] * n
    return [
        Day(START + DAY * (first + i), p, p * 1.01, p * 0.99, p, 1e6) for i, p in enumerate(prices)
    ]


def test_old_coins_are_not_listings_and_entry_is_on_day_seven() -> None:
    market = Market(
        {"OLDUSDT": [Day(datetime(2020, 1, 1, tzinfo=UTC), 1, 1, 1, 1, 1)], "NEWUSDT": coin(0, 20)},
        {},
    )
    assert listings.listings(market) == {START + DAY * 7: ["NEWUSDT"]}


def test_a_falling_listing_earns_and_a_doubling_one_is_stopped() -> None:
    falling = [100.0 * (0.99**i) for i in range(100)]
    doubling = [100.0] * 8 + [100.0 * 1.2**i for i in range(1, 60)]
    market = Market({"DOWNUSDT": coin(0, 100, falling), "UPUSDT": coin(0, 67, doubling)}, {})
    result = listings.run_short_listings(market)
    equity = 1.0
    for r in result.returns:
        equity *= 1 + r
    # Down 45% over 60 days on 5% of equity: about +2.2%; up coin stopped at 2x: about -5%.
    assert equity == pytest.approx(1 + 0.05 * (1 - 0.99**60) - 0.05 - 4 * 0.05 * 0.00345, abs=0.004)
    assert result.costs > 0


def test_funding_paid_by_shorts_when_negative() -> None:
    market = Market({"AUSDT": coin(0, 80)}, {"AUSDT": {START + DAY * d: -0.001 for d in range(80)}})
    result = listings.run_short_listings(market)
    assert result.funding > 0  # the short paid
