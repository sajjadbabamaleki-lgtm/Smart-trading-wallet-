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

from libs.config import load_settings
from libs.domain.clock import SystemClock
from libs.observability.logging import configure_logging
from libs.storage import clickhouse as ch
from services.research.costs import BASE_MAKER_FEE_BPS as MAKER_FEE_BPS
from services.research.costs import MEASURED_DATA_ARRIVAL_FLOOR_MS, CostModel, hurdle
from services.research.dataset import DatasetSpec
from services.research.measure import calibrate
from services.research.store import fetch_rows

REFERENCE_PRICE = Decimal(60000)
"""Only to express the hurdle as a price move.

A round-trip cost in basis points is the real quantity and is
price-independent; this turns it into something a person can picture.
Nothing is computed from it.
"""


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
    args = parser.parse_args()

    configure_logging()
    settings = load_settings()
    end = SystemClock().now()
    spec = DatasetSpec(
        asset=args.asset,
        range_start=end - timedelta(hours=args.hours),
        range_end=end,
        data_types=("BBO", "L2_SNAPSHOT"),
    )

    with ch.connect_from_settings(settings) as client:
        rows = fetch_rows(client, spec)

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
