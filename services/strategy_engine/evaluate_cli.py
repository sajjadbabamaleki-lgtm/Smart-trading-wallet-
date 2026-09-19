#!/usr/bin/env python3
"""Run the baseline strategies over recorded data and report what they did.

    python -m services.strategy_engine.evaluate_cli --hours 24
    python -m services.strategy_engine.evaluate_cli --hours 24 --hold 60 --threshold 0.4
    python -m services.strategy_engine.evaluate_cli --hours 24 --json

Three strategies are run over the same quotes, and the comparison between them
is the output — a single strategy's net PnL says almost nothing on its own.

    control-flat                trades nothing
    baseline-imbalance-only     depth imbalance alone
    baseline-imbalance-flow     depth imbalance and signed flow must agree

The control must return exactly zero. If it does not, the harness is charging
or crediting something it should not, and every other number in the run is
suspect. The one-signal version is what the two-signal version has to beat: if
requiring agreement adds nothing, the filter was decoration and the honest
conclusion is that it should go.

**A profit here is not a finding.** These parameters were not chosen out of
sample, the sample is a day or two of one asset, and a strategy tested on the
data that suggested it is the oldest mistake in this field. What a run does
establish is the sign and the scale — whether anything is even close to the
measured 3.41 bps maker floor, or whether it is off by an order of magnitude.
That is worth knowing before a week is spent on features.

The null hypothesis is that all of these lose money net of cost. It is the
expected result and a valid one.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs.config import ConfigurationError, load_settings  # noqa: E402
from libs.domain.clock import SystemClock  # noqa: E402
from libs.observability.logging import configure_logging  # noqa: E402
from libs.storage import clickhouse as ch  # noqa: E402
from services.research.backtest import BacktestEngine, BacktestResult, Strategy  # noqa: E402
from services.research.costs import CostModel  # noqa: E402
from services.research.dataset import DatasetSpec  # noqa: E402
from services.research.store import fetch_rows  # noqa: E402
from services.strategy_engine.baseline import (  # noqa: E402
    AlwaysFlatStrategy,
    BaselineStrategy,
    BookOnlyStrategy,
)
from services.strategy_engine.stream import quotes_from_rows  # noqa: E402

# Measured on this venue, 2026-09-19. Passed in rather than defaulted so the
# run says which cost it charged.
MEASURED_HALF_SPREAD_BPS = Decimal("0.4924")
MEASURED_MAKER_ADVERSE_BPS = Decimal("0.2033")


def _report(result: BacktestResult, costs: CostModel) -> dict[str, Any]:
    trades = result.trades
    net_bps = [trade.net_bps for trade in trades]
    mean_net = sum(net_bps, Decimal(0)) / len(net_bps) if net_bps else None
    return {
        "strategy": result.strategy,
        "quotes_seen": result.quotes_seen,
        "intents_formed": result.intents_formed,
        "intents_unfilled": result.intents_unfilled,
        "trades": len(trades),
        "wins": result.wins,
        "gross_pnl": str(result.gross_pnl),
        "fees": str(result.fees),
        "net_pnl": str(result.net_pnl),
        "mean_net_bps": None if mean_net is None else str(mean_net.quantize(Decimal("0.001"))),
        "mean_adverse_drift_bps": (
            None
            if result.mean_adverse_drift_bps is None
            else str(result.mean_adverse_drift_bps.quantize(Decimal("0.001")))
        ),
        "taker_round_trip_bps": str(costs.round_trip_bps),
        "maker_round_trip_bps": str(costs.maker_round_trip_bps),
        # The comparison that matters: a mean net return per trade below the
        # cost of the cheapest way to execute is not an edge.
        "beats_maker_floor": (None if mean_net is None else mean_net > costs.maker_round_trip_bps),
    }


def _print(report: dict[str, Any]) -> None:
    print(f"\n{report['strategy']}")
    print(f"  quotes seen        {report['quotes_seen']:,}")
    print(f"  intents formed     {report['intents_formed']:,}")
    print(f"  unfilled at end    {report['intents_unfilled']:,}")
    print(f"  completed trades   {report['trades']:,}")
    if report["trades"]:
        print(f"  won                {report['wins']:,}")
        print(f"  gross              {report['gross_pnl']}")
        print(f"  fees               {report['fees']}")
        print(f"  net                {report['net_pnl']}")
        print(f"  mean net per trade {report['mean_net_bps']} bps")
        print(f"  measured slippage  {report['mean_adverse_drift_bps']} bps on entry")
        print(f"  beats maker floor  {report['beats_maker_floor']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="BTC")
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--threshold", type=Decimal, default=Decimal("0.30"))
    parser.add_argument("--hold", type=float, default=30.0, help="seconds to hold")
    parser.add_argument("--flow-window", type=float, default=10.0, help="seconds")
    parser.add_argument(
        "--latency-ms",
        type=float,
        default=322.0,
        help="decision-to-fill latency; the default is the arrival floor alone",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"configuration refused: {exc}", file=sys.stderr)
        return 2

    configure_logging(settings.log_level, stream=sys.stderr)
    end = SystemClock().now()
    spec = DatasetSpec(
        asset=args.asset,
        range_start=end - timedelta(hours=args.hours),
        range_end=end,
        data_types=("BBO", "TRADE"),
    )

    try:
        with ch.connect_from_settings(settings) as client:
            rows = list(fetch_rows(client, spec))
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        print(f"could not read the store: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    quotes = list(quotes_from_rows(rows))
    if not quotes:
        print(
            f"{len(rows)} row(s) in range produced no two-sided quote. Nothing can be "
            f"backtested on this range",
            file=sys.stderr,
        )
        return 1

    costs = CostModel(
        half_spread_bps=MEASURED_HALF_SPREAD_BPS,
        maker_adverse_selection_bps=MEASURED_MAKER_ADVERSE_BPS,
    )
    hold = timedelta(seconds=args.hold)
    flow_window = timedelta(seconds=args.flow_window)

    strategies: list[Strategy] = [
        AlwaysFlatStrategy(),
        BookOnlyStrategy(threshold=args.threshold, hold=hold, flow_window=flow_window),
        BaselineStrategy(threshold=args.threshold, hold=hold, flow_window=flow_window),
    ]

    reports = []
    for strategy in strategies:
        engine = BacktestEngine(
            strategy=strategy,
            costs=costs,
            latency=timedelta(milliseconds=args.latency_ms),
        )
        reports.append(_report(engine.run(quotes), costs))

    if args.json:
        print(json.dumps({"rows": len(rows), "quotes": len(quotes), "runs": reports}, indent=2))
        return 0

    print(f"rows {len(rows):,} → quotes {len(quotes):,} over {args.hours}h of {args.asset}")
    print(f"threshold {args.threshold}, hold {args.hold:.0f}s, flow window {args.flow_window:.0f}s")
    print(f"latency {args.latency_ms:.0f} ms — the arrival floor alone, so optimistic")
    for report in reports:
        _print(report)

    control = reports[0]
    print()
    if control["trades"]:
        print(
            "WARNING: the control traded. It is built to do nothing, so the harness is\n"
            "doing something it should not and no number above can be trusted."
        )
    else:
        print("control traded nothing, as it must. The harness is not inventing fills.")
    print(
        "\nA profit here is not a finding: these parameters were not chosen out of\n"
        "sample, and a strategy tested on the data that suggested it proves nothing.\n"
        "What this establishes is sign and scale against a 3.41 bps maker floor."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
