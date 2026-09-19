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
from datetime import UTC, datetime
from pathlib import Path

from services.strategy_engine import evaluate_candles_cli

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

# Built from the CLI's own header functions rather than typed out. A sample
# written by hand is a sample that goes stale silently: the header gained a
# venue field, the parser still matched only the old shape, and the test kept
# passing while a real run returned nothing. Anything that changes these
# formats now fails here first.
RUN = evaluate_candles_cli.run_header(
    asset="BTC", interval="4h", rule="trend-confirmed", venue="binance"
)


def period(label: str, candles: int) -> str:
    return evaluate_candles_cli.period_header(
        label=label,
        start=datetime(2020, 9, 10, tzinfo=UTC),
        end=datetime(2026, 3, 23, tzinfo=UTC),
        candles=candles,
    )


def body(
    *,
    trades: int,
    win: str,
    ret: str,
    dd: str,
    expo: str,
    gross: str,
    beaten: int,
    versus: str,
    verdict: str,
) -> str:
    """One period's rows, in the shapes the CLI prints them in."""
    return f"""
  rule                       trades    win%    return  drawdown  in mkt
  trend-following-confirmed-2 {trades:>6}   {win}      {ret}      {dd}     {expo}
  control-buy-and-hold            1  100.0%      1.2%      9.1%    100%
  control-always-flat             0       -      0.0%      0.0%      0%

  per-trade economics — is the signal worth its transaction?
  trend-following-confirmed-2 gross  {gross} bps/trade  cost   9.98  net  +24.78

  vs shuffled : {beaten} of 200 random orderings did as well or better
  vs buy-hold : {versus} points of return

  VERDICT: {verdict}
"""


ONE_PERIOD = (
    RUN
    + "\n\n"
    + period("TRAINING PERIOD", 13098)
    + body(
        trades=106,
        win="53.8%",
        ret="2.6%",
        dd="1.9%",
        expo="47%",
        gross="+34.76",
        beaten=0,
        versus="+1.5",
        verdict="candidate survived this period. Not evidence of an edge yet —",
    )
)

THREE_PERIODS = (
    ONE_PERIOD
    + period("TRAINING, FIRST HALF", 6549)
    + body(
        trades=53,
        win="49.2%",
        ret="3.9%",
        dd="1.1%",
        expo="52%",
        gross="+73.90",
        beaten=2,
        versus="-18.1",
        verdict="NO_EDGE_FOUND — profitable, but worse than simply holding.",
    )
    + period("TRAINING, SECOND HALF", 6649)
    + body(
        trades=47,
        win="57.4%",
        ret="-1.2%",
        dd="1.8%",
        expo="43%",
        gross="-15.60",
        beaten=44,
        versus="+4.4",
        verdict="NO_EDGE_FOUND — the rule lost money net of costs.",
    )
)


class TestOnePeriod:
    def test_every_column_comes_from_that_period(self) -> None:
        (run,) = summarize.parse(ONE_PERIOD)  # type: ignore[attr-defined]
        assert run.asset == "BTC"
        assert run.interval == "4h"
        assert run.period == "TRAIN"
        assert run.trades == "106"
        assert run.venue == "binance"
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


class TestFormatDrift:
    """The failure mode this file kept having: the format moved, the parser did not."""

    def test_the_parser_reads_the_header_the_cli_actually_prints(self) -> None:
        header = evaluate_candles_cli.run_header(
            asset="ETH", interval="1d", rule="trend-following", venue="hyperliquid"
        )
        (run,) = summarize.parse(  # type: ignore[attr-defined]
            header + "\n\nTRAINING PERIOD: x\n  vs shuffled : 4 of 200\n"
        )
        assert (run.asset, run.interval, run.rule, run.venue) == (
            "ETH",
            "1d",
            "trend-following",
            "hyperliquid",
        )

    def test_a_header_that_grows_another_field_still_parses(self) -> None:
        """It has grown once already; the next time must not return nothing."""
        grown = (
            evaluate_candles_cli.run_header(
                asset="BTC", interval="4h", rule="trend-confirmed", venue="binance"
            )
            + ", horizon: 4h, seed: 7"
        )
        (run,) = summarize.parse(grown + "\n\nTRAINING PERIOD: x\n")  # type: ignore[attr-defined]
        assert (run.asset, run.rule, run.venue) == ("BTC", "trend-confirmed", "binance")

    def test_a_header_without_a_venue_defaults_rather_than_failing(self) -> None:
        """Older evaluation files on disk predate the venue field."""
        (run,) = summarize.parse(  # type: ignore[attr-defined]
            "SOL 4h, rule: trend-following\n\nTRAINING PERIOD: x\n"
        )
        assert run.venue == "hyperliquid"

    def test_the_period_labels_the_parser_knows_are_the_ones_emitted(self) -> None:
        """Every label the CLI can print must map to a short code, not to TRAIN.

        A label the parser does not recognise silently becomes "TRAIN", which
        would put a holdout row and a training row under the same name.
        """
        emitted = {
            "TRAINING PERIOD": "TRAIN",
            "TRAINING, FIRST HALF": "1st",
            "TRAINING, SECOND HALF": "2nd",
            "HOLDOUT PERIOD": "HOLD",
        }
        for label, expected in emitted.items():
            text = RUN + "\n\n" + period(label, 100) + "\n  vs shuffled : 1 of 200\n"
            (run,) = summarize.parse(text)  # type: ignore[attr-defined]
            assert run.period == expected, label
