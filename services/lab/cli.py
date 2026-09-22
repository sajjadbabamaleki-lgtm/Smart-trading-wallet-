"""Strategy lab commands.

    python -m services.lab.cli fetch            # download and cache the ten assets
    python -m services.lab.cli list             # the catalogue and each one's status
    python -m services.lab.cli run all          # every strategy on the development window
    python -m services.lab.cli run trend-trailing
    python -m services.lab.cli trials           # every trial, with its Deflated Sharpe
    python -m services.lab.cli holdout NAME     # once per strategy, on the locked months
    python -m services.lab.cli copy-fetch       # leaderboard accounts' PnL history
    python -m services.lab.cli copy-study       # do winning traders keep winning?

The pass criteria below are fixed in code, before any result.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.analyst.backtest import Metrics  # noqa: E402
from services.lab import copytrade, data, registry  # noqa: E402
from services.lab.engine import LabResult, annualised, run  # noqa: E402
from services.lab.strategies import CATALOGUE  # noqa: E402

DEV_MIN_DEFLATED_SHARPE: Final = 0.95
HOLDOUT_MIN_PROFIT_FACTOR: Final = 1.1
HOLDOUT_MIN_PSR: Final = 0.90


def _info() -> object:
    from hyperliquid.info import Info  # noqa: PLC0415 — network client, created on demand

    from services.trader.venues.hyperliquid import EMPTY_SPOT_META, base_url  # noqa: PLC0415

    return Info(base_url(True), skip_ws=True, spot_meta=EMPTY_SPOT_META, timeout=15)


def _check(ok: bool) -> str:
    return "✅" if ok else "❌"


def _print_metrics(title: str, m: Metrics) -> None:
    pf = "∞" if m.profit_factor == float("inf") else f"{m.profit_factor:.2f}"
    print(f"  {title}: {m.start:%Y-%m-%d} → {m.end:%Y-%m-%d}")
    print(
        f"    {m.trades} trades, win {m.win_rate:.0%}, avg {m.average_r:+.2f}R, PF {pf}, "
        f"return {m.total_return:+.1%}, max DD {m.max_drawdown:.1%}"
    )
    print(
        f"    basket buy & hold {m.buy_and_hold_return:+.1%} (max DD "
        f"{m.buy_and_hold_max_drawdown:.1%}); costs ${m.fees + m.funding:,.0f}"
    )


def _print_result(result: LabResult, deflated: float | None) -> None:
    weeks = (result.full.end - result.full.start) / timedelta(weeks=1)
    print(f"\n=== {result.strategy}  ({CATALOGUE[result.strategy].summary})")
    _print_metrics("whole window", result.full)
    _print_metrics("first half", result.first_half)
    _print_metrics("second half", result.second_half)
    print(
        f"  Sharpe {annualised(result.sharpe_per_bar):.2f}, "
        f"P(true Sharpe > 0) {result.full.probabilistic_sharpe:.0%}, "
        f"trades per week {len(result.trades) / weeks:.1f}"
    )
    busiest = ", ".join(f"{s} {n}" for s, n in sorted(result.trades_by_asset.items()))
    print(f"  trades by asset: {busiest}")
    if deflated is not None:
        halves = result.first_half.total_return > 0 and result.second_half.total_return > 0
        drawdown = result.full.max_drawdown > result.full.buy_and_hold_max_drawdown
        print(
            f"  Deflated Sharpe {deflated:.0%} {_check(deflated >= DEV_MIN_DEFLATED_SHARPE)}  "
            f"both halves up {_check(halves)}  drawdown below buy & hold {_check(drawdown)}"
        )


def _dev_window(dataset: data.Dataset) -> tuple[datetime, datetime]:
    return dataset.start + data.DEV_WARMUP, data.HOLDOUT_START


def cmd_fetch(_: argparse.Namespace) -> int:
    print("Downloading ten assets; rate limits make this take a few minutes.")
    report, failed = data.fetch(_info(), now=datetime.now(UTC))
    print("\n".join(report))
    if failed:
        print(f"\nWARNING: {', '.join(failed)} failed; run fetch again to retry.")
    return 1 if failed else 0


def cmd_list(_: argparse.Namespace) -> int:
    entries = registry.load()
    trials = registry.development_trials(entries)
    for name, cls in CATALOGUE.items():
        status = "tested" if name in trials else "not yet run"
        if registry.holdout_used(name, entries):
            status += ", holdout USED"
        print(f"\n{name}  [{status}]\n  {cls.summary}\n  source: {cls.source}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    dataset = data.load()
    start, end = _dev_window(dataset)
    names = list(CATALOGUE) if args.strategy == "all" else [args.strategy]
    unknown = [n for n in names if n not in CATALOGUE]
    if unknown:
        raise ValueError(f"unknown strategy {unknown[0]!r}; see `list`")
    print(
        f"Development window {start:%Y-%m-%d} → {end:%Y-%m-%d}, {len(dataset.candles)} assets. "
        f"The months after {end:%Y-%m-%d} stay locked."
    )
    results = []
    for name in names:
        result = run(CATALOGUE[name](), dataset, start=start, end=end)
        registry.record(result, "development")
        results.append(result)
    trials = registry.development_trials(registry.load())
    for result in results:
        _print_result(result, registry.deflated_for(trials[result.strategy], trials))
    print(
        f"\nTrials counted so far: {len(trials)} in the lab + {registry.PRIOR_TRIALS} before it."
        "\nA strategy is worth its one holdout run only if all three checks pass."
    )
    return 0


def cmd_trials(_: argparse.Namespace) -> int:
    entries = registry.load()
    trials = registry.development_trials(entries)
    if not trials:
        print("no trials yet")
        return 0
    print(f"{len(trials)} strategies tried in the lab, + {registry.PRIOR_TRIALS} before it\n")
    print(f"  {'strategy':<20} {'return':>8} {'trades':>7} {'Sharpe':>7} {'deflated':>9}")
    for name, entry in sorted(trials.items(), key=lambda kv: -kv[1]["sharpe_per_bar"]):
        deflated = registry.deflated_for(entry, trials)
        print(
            f"  {name:<20} {entry['total_return']:>+8.1%} {entry['trades']:>7} "
            f"{annualised(entry['sharpe_per_bar']):>7.2f} {deflated:>9.0%}"
        )
    for entry in entries:
        if entry["window"] == "holdout":
            print(f"\n  holdout: {entry['strategy']} {entry['total_return']:+.1%}")
    return 0


def cmd_holdout(args: argparse.Namespace) -> int:
    entries = registry.load()
    if args.strategy not in CATALOGUE:
        raise ValueError(f"unknown strategy {args.strategy!r}")
    if registry.holdout_used(args.strategy, entries):
        raise ValueError(
            f"{args.strategy} has already used its holdout. A second look would turn the "
            "holdout into development data; add a new strategy instead."
        )
    if args.strategy not in registry.development_trials(entries):
        raise ValueError("run it on the development window first")
    dataset = data.load()
    result = run(
        CATALOGUE[args.strategy](),
        dataset,
        start=data.HOLDOUT_START,
        end=dataset.end + timedelta(hours=4),
    )
    registry.record(result, "holdout")
    _print_result(result, None)
    m = result.full
    checks = {
        "profitable": m.total_return > 0,
        f"profit factor ≥ {HOLDOUT_MIN_PROFIT_FACTOR}": m.profit_factor
        >= HOLDOUT_MIN_PROFIT_FACTOR,
        "drawdown below buy & hold": m.max_drawdown > m.buy_and_hold_max_drawdown,
        f"P(true Sharpe > 0) ≥ {HOLDOUT_MIN_PSR:.0%}": m.probabilistic_sharpe >= HOLDOUT_MIN_PSR,
    }
    print("\nHoldout verdict:")
    for label, ok in checks.items():
        print(f"  {_check(ok)} {label}")
    print("\nPASSED — next is paper trading." if all(checks.values()) else "\nNOT PASSED.")
    return 0


def cmd_copy_fetch(_: argparse.Namespace) -> int:
    print(f"Downloading the leaderboard and {copytrade.POOL_SIZE} accounts' history (minutes).")
    pool, failed = copytrade.fetch(_info())
    print(f"{pool - len(failed)} of {pool} accounts cached.")
    if failed:
        print(f"WARNING: {len(failed)} failed; run copy-fetch again to retry.")
    return 0


def cmd_copy_study(_: argparse.Namespace) -> int:
    study = copytrade.run_study(copytrade.load(), now=datetime.now(UTC))
    s = study.selection_date
    print(
        f"Selection date {s:%Y-%m-%d}: period A {s - copytrade.PERIOD:%Y-%m-%d} → {s:%Y-%m-%d}, "
        f"period B {s:%Y-%m-%d} → {s + copytrade.PERIOD:%Y-%m-%d}"
    )
    print(f"  {len(study.outcomes)} of {study.pool} accounts have history covering both periods")
    print(f"  rank correlation A→B {study.spearman:+.2f} (p = {study.p_value:.3f})")
    print(
        f"  period B median return: top decile of A {study.top_median_b:+.1%} "
        f"({study.top_profitable_b:.0%} profitable), all {study.pool_median_b:+.1%}, "
        f"bottom decile {study.bottom_median_b:+.1%}"
    )
    print("\nVerdict:")
    for label, ok in study.checks.items():
        print(f"  {_check(ok)} {label}")
    passed = all(study.checks.values())
    print(
        "\nPASSED — next: simulate copying their fills with delay and costs."
        if passed
        else "\nNOT PASSED — past winners here do not keep winning; copying them has no edge."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lab", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fetch", help="download and cache the dataset").set_defaults(fn=cmd_fetch)
    commands.add_parser("list", help="the strategy catalogue").set_defaults(fn=cmd_list)
    run_cmd = commands.add_parser("run", help="run on the development window")
    run_cmd.add_argument("strategy", help="a strategy name, or 'all'")
    run_cmd.set_defaults(fn=cmd_run)
    commands.add_parser("trials", help="every trial so far").set_defaults(fn=cmd_trials)
    holdout = commands.add_parser("holdout", help="the one evaluation on the locked months")
    holdout.add_argument("strategy")
    holdout.set_defaults(fn=cmd_holdout)
    commands.add_parser("copy-fetch", help="cache leaderboard accounts").set_defaults(
        fn=cmd_copy_fetch
    )
    commands.add_parser("copy-study", help="persistence of trader returns").set_defaults(
        fn=cmd_copy_study
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except (ValueError, FileNotFoundError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
