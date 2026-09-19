"""Run a rule over stored history, against the controls that make it mean something.

A return on its own says nothing. This prints four things next to it, and the
comparisons are the report:

**Buy and hold.** Two years of crypto went up. A rule that made money and less
money than waiting has demonstrated nothing, and this is the comparison most
strategy reports quietly omit.

**The same decisions, shuffled.** The candidate's own decision sequence in a
random order, repeated many times. It keeps the mix — the same count of longs,
shorts and flats, so roughly the same trade count and the same fee bill — and
destroys only the information about *when*. If the candidate cannot beat its own
shuffled self, its timing carried nothing. This is a permutation test, and it is
worth more than a random-entry control because it controls for the one thing
random entry does not: the rule's directional bias in a market that trended.

**Always flat.** Proves the harness is not inventing trades. If it shows any
profit or loss, every other number in the run is suspect.

**Drawdown, not just return.** Phase 1 §1 ranks capital preservation above
return, so a report of return alone cannot be read against the objective.

**The holdout is not touched unless you ask for it.** By default this evaluates
the training period only. Phase 4's promotion gates exist because a rule
evaluated repeatedly on the same data eventually passes by luck, and the only
defence is data that has not been looked at. Every run with `--holdout` spends
some of that, and the flag exists to make spending it a decision rather than a
default.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

from libs.config import load_settings
from libs.exchange.hyperliquid.candles import Candle, CandleRequest
from libs.observability import configure_logging
from libs.storage import clickhouse as ch
from services.research.candle_store import read_candles
from services.research.costs import CostModel
from services.strategy_engine.candle_backtest import (
    CandleBacktest,
    CandleBacktestResult,
    execution_pairs,
)
from services.strategy_engine.decisions import (
    AlwaysFlat,
    BuyAndHold,
    Decision,
    Rule,
    Shuffled,
    TrendFollowing,
    TrendFollowingCalm,
)
from services.strategy_engine.features import FeatureConfig

MEASURED_HALF_SPREAD_BPS: Final = Decimal("0.4924")
"""Median half-spread measured on the recorded BTC book, 2026-09-19.

Used for both assets, and that is an understatement for SOL: a smaller book
quotes wider. Understating a cost makes a result look better, so this is
declared rather than hidden — and it is small enough at this horizon that it
changes nothing about the conclusion either way.
"""

RULES: Final = {
    "trend-following": TrendFollowing,
    "trend-following-calm": TrendFollowingCalm,
}


def _split(
    candles: Sequence[Candle], *, holdout_days: int
) -> tuple[tuple[Candle, ...], tuple[Candle, ...]]:
    """Training period first, holdout last, split on time rather than count.

    On time because a count split moves when more history arrives, and a
    holdout whose boundary drifts is a holdout that has been partly seen.
    """
    if not candles:
        return (), ()
    boundary = candles[-1].close_time - timedelta(days=holdout_days)
    train = tuple(candle for candle in candles if candle.close_time <= boundary)
    test = tuple(candle for candle in candles if candle.close_time > boundary)
    return train, test


def _run(rule: Rule, candles: Sequence[Candle], config: FeatureConfig) -> CandleBacktestResult:
    costs = CostModel(half_spread_bps=MEASURED_HALF_SPREAD_BPS)
    return CandleBacktest(rule=rule, costs=costs).run(candles, config)


def _decisions_of(rule: Rule, candles: Sequence[Candle], config: FeatureConfig) -> list[Decision]:
    """What the candidate decided, in order, for the shuffled control to reuse."""
    return [rule.decide(reading) for reading, _ in execution_pairs(candles, config)]


def _row(result: CandleBacktestResult) -> str:
    win = "     -" if result.win_rate is None else f"{result.win_rate:5.1f}%"
    return (
        f"  {result.rule:<26} {len(result.trades):>6}  {win}  "
        f"{result.return_pct:>7.1f}%  {result.max_drawdown_pct:>7.1f}%  "
        f"{result.exposure_pct:>5.0f}%"
    )


def _verdict(
    candidate: CandleBacktestResult,
    *,
    hold: CandleBacktestResult,
    shuffles: list[CandleBacktestResult],
) -> list[str]:
    """State what the numbers support, and nothing beyond it."""
    lines: list[str] = []
    beaten = sum(1 for run in shuffles if run.net_pnl >= candidate.net_pnl)
    lines.append(
        f"  vs shuffled : {beaten} of {len(shuffles)} random orderings did as well or better"
    )
    if beaten == 0:
        lines.append("                its timing carried information on this period")
    elif beaten > len(shuffles) // 20:
        lines.append("                its timing carried nothing this data can distinguish")

    difference = candidate.return_pct - hold.return_pct
    lines.append(f"  vs buy-hold : {difference:+.1f} points of return")
    if candidate.max_drawdown_pct < hold.max_drawdown_pct:
        lines.append(
            f"                but {hold.max_drawdown_pct - candidate.max_drawdown_pct:.1f} "
            f"points less drawdown"
        )

    lines.append("")
    if candidate.net_pnl <= 0:
        lines.append("  VERDICT: NO_EDGE_FOUND — the rule lost money net of costs.")
    elif beaten > 0:
        lines.append("  VERDICT: NO_EDGE_FOUND — profitable, but not beyond its own shuffle.")
    elif difference <= 0:
        lines.append("  VERDICT: NO_EDGE_FOUND — profitable, but worse than simply holding.")
    else:
        lines.append("  VERDICT: candidate survived this period. Not evidence of an edge yet —")
        lines.append("           one period, one rule, and the holdout still has to agree.")
    if candidate.costs_exceeded_edge:
        lines.append("  Rev.2 §25: profitable before costs, unprofitable after.")
    return lines


def _evaluate(
    name: str,
    candles: Sequence[Candle],
    *,
    config: FeatureConfig,
    shuffle_count: int,
    label: str,
) -> None:
    print()
    print(
        f"{label}: {candles[0].open_time:%Y-%m-%d} to {candles[-1].close_time:%Y-%m-%d} "
        f"({len(candles):,} candles)"
    )
    print()
    print(
        f"  {'rule':<26} {'trades':>6}  {'win%':>6}  {'return':>8}  {'drawdown':>8}  {'in mkt':>6}"
    )

    candidate = _run(RULES[name](), candles, config)
    hold = _run(BuyAndHold(), candles, config)
    flat = _run(AlwaysFlat(), candles, config)
    print(_row(candidate))
    print(_row(hold))
    print(_row(flat))

    if flat.net_pnl != 0 or flat.trades:
        print("  ** the flat control traded: the harness is wrong, ignore every number **")
        return

    decisions = _decisions_of(RULES[name](), candles, config)
    shuffles = [
        _run(Shuffled(decisions=decisions, seed=seed), candles, config)
        for seed in range(shuffle_count)
    ]
    returns = sorted(float(run.return_pct) for run in shuffles)
    print(
        f"  {'control-shuffled x' + str(shuffle_count):<26} "
        f"{'':>6}  {'':>6}  {statistics.median(returns):>7.1f}%  "
        f"[{returns[0]:.1f}% to {returns[-1]:.1f}%]"
    )
    print()
    for line in _verdict(candidate, hold=hold, shuffles=shuffles):
        print(line)


def main() -> int:
    import argparse  # noqa: PLC0415 - CLI-local

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="SOL")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--rule", default="trend-following", choices=sorted(RULES))
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument(
        "--holdout-days",
        type=int,
        default=180,
        help="days reserved at the end and not evaluated unless --holdout is passed",
    )
    parser.add_argument("--shuffles", type=int, default=20)
    parser.add_argument(
        "--holdout",
        action="store_true",
        help="also evaluate the reserved period; spends it, so pass it deliberately",
    )
    args = parser.parse_args()

    configure_logging()
    settings = load_settings()
    end = datetime.now(tz=UTC)
    request = CandleRequest(
        asset=args.asset.upper(),
        interval=args.interval,
        start=end - timedelta(days=args.days),
        end=end,
    )

    with ch.connect_from_settings(settings) as client:
        candles = read_candles(client, request)

    config = FeatureConfig()
    train, test = _split(candles, holdout_days=args.holdout_days)
    if len(train) < config.warmup + 2:
        print(
            f"only {len(train)} candles in the training period and {config.warmup} are "
            f"needed before a single feature is complete. Run `make history-all` first."
        )
        return 1

    print(f"{request.asset} {request.interval}, rule: {args.rule}")
    _evaluate(args.rule, train, config=config, shuffle_count=args.shuffles, label="TRAINING PERIOD")

    if not args.holdout:
        print()
        print(
            f"  The last {args.holdout_days} days ({len(test):,} candles) were not "
            f"evaluated.\n"
            f"  Pass --holdout to spend them. Do it once, on one rule, after the\n"
            f"  training period has given you something worth testing."
        )
        return 0

    if len(test) < config.warmup + 2:
        print()
        print(f"the holdout has {len(test)} candles, too few to evaluate")
        return 1
    _evaluate(args.rule, test, config=config, shuffle_count=args.shuffles, label="HOLDOUT PERIOD")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
