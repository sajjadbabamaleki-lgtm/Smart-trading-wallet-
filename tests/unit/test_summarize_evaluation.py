"""Compressing an evaluation to one line per run.

This file exists because the summarizer shipped without it and produced a row
that mixed two periods: the guarded columns held the full period's numbers
while the unguarded ones were overwritten by the last half's, and the result
read like a clean result. A summary that silently mixes periods is worse than
no summary.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path("infrastructure/scripts/summarize_evaluation.py")


def _module() -> object:
    """Load the script by path; `infrastructure/scripts` is not a package."""
    spec = importlib.util.spec_from_file_location("summarize_evaluation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


summarize = _module()

ONE_PERIOD = """\
BTC 4h, rule: trend-confirmed

TRAINING PERIOD: 2024-09-19 to 2026-03-23 (3,299 candles)

  rule                       trades    win%    return  drawdown  in mkt
  trend-following-confirmed-2    106   53.8%      2.6%      1.9%     47%
  control-buy-and-hold            1  100.0%      1.2%      9.1%    100%
  control-always-flat             0       -      0.0%      0.0%      0%

  per-trade economics — is the signal worth its transaction?
  trend-following-confirmed-2 gross  +34.76 bps/trade  cost   9.98  net  +24.78

  vs shuffled : 0 of 200 random orderings did as well or better
  vs buy-hold : +1.5 points of return

  VERDICT: candidate survived this period. Not evidence of an edge yet —
"""

THREE_PERIODS = (
    ONE_PERIOD
    + """
TRAINING, FIRST HALF: 2024-09-19 to 2025-06-20 (1,649 candles)

  rule                       trades    win%    return  drawdown  in mkt
  trend-following-confirmed-2     61   49.2%      3.9%      1.1%     52%
  control-buy-and-hold            1  100.0%     22.0%      5.0%    100%
  control-always-flat             0       -      0.0%      0.0%      0%

  per-trade economics — is the signal worth its transaction?
  trend-following-confirmed-2 gross  +73.90 bps/trade  cost   9.97  net  +63.93

  vs shuffled : 2 of 200 random orderings did as well or better
  vs buy-hold : -18.1 points of return

  VERDICT: NO_EDGE_FOUND — profitable, but worse than simply holding.

TRAINING, SECOND HALF: 2025-06-20 to 2026-03-23 (1,749 candles)

  rule                       trades    win%    return  drawdown  in mkt
  trend-following-confirmed-2     47   57.4%     -1.2%      1.8%     43%
  control-buy-and-hold            1    0.0%    -17.0%      9.1%    100%
  control-always-flat             0       -      0.0%      0.0%      0%

  per-trade economics — is the signal worth its transaction?
  trend-following-confirmed-2 gross  -15.60 bps/trade  cost   9.98  net  -25.58

  vs shuffled : 44 of 200 random orderings did as well or better
  vs buy-hold : +4.4 points of return

  VERDICT: NO_EDGE_FOUND — the rule lost money net of costs.
"""
)


class TestOnePeriod:
    def test_every_column_comes_from_that_period(self) -> None:
        (run,) = summarize.parse(ONE_PERIOD)  # type: ignore[attr-defined]
        assert run.asset == "BTC"
        assert run.interval == "4h"
        assert run.period == "TRAIN"
        assert run.trades == "106"
        assert run.ret == "2.6%"
        assert run.gross == "+34.76"
        assert run.beaten == "0/200"
        assert run.versus_hold == "+1.5"

    def test_the_candidate_is_read_not_the_controls(self) -> None:
        """A wrapped rule renames itself, so the name cannot be matched on."""
        (run,) = summarize.parse(ONE_PERIOD)  # type: ignore[attr-defined]
        assert run.rule == "trend-following-confirmed-2"
        assert run.trades != "1"  # buy-and-hold's


class TestSeveralPeriods:
    """The defect this file was written for."""

    def test_each_period_is_its_own_row(self) -> None:
        runs = summarize.parse(THREE_PERIODS)  # type: ignore[attr-defined]
        assert [run.period for run in runs] == ["TRAIN", "1st", "2nd"]

    def test_no_column_leaks_between_periods(self) -> None:
        """The exact failure: shuffles and vs-buy-hold came from the last half.

        Every column of every row must come from the period that row names, and
        the three periods here are given deliberately different values in every
        column so a leak cannot hide.
        """
        full, first, second = summarize.parse(THREE_PERIODS)  # type: ignore[attr-defined]
        assert (full.beaten, full.versus_hold, full.ret) == ("0/200", "+1.5", "2.6%")
        assert (first.beaten, first.versus_hold, first.ret) == ("2/200", "-18.1", "3.9%")
        assert (second.beaten, second.versus_hold, second.ret) == ("44/200", "+4.4", "-1.2%")

    def test_the_asset_carries_across_periods(self) -> None:
        """The header appears once; the periods below it belong to it."""
        runs = summarize.parse(THREE_PERIODS)  # type: ignore[attr-defined]
        assert {run.asset for run in runs} == {"BTC"}
        assert {run.interval for run in runs} == {"4h"}

    def test_a_negative_half_is_reported_as_negative(self) -> None:
        """The whole purpose of the split: a rule that worked in only one half."""
        _, _, second = summarize.parse(THREE_PERIODS)  # type: ignore[attr-defined]
        assert second.ret.startswith("-")
        assert second.gross.startswith("-")


class TestRobustness:
    def test_an_unrecognised_line_is_skipped(self) -> None:
        noisy = ONE_PERIOD.replace(
            "  vs shuffled", '{"level":"INFO","message":"something"}\n  vs shuffled'
        )
        (run,) = summarize.parse(noisy)  # type: ignore[attr-defined]
        assert run.beaten == "0/200"

    def test_a_file_with_no_runs_parses_to_nothing(self) -> None:
        assert summarize.parse("nothing to see here\n") == []  # type: ignore[attr-defined]

    def test_a_period_before_any_header_is_ignored(self) -> None:
        """Rather than attaching numbers to an asset nobody named."""
        assert summarize.parse("TRAINING PERIOD: x\n  vs shuffled : 1 of 2\n") == []  # type: ignore[attr-defined]
