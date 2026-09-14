#!/usr/bin/env python3
"""Build a BTC research dataset (M4).

    python -m services.research.cli --hours 24
    python -m services.research.cli --from 2026-09-14T21:00:00Z --to 2026-09-14T22:00:00Z

Reads recorded events from ClickHouse, writes them as Parquet, and records the
manifest in PostgreSQL. The manifest is written last: a dataset nobody can find
is recoverable, a manifest pointing at a file that was never written is not.

Exits non-zero when the dataset is not usable for training, so a pipeline
cannot proceed on one by accident. That is not the same as failing — the
dataset and its manifest are still written, because a range with a gap in it is
a fact worth recording rather than an error to discard.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from libs.config import load_settings
from libs.domain.clock import SystemClock
from libs.observability.logging import configure_logging, get_logger
from libs.storage import clickhouse as ch
from libs.storage import postgres as pg
from services.research import store
from services.research.dataset import DatasetSpec, build_dataset
from services.research.writer import write_parquet

logger = get_logger("research.dataset")

DEFAULT_OUTPUT = Path("research/datasets")


def _moment(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(f"{value!r} has no timezone; use a trailing Z for UTC")
    return parsed.astimezone(UTC)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="BTC")
    parser.add_argument("--hours", type=float, help="Build the last N hours, ending now.")
    parser.add_argument("--from", dest="start", type=_moment, help="Range start, inclusive.")
    parser.add_argument("--to", dest="end", type=_moment, help="Range end, exclusive.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--include-warnings",
        action="store_true",
        help="Admit WARNING rows as well as VALID. Recorded in the manifest.",
    )
    args = parser.parse_args()

    configure_logging()
    settings = load_settings()
    clock = SystemClock()

    if args.hours is not None:
        end = clock.now()
        start = end - timedelta(hours=args.hours)
    elif args.start is not None and args.end is not None:
        start, end = args.start, args.end
    else:
        parser.error("give either --hours, or both --from and --to")

    from libs.schemas.enums import DataQualityStatus  # noqa: PLC0415 - CLI-local

    quality = (DataQualityStatus.VALID, DataQualityStatus.WARNING)
    spec = DatasetSpec(
        asset=args.asset,
        range_start=start,
        range_end=end,
        quality_filter=quality if args.include_warnings else (DataQualityStatus.VALID,),
    )

    with (
        ch.connect_from_settings(settings) as client,
        pg.connect(settings.postgres_dsn) as connection,
    ):
        manifest = build_dataset(
            spec,
            fetch_rows=lambda s: store.fetch_rows(client, s),
            fetch_gaps=lambda s: store.fetch_gaps(connection, s),
            write=lambda rows, dataset_id: write_parquet(rows, dataset_id, directory=args.out),
            now=clock.now(),
        )
        store.record_manifest(connection, manifest)

    print(f"dataset_id     {manifest.dataset_id}")
    print(f"rows           {manifest.row_count}")
    print(f"range          {manifest.range_start.isoformat()} -> {manifest.range_end.isoformat()}")
    print(f"quality        {manifest.quality_status.value}")
    print(f"pit            {manifest.pit_status.value}")
    print(f"checksum       {manifest.checksum}")
    print(f"storage        {manifest.storage_uri}")
    print(f"gaps in range  {len(manifest.known_gap_ids)}")
    for key, value in sorted(manifest.quality_summary.items()):
        print(f"  {key}: {value}")

    if not manifest.usable_for_training:
        print(
            "\nNOT USABLE FOR TRAINING. The dataset and its manifest were written; "
            "the summary above says why it may not be used.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
