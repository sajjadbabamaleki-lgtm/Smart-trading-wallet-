"""Cross-venue funding arbitrage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from services.lab import crossvenue

START = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


def rates(n: int, hl: float, dydx: float) -> crossvenue.Rates:
    hours = [START + HOUR * i for i in range(n)]
    return crossvenue.Rates(
        dict.fromkeys(hours, hl), dict.fromkeys(hours, dydx), dict.fromkeys(hours, 100.0)
    )


def test_a_persistent_gap_is_earned_after_costs() -> None:
    # 0.005% an hour more on Hyperliquid is about 44% a year.
    result = crossvenue.run_arb({"BTC": rates(24 * 60, 0.00006, 0.00001)})
    total = 1.0
    for r in result.returns:
        total *= 1 + r
    notional = 1 / crossvenue.MAX_COINS * crossvenue.LEVERAGE / 2
    held = 24 * 60 - crossvenue.LOOKBACK_HOURS
    expected = notional * 0.00005 * held - notional * crossvenue.ROUND_TRIP / 2
    assert total - 1 == pytest.approx(expected, rel=0.02)
    assert result.funding < 0  # earned


def test_no_gap_means_no_trade() -> None:
    result = crossvenue.run_arb({"BTC": rates(24 * 10, 0.00001, 0.00001)})
    assert result.costs == 0 and all(r == 0 for r in result.returns)


def test_the_short_goes_on_the_venue_that_pays_more() -> None:
    result = crossvenue.run_arb({"ETH": rates(24 * 30, 0.00001, 0.00008)})
    assert result.funding < 0  # dYdX paid more: short dYdX, long Hyperliquid, and earn


def test_dydx_history_is_walked_back_page_by_page() -> None:
    def page(start: int, n: int) -> list[dict[str, str]]:
        return [
            {
                "effectiveAt": (START + HOUR * (start - i)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "rate": "0.00001",
                "price": "100",
            }
            for i in range(n)
        ]

    calls: list[str] = []

    def get_json(url: str) -> Any:
        calls.append(url)
        return {"historicalFunding": page(199, 100) if len(calls) == 1 else page(99, 100)}

    got, prices = crossvenue.fetch_dydx(
        "BTC", start=START, end=START + HOUR * 199, get_json=get_json, sleep=lambda _s: None
    )
    assert len(got) == 200 and len(prices) == 200
    assert "effectiveBeforeOrAt=2024-01-05T03:59:59.000Z" in calls[1]
