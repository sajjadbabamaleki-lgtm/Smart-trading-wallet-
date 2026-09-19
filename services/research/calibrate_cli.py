#!/usr/bin/env python3
"""Measure cost-model inputs from recorded BTC data (M5).

    python -m services.research.calibrate_cli --hours 2

Reads recorded quotes from ClickHouse and reports what they say about the cost
of trading them: the half-spread a crossing order pays, and how far mid moves
over the decision delay. Both as distributions, because the mean of either is
the number least likely to describe the moment a strategy trades.

The delay defaults to the arrival floor this project measured against the live
venue on 2026-09-14. That is the *optimistic* setting: it counts the venue's
own publication delay and nothing of our decoding, feature computation,
inference, risk check or order transmission. Pass a larger --delay-ms to see
what a realistic end-to-end path faces.

This writes nothing. It is a measurement, and what to do about it is a
decision for a research note.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Final

from libs.config import load_settings
from libs.domain.clock import SystemClock
from libs.observability.logging import configure_logging
from libs.storage import clickhouse as ch
from services.research.costs import BASE_MAKER_FEE_BPS as MAKER_FEE_BPS
from services.research.costs import MEASURED_DATA_ARRIVAL_FLOOR_MS, CostModel, hurdle
from services.research.dataset import DatasetSpec
from services.research.measure import MeasurementError, calibrate, measure_mid_move_bps
from services.research.store import fetch_rows

REFERENCE_PRICE = Decimal(60000)
"""Only to express the hurdle as a price move.

A round-trip cost in basis points is the real quantity and is
price-independent; this turns it into something a person can picture.
Nothing is computed from it.
"""


# Horizons worth asking about, given that a taker round trip costs about 10 bps
# and a maker round trip about 3.4. Deliberately spanning three orders of
# magnitude: the question is where the available move crosses the cost, and
# guessing the answer's neighbourhood is how you measure only inside it.
LADDER_SECONDS: Final = (1, 5, 10, 30, 60, 300, 900, 1800, 3600)


def _ladder(rows: list[dict[str, object]]) -> int:
    """How far price actually moves at each horizon, measured rather than scaled.

    This exists because extrapolating from one horizon is not defensible here.
    Scaling the 322 ms measurement forward by the square root of time gives an
    answer that differs by a factor of fifty depending on whether the median or
    the p90 is scaled from — 0.098 bps of implied sigma against 0.711 — which
    means the distribution is nowhere near Gaussian and the square-root rule
    has nothing to stand on.

    So each horizon is measured on its own. No rule, no fitting, and every row
    is one the recorder actually captured.

    What the result is, and is not: the move is unsigned, so the median at a
    horizon is the *ceiling* on what a strategy with perfect direction could
    capture there. A horizon whose ceiling is below the cost is closed to any
    signal. A horizon whose ceiling is above it is merely not closed — clearing
    the cost is necessary, never sufficient, and the direction still has to be
    predicted.
    """
    taker = hurdle(CostModel(half_spread_bps=Decimal("0.4924"))).round_trip_bps
    maker = CostModel(
        half_spread_bps=Decimal("0.4924"), maker_adverse_selection_bps=Decimal("0.2033")
    ).maker_round_trip_bps

    print(f"mid move by horizon, measured over {len(rows):,} rows (bps, unsigned)")
    print(f"cost to beat: {maker:.2f} bps resting, {taker:.2f} bps crossing")
    print()
    print(f"  {'horizon':>9}  {'count':>8}  {'p50':>8}  {'p90':>8}  {'p95':>9}  {'p99':>9}  clears")
    for seconds in LADDER_SECONDS:
        try:
            moved = measure_mid_move_bps(rows, delay=timedelta(seconds=seconds))
        except MeasurementError as exc:
            print(f"  {seconds:>8}s  not measurable: {exc}")
            continue
        # Which cost the median move clears, if either. The median rather than
        # the mean: a strategy trades at a typical moment, not an average one.
        clears = "resting" if moved.p50 > maker else "-"
        if moved.p50 > taker:
            clears = "both"
        print(
            f"  {seconds:>8}s  {moved.count:>8,}  {moved.p50:>8.2f}  "
            f"{moved.p90:>8.2f}  {moved.p95:>9.2f}  {moved.p99:>9.2f}  {clears}"
        )
    print()
    print(
        "Read the p50 column, not a mean: a strategy trades at a typical moment,\n"
        "and a mean here is carried by the tail.\n"
        "\n"
        "The move is unsigned, so each figure is a ceiling — what a strategy that\n"
        "called direction perfectly could have captured. Below the cost the\n"
        "horizon is closed to every signal. Above it the horizon is only open,\n"
        "and the direction still has to be predicted."
    )
    return 0


def main() -> int:
    import argparse  # noqa: PLC0415 - CLI-local

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="BTC")
    parser.add_argument("--hours", type=float, default=2.0)
    parser.add_argument(
        "--delay-ms",
        type=float,
        default=float(MEASURED_DATA_ARRIVAL_FLOOR_MS),
        help="Decision delay to measure price movement over.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--ladder",
        action="store_true",
        help="measure the mid-move distribution at a range of horizons, and stop",
    )
    args = parser.parse_args()

    configure_logging()
    settings = load_settings()
    end = SystemClock().now()
    spec = DatasetSpec(
        asset=args.asset,
        range_start=end - timedelta(hours=args.hours),
        range_end=end,
        # TRADE is here for the passive-fill markout, which needs to know who
        # chose to trade and at what price. The two quote-only measurements
        # ignore these rows; without them the markout has nothing to locate a
        # fill against and reports "not measured", which is what it did.
        data_types=("BBO", "L2_SNAPSHOT", "TRADE"),
    )

    with ch.connect_from_settings(settings) as client:
        rows = fetch_rows(client, spec)

    if args.ladder:
        return _ladder(list(rows))

    result = calibrate(list(rows), delay=timedelta(milliseconds=args.delay_ms))
    measured = CostModel(half_spread_bps=result.half_spread_bps.p50)
    threshold = hurdle(measured)

    if args.json:
        print(
            json.dumps(
                {
                    "calibration": result.as_dict(),
                    "hurdle": threshold.describe(REFERENCE_PRICE),
                },
                indent=2,
            )
        )
        return 0

    print(f"sample          {result.sample_rows} rows over {args.hours}h")
    print(f"delay           {args.delay_ms:.0f} ms")
    print()
    print("half-spread (bps, per side)")
    for key, value in result.half_spread_bps.as_dict().items():
        print(f"  {key:6} {value}")
    print()
    print(f"mid move over {args.delay_ms:.0f} ms (bps, unsigned)")
    for key, value in result.mid_move_bps.as_dict().items():
        print(f"  {key:6} {value}")
    print()
    print(f"round trip now costs {threshold.round_trip_bps} bps by crossing (taker)")
    print(f"fully measured: {threshold.is_fully_measured} (adverse drift is M6's question)")

    markout = result.passive_markout_bps
    if markout is not None and result.markout_horizon is not None:
        seconds = result.markout_horizon.total_seconds()
        print()
        print(f"passive fill markout over {seconds:.0f}s (bps, signed; negative is adverse)")
        for key, value in markout.as_dict().items():
            print(f"  {key:6} {value}")
        print()
        # The comparison the maker question turns on, written out rather than
        # left for the reader to assemble from two tables.
        maker_round_trip = MAKER_FEE_BPS * 2 - markout.mean * 2
        print(f"  resting instead of crossing pays {MAKER_FEE_BPS * 2} bps in fees,")
        print(f"  and a mean markout of {markout.mean} bps on each of two fills,")
        print(f"  so a maker round trip costs about {maker_round_trip:.2f} bps")
        print(f"  against {threshold.round_trip_bps} bps by crossing.")
        print()
        print(
            "  This markout is optimistic: it assumes any aggressive trade at our\n"
            "  level fills us, when a real queue fills us hardest exactly when the\n"
            "  level is about to be cleared. Treat it as a lower bound on adverse\n"
            "  selection — the number to beat, not the number to bank."
        )
    else:
        print()
        print(
            "passive fill markout: not measured. The sample holds no trade at the\n"
            "touch with a quote a horizon later, so nothing here can say whether\n"
            "resting is cheaper than crossing."
        )

    print()
    print(
        "Read these together: if mid routinely moves further over the delay than a\n"
        "round trip costs, the delay is not a tax on the edge — it is larger than the\n"
        "edge needs to be, and that horizon is unreachable from a public feed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
