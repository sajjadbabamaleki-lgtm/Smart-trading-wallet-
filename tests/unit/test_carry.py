"""Funding carry: exact accounting, no look-ahead, rebalancing and negative funding."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from services.analyst.candles import Candle
from services.analyst.carry import CarryConfig, run_carry, run_carry_portfolio

START = datetime(2025, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
CONFIG = CarryConfig(lookback_hours=24)


def flat_candles(hours: int, price: float = 100.0) -> list[Candle]:
    return [
        Candle(START + HOUR * 4 * i, price, price, price, price, 1.0)
        for i in range((hours + 3) // 4)
    ]


def rates(values: list[float]) -> dict[datetime, float]:
    return {START + HOUR * i: rate for i, rate in enumerate(values)}


def test_always_on_accounting_is_exact() -> None:
    hours, rate = 24 * 10, 0.0001
    config = replace(CONFIG, always_on=True)
    result = run_carry(flat_candles(hours), rates([rate] * hours), config)

    notional = 10_000 * config.working_fraction
    held = hours - config.lookback_hours
    expected = 10_000 - 2 * notional * config.round_trip_cost + held * notional * rate
    assert result.equity_curve[-1][1] == pytest.approx(expected)
    assert result.funding_earned == pytest.approx(held * notional * rate)
    assert result.entries == 1
    assert result.time_invested == 1.0


def test_two_x_short_leaves_a_third_of_capital_idle() -> None:
    assert CarryConfig(perp_leverage=2).working_fraction == pytest.approx(2 / 3)


def test_negative_funding_is_paid_while_held() -> None:
    hours = 24 * 10
    result = run_carry(
        flat_candles(hours), rates([-0.0001] * hours), replace(CONFIG, always_on=True)
    )
    assert result.funding_earned < 0
    assert result.total_return < 0


def test_conditional_waits_for_high_past_funding_and_leaves_when_it_turns() -> None:
    # 2 days of zero, 3 days of rich funding, 3 days negative.
    values = [0.0] * 48 + [0.0002] * 72 + [-0.0002] * 72
    result = run_carry(flat_candles(len(values)), rates(values), CONFIG)
    assert result.entries == 1
    assert 0 < result.time_invested < 1
    # It exits once the trailing average falls to zero, so it pays less
    # negative funding than holding throughout would.
    always = run_carry(flat_candles(len(values)), rates(values), replace(CONFIG, always_on=True))
    assert result.total_return > always.total_return


def test_a_single_spike_is_not_seen_before_it_is_paid() -> None:
    # One enormous rate at hour 30. With only past data, the position cannot
    # be open to collect it.
    values = [0.0] * 30 + [1.0] + [0.0] * 60
    result = run_carry(flat_candles(len(values)), rates(values), CONFIG)
    assert result.funding_earned == 0.0


def test_large_price_moves_force_a_paid_rebalance() -> None:
    hours = 24 * 6
    candles = [
        Candle(START + HOUR * 4 * i, p, p, p, p, 1.0)
        for i, p in enumerate([100.0] * 18 + [130.0] * ((hours // 4) - 18))
    ]
    moved = run_carry(candles, rates([0.0] * hours), replace(CONFIG, always_on=True))
    still = run_carry(flat_candles(hours), rates([0.0] * hours), replace(CONFIG, always_on=True))
    assert moved.rebalances == 1
    assert moved.costs > still.costs


def test_too_little_history_is_refused() -> None:
    with pytest.raises(ValueError, match="not enough funding history"):
        run_carry(flat_candles(30), rates([0.0001] * 30), CONFIG)


def test_portfolio_splits_capital_and_sums_results() -> None:
    hours = 24 * 10
    a = (flat_candles(hours), rates([0.0001] * hours))
    b = (flat_candles(hours, 50.0), rates([0.0002] * hours))
    config = replace(CONFIG, always_on=True)
    portfolio = run_carry_portfolio({"A": a, "B": b}, config)
    final = portfolio.total.equity_curve[-1][1]
    assert final == pytest.approx(sum(r.equity_curve[-1][1] for r in portfolio.per_asset.values()))
    assert portfolio.per_asset["B"].funding_earned == pytest.approx(
        2 * portfolio.per_asset["A"].funding_earned
    )


def test_cli_carry_reports_both_rule_sets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from services.analyst import cli  # noqa: PLC0415

    hours = 24 * 12
    candles = flat_candles(hours)
    history: list[dict[str, Any]] = [
        {"time": int((START + HOUR * i).timestamp() * 1000), "fundingRate": "0.00002"}
        for i in range(hours)
    ]

    class Info:
        def candles_snapshot(self, *_request: Any) -> Any:
            return [
                {
                    "t": int(c.open_time.timestamp() * 1000),
                    "o": "100",
                    "h": "100",
                    "l": "100",
                    "c": "100",
                    "v": "1",
                }
                for c in candles
            ]

        def funding_history(self, _name: str, start: int, *_rest: Any) -> Any:
            return [row for row in history if row["time"] >= start]

    now = candles[-1].open_time + HOUR * 8
    monkeypatch.setattr(cli, "_info", lambda *_, **__: Info())
    monkeypatch.setattr(cli, "datetime", type("Now", (), {"now": staticmethod(lambda *_: now)}))
    monkeypatch.setattr("services.analyst.candles.PAGE_PAUSE_SECONDS", 0)
    assert cli.main(["carry", "--symbols", "SOL"]) == 0
    out = capsys.readouterr().out
    assert "CONDITIONAL" in out and "ALWAYS ON" in out
    assert "67% of capital earns funding" in out
