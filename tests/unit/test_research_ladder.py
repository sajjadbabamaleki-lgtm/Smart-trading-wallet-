"""The horizon ladder: how far price moves, measured at each horizon.

The ladder exists because a single measurement extrapolated by the square root
of time gave answers fifty times apart depending on which quantile it was
scaled from. These tests hold it to the two things that makes it worth having:
it must measure each horizon on its own, and it must say "not measurable" where
the sample cannot reach rather than inventing a figure or dying.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from services.research.calibrate_cli import LADDER_SECONDS, _ladder

START = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


def quote(offset_seconds: float, *, mid: str) -> dict[str, Any]:
    centre = Decimal(mid)
    return {
        "event_type": "BBO",
        "local_receive_time": START + timedelta(seconds=offset_seconds),
        "bid_price": centre - Decimal("0.5"),
        "ask_price": centre + Decimal("0.5"),
    }


def one_minute_of_quotes(*, step: str) -> list[dict[str, Any]]:
    """A minute of quotes, one a second, stepping `step` up and down."""
    high = Decimal(60000) + Decimal(step)
    return [
        quote(second, mid=str(Decimal(60000) if second % 2 == 0 else high)) for second in range(61)
    ]


class TestLadder:
    def test_each_horizon_is_measured_rather_than_scaled(self, capsys: Any) -> None:
        """Every reachable rung reports its own count, not one derived figure."""
        assert _ladder(one_minute_of_quotes(step="100")) == 0
        printed = capsys.readouterr().out
        for seconds in (1, 5, 10, 30, 60):
            assert f"{seconds}s" in printed

    def test_a_horizon_the_sample_cannot_reach_says_so(self, capsys: Any) -> None:
        """A minute of data cannot speak about an hour, and must not pretend to."""
        _ladder(one_minute_of_quotes(step="100"))
        printed = capsys.readouterr().out
        for seconds in (300, 900, 1800, 3600):
            assert f"{seconds}s  not measurable" in printed

    def test_a_move_larger_than_both_costs_clears_both(self, capsys: Any) -> None:
        """100 on 60000 is 16.7 bps, above the 9.98 bps of crossing."""
        _ladder(one_minute_of_quotes(step="100"))
        line = next(
            row for row in capsys.readouterr().out.splitlines() if row.startswith("         1s")
        )
        assert line.endswith("both")

    def test_a_move_below_the_resting_cost_clears_nothing(self, capsys: Any) -> None:
        """1 on 60000 is 0.17 bps: under 3.41, so no cost structure reaches it."""
        _ladder(one_minute_of_quotes(step="1"))
        line = next(
            row for row in capsys.readouterr().out.splitlines() if row.startswith("         1s")
        )
        assert line.endswith("-")

    def test_an_empty_sample_does_not_crash_the_ladder(self, capsys: Any) -> None:
        """The recorder has been down before. A down day is not an exception."""
        assert _ladder([]) == 0
        printed = capsys.readouterr().out
        assert printed.count("not measurable") == len(LADDER_SECONDS)
