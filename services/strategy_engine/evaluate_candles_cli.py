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
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

from libs.config import load_settings
from libs.domain.candles import Candle, CandleRequest
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
    Confirmed,
    Decision,
    Rule,
    Shuffled,
    TrendFollowing,
    TrendFollowingCalm,
)
from services.strategy_engine.features import FeatureConfig, FeatureSet

MEASURED_HALF_SPREAD_BPS: Final = Decimal("0.4924")
"""Median half-spread measured on the recorded BTC book, 2026-09-19.

Used for both assets, and that is an understatement for SOL: a smaller book
quotes wider. Understating a cost makes a result look better, so this is
declared rather than hidden — and it is small enough at this horizon that it
changes nothing about the conclusion either way.
"""


def _confirmed(candles: int = 2) -> Callable[[], Rule]:
    """A trend rule that waits for a regime change to hold before acting."""
    return lambda: Confirmed(inner=TrendFollowing(), confirm=candles)


RULES: Final[dict[str, Callable[[], Rule]]] = {
    "trend-following": TrendFollowing,
    "trend-following-calm": TrendFollowingCalm,
    "trend-confirmed": _confirmed(2),
    "trend-confirmed-3": _confirmed(3),
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


Pairs = Sequence[tuple[FeatureSet, Candle]]


def _halves(
    candles: Sequence[Candle], *, config: FeatureConfig
) -> list[tuple[str, tuple[Candle, ...]]]:
    """Split a period in two, each half carrying its own warmup.

    The second half starts `warmup` candles early so its features are complete
    from its first decision, and those extra candles are read but never decided
    on. Either half could instead be warmed from the data before it; this is
    simpler to reason about, and no feature reaches forward under either.
    """
    midpoint = len(candles) // 2
    first = tuple(candles[:midpoint])
    second = tuple(candles[max(0, midpoint - config.warmup) :])
    parts: list[tuple[str, tuple[Candle, ...]]] = []
    if len(first) >= config.warmup + 2:
        parts.append(("TRAINING, FIRST HALF", first))
    if len(second) >= config.warmup + 2:
        parts.append(("TRAINING, SECOND HALF", second))
    return parts


def _run(rule: Rule, pairs: Pairs) -> CandleBacktestResult:
    costs = CostModel(half_spread_bps=MEASURED_HALF_SPREAD_BPS)
    return CandleBacktest(rule=rule, costs=costs).run_pairs(pairs)


def _decisions_of(rule: Rule, pairs: Pairs) -> list[Decision]:
    """What the candidate decided, in order, for the shuffled control to reuse."""
    return [rule.decide(reading) for reading, _ in pairs]


def _row(result: CandleBacktestResult) -> str:
    win = "     -" if result.win_rate is None else f"{result.win_rate:5.1f}%"
    return (
        f"  {result.rule:<26} {len(result.trades):>6}  {win}  "
        f"{result.return_pct:>7.1f}%  {result.max_drawdown_pct:>7.1f}%  "
        f"{result.exposure_pct:>5.0f}%"
    )


def _economics(result: CandleBacktestResult) -> str:
    """Gross and cost per trade, which is where a fix is chosen.

    A rule can fail two ways that look identical in the return column: the
    signal is worthless, or the signal is fine and trades too often. These two
    numbers tell them apart, and they point at different work.
    """
    gross, fee = result.gross_bps_per_trade, result.fee_bps_per_trade
    if gross is None or fee is None:
        return f"  {result.rule:<26} no trades"
    return (
        f"  {result.rule:<26} gross {gross:>+7.2f} bps/trade  "
        f"cost {fee:>6.2f}  net {gross - fee:>+7.2f}"
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
    # Built once and shared by every rule below. Features are a property of
    # the candles and never of the rule, so computing them per rule did the
    # same work twenty-three times per evaluation.
    pairs = list(execution_pairs(candles, config))
    print()
    print(
        f"{label}: {candles[0].open_time:%Y-%m-%d} to {candles[-1].close_time:%Y-%m-%d} "
        f"({len(candles):,} candles)"
    )
    print()
    print(
        f"  {'rule':<26} {'trades':>6}  {'win%':>6}  {'return':>8}  {'drawdown':>8}  {'in mkt':>6}"
    )

    candidate = _run(RULES[name](), pairs)
    hold = _run(BuyAndHold(), pairs)
    flat = _run(AlwaysFlat(), pairs)
    print(_row(candidate))
    print(_row(hold))
    print(_row(flat))

    if flat.net_pnl != 0 or flat.trades:
        print("  ** the flat control traded: the harness is wrong, ignore every number **")
        return

    decisions = _decisions_of(RULES[name](), pairs)
    shuffles = [
        _run(Shuffled(decisions=decisions, seed=seed), pairs) for seed in range(shuffle_count)
    ]
    returns = sorted(float(run.return_pct) for run in shuffles)
    print(
        f"  {'control-shuffled x' + str(shuffle_count):<26} "
        f"{'':>6}  {'':>6}  {statistics.median(returns):>7.1f}%  "
        f"[{returns[0]:.1f}% to {returns[-1]:.1f}%]"
    )
    print()
    print("  per-trade economics — is the signal worth its transaction?")
    print(_economics(candidate))
    print(_economics(hold))
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
        "--venue",
        default="hyperliquid",
        choices=["hyperliquid", "binance"],
        help="which venue's stored history to read; binance reaches back years",
    )
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
    parser.add_argument(
        "--halves",
        action="store_true",
        help="evaluate the training period in two halves, to see whether the rule "
        "worked throughout it or only in part of it",
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
        candles = read_candles(client, request, venue=args.venue)

    config = FeatureConfig()
    train, test = _split(candles, holdout_days=args.holdout_days)
    if len(train) < config.warmup + 2:
        print(
            f"only {len(train)} candles in the training period and {config.warmup} are "
            f"needed before a single feature is complete. Run `make history-all` first."
        )
        return 1

    print(f"{request.asset} {request.interval}, rule: {args.rule}, venue: {args.venue}")
    _evaluate(args.rule, train, config=config, shuffle_count=args.shuffles, label="TRAINING PERIOD")

    if args.halves:
        # A rule that made all of its money in one half of the training period
        # and none in the other has not found a durable regularity; it found
        # one episode. This costs nothing — the training period is already
        # spent — and it is the cheapest way to fail a rule before the holdout
        # has to.
        for label, part in _halves(train, config=config):
            _evaluate(args.rule, part, config=config, shuffle_count=args.shuffles, label=label)

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
