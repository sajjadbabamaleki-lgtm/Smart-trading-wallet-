"""Run the recorder.

    python -m services.market_data.cli --minutes 5        # live, to the stores
    python -m services.market_data.cli --replay FILE      # fixture, in memory
    python -m services.market_data.cli --dry-run          # live, in memory

`--dry-run` records from the live feed into memory and prints the metrics. It is
the cheapest way to answer the question M2 actually has to answer: does the
venue send what we think it sends? Nothing is written, so it can be run before
the stores exist.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs.config import ConfigurationError, Settings, load_settings  # noqa: E402
from libs.domain.clock import SystemClock  # noqa: E402
from libs.exchange.hyperliquid.subscriptions import (  # noqa: E402
    MAINNET_WS_URL,
    TESTNET_WS_URL,
)
from libs.exchange.hyperliquid.websocket import HyperliquidWebSocketSource  # noqa: E402
from libs.observability.logging import configure_logging, get_logger  # noqa: E402
from libs.schemas.enums import ExecutionEnvironment  # noqa: E402
from services.market_data.recorder import Recorder  # noqa: E402
from services.market_data.sinks import InMemorySink  # noqa: E402
from services.market_data.source import FixtureSource, MessageSource  # noqa: E402

logger = get_logger("recorder")


def websocket_url(settings: Settings) -> str:
    """Endpoint for the configured environment.

    Derived, never configured — the same rule as the REST endpoint
    (Build 0.1 Rev.1 §46). DEVELOPMENT has no venue of its own, so it reads the
    testnet feed: recording public market data carries no capital risk, and
    refusing to read it would make the recorder untestable in the one
    environment it is meant to be developed in.
    """
    if settings.execution_environment in (
        ExecutionEnvironment.DEVELOPMENT,
        ExecutionEnvironment.TESTNET,
    ):
        return TESTNET_WS_URL
    raise ConfigurationError(
        f"no market-data endpoint is permitted for "
        f"{settings.execution_environment.value} at this build stage "
        f"(mainnet would be {MAINNET_WS_URL})"
    )


async def run(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"configuration refused: {exc}", file=sys.stderr)
        return 2

    configure_logging(settings.log_level)
    clock = SystemClock()

    source: MessageSource
    if args.replay:
        source = FixtureSource(Path(args.replay), clock)
    else:
        source = HyperliquidWebSocketSource(
            url=websocket_url(settings),
            assets=settings.asset_allowlist,
            clock=clock,
        )

    sink = InMemorySink()
    if not args.dry_run and not args.replay:
        print(
            "writing to the stores is not wired into the CLI yet; use --dry-run or --replay",
            file=sys.stderr,
        )
        return 2

    recorder = Recorder(source=source, sink=sink, clock=clock)

    logger.info(
        "recorder_starting",
        extra={
            "environment": settings.execution_environment.value,
            "assets": list(settings.asset_allowlist),
            "source": source.name,
            "sink": "memory",
        },
    )

    if args.minutes:
        try:
            metrics = await asyncio.wait_for(recorder.run(), timeout=args.minutes * 60)
        except TimeoutError:
            metrics = recorder.metrics
            await sink.flush()
    else:
        metrics = await recorder.run()

    report = {
        "state": recorder.machine.state.value,
        "metrics": metrics.as_dict(),
        "dedup": {
            "tracked": recorder.dedup.tracked,
            "duplicates": recorder.dedup.stats.duplicates,
        },
        "streams": [f"{asset}/{event_type}" for asset, event_type in recorder.gaps.streams],
        "channels_seen": sorted({frame.channel for frame in sink.raw}),
    }
    print(json.dumps(report, indent=2))

    # A run that received frames but normalized nothing means the venue is
    # sending something we do not understand — the single most important
    # failure for this milestone to surface rather than hide.
    if metrics.messages_received > 0 and metrics.market_events_written == 0:
        print(
            "received frames but wrote no events; the message shapes do not "
            "match what the parser expects",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", help="replay a fixture file instead of connecting")
    parser.add_argument("--dry-run", action="store_true", help="record to memory, write nothing")
    parser.add_argument("--minutes", type=float, default=0, help="stop after this many minutes")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
