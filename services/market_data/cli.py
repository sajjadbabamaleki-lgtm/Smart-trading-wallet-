"""Run the recorder.

    python -m services.market_data.cli --dry-run --minutes 5
    python -m services.market_data.cli --dry-run --minutes 5 --capture OUT.jsonl
    python -m services.market_data.cli --replay FILE
    python -m services.market_data.cli --replay FILE --determinism

`--dry-run` records from the live feed into memory and prints the metrics. It is
the cheapest way to answer the question M2 has to answer: does the venue send
what we think it sends? Nothing is written to a store, so it runs before the
stores exist.

`--capture` additionally writes the session to a capture file. That file is the
point of the exercise: it turns one live run into a permanent, replayable
fixture, so every later change can be tested against what the venue actually
sent rather than against what we assumed it would.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs.config import ConfigurationError, Settings, load_settings  # noqa: E402
from libs.domain.clock import SystemClock  # noqa: E402
from libs.exchange.hyperliquid.subscriptions import (  # noqa: E402
    MAINNET_WS_URL,
    RECORDED_CHANNELS,
    TESTNET_WS_URL,
)
from libs.exchange.hyperliquid.websocket import HyperliquidWebSocketSource  # noqa: E402
from libs.observability.logging import configure_logging, get_logger  # noqa: E402
from libs.schemas.enums import ExecutionEnvironment  # noqa: E402
from services.market_data.capture import (  # noqa: E402
    CaptureHeader,
    SessionWriter,
    load_session,
)
from services.market_data.monitor import Monitor  # noqa: E402
from services.market_data.recorder import Recorder  # noqa: E402
from services.market_data.registry import InMemoryGapRegistry  # noqa: E402
from services.market_data.replay import (  # noqa: E402
    ReplayEngine,
    ReplayReport,
    verify_determinism,
)
from services.market_data.sinks import InMemorySink, RawFrame, Sink  # noqa: E402
from services.market_data.source import MessageSource  # noqa: E402

logger = get_logger("recorder")


@dataclass
class _CapturingSink:
    """Wraps a sink, also writing every raw frame to a capture file.

    Capture happens here rather than inside the recorder because capturing is a
    property of this run, not of the pipeline. The recorder stays unaware of it,
    which is what keeps a captured session a faithful record of a normal run
    rather than of a run in capture mode.
    """

    inner: Sink
    writer: SessionWriter

    async def write_raw(self, frame: RawFrame) -> None:
        self.writer.write(frame)
        await self.inner.write_raw(frame)

    async def write_market_events(self, events: tuple[Any, ...]) -> None:
        await self.inner.write_market_events(events)

    async def write_trader_events(self, events: tuple[Any, ...]) -> None:
        await self.inner.write_trader_events(events)

    async def write_gap(self, gap: Any) -> None:
        await self.inner.write_gap(gap)

    async def flush(self) -> None:
        await self.inner.flush()


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


async def _replay(path: Path, args: argparse.Namespace) -> int:
    """Replay a capture on its own clock and report.

    Delegates to `ReplayEngine`, which is the same code the determinism tests
    and `verify_replay.py` use — a CLI that replayed differently would prove
    nothing about either.
    """
    configure_logging("WARNING", stream=sys.stderr)
    session = load_session(path)
    if not session.frames:
        print(f"{path} contains no replayable frames", file=sys.stderr)
        return 2

    result = await ReplayEngine(session).run()
    report = ReplayReport(result=result)
    if session.synthetic_receipts:
        report.findings.append(
            "receipt times were synthesized from venue timestamps; any "
            "latency figure from this session is an artifact, not a measurement"
        )
    if args.determinism:
        report.comparison = await verify_determinism(session)

    print(json.dumps(report.as_dict(), indent=2))

    if report.comparison is not None and not report.comparison.identical:
        print(report.comparison.render(), file=sys.stderr)
        return 1
    return 0


async def run(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"configuration refused: {exc}", file=sys.stderr)
        return 2

    # Logs to stderr, so stdout carries only the report. Mixing them made the
    # JSON output unparseable — a --json flag that cannot be piped into a JSON
    # reader is not a machine-readable interface.
    configure_logging(settings.log_level, stream=sys.stderr)
    clock = SystemClock()

    # Replay takes a different path, and deliberately so: it must run on the
    # session's clock, not this machine's. Driving the monitor from a
    # SystemClock during a replay produced negative staleness figures — "how
    # old is this data" measured against the wrong present. A fabricated
    # freshness number in a report is exactly the kind of plausible-looking
    # wrongness this project keeps guarding against.
    if args.replay:
        return await _replay(Path(args.replay), args)

    source: MessageSource = HyperliquidWebSocketSource(
        url=websocket_url(settings),
        assets=settings.asset_allowlist,
        clock=clock,
    )

    sink = InMemorySink()
    if not args.dry_run:
        print(
            "writing to the stores is not wired into the CLI yet; use --dry-run or --replay",
            file=sys.stderr,
        )
        return 2

    capture_writer: SessionWriter | None = None
    if args.capture:
        capture_writer = SessionWriter(
            Path(args.capture),
            CaptureHeader(
                format_version=1,
                venue="hyperliquid",
                source=source.name,
                assets=settings.asset_allowlist,
                channels=RECORDED_CHANNELS,
                started_at=clock.now().isoformat(),
            ),
        )

    registry = InMemoryGapRegistry()
    recording_sink: Sink = sink if capture_writer is None else _CapturingSink(sink, capture_writer)
    recorder = Recorder(source=source, sink=recording_sink, clock=clock)
    monitor = Monitor(
        clock=clock,
        gaps=recorder.gaps,
        heartbeat=recorder.heartbeat,
        machine=recorder.machine,
        staleness_limit=timedelta(seconds=settings.data_staleness_limit_seconds),
        on_gap=registry.register,
    )

    logger.info(
        "recorder_starting",
        extra={
            "environment": settings.execution_environment.value,
            "assets": list(settings.asset_allowlist),
            "source": source.name,
            "sink": "memory",
        },
    )

    stop = asyncio.Event()
    monitor_task = asyncio.create_task(monitor.run(stop=stop))

    try:
        if capture_writer is not None:
            capture_writer.__enter__()
        if args.minutes:
            try:
                metrics = await asyncio.wait_for(recorder.run(), timeout=args.minutes * 60)
            except TimeoutError:
                metrics = recorder.metrics
                await sink.flush()
        else:
            metrics = await recorder.run()
    finally:
        stop.set()
        await monitor_task
        if capture_writer is not None:
            capture_writer.__exit__()

    report: dict[str, Any] = {
        "state": recorder.machine.state.value,
        "metrics": metrics.as_dict(),
        "freshness": None if monitor.last_check is None else monitor.last_check.freshness.as_dict(),
        "gaps": (await registry.summary()).as_dict(),
        "dedup": {
            "tracked": recorder.dedup.tracked,
            "duplicates": recorder.dedup.stats.duplicates,
        },
        "streams": [f"{asset}/{event_type}" for asset, event_type in recorder.gaps.streams],
        "channels_seen": sorted({frame.channel for frame in sink.raw}),
    }
    if capture_writer is not None:
        report["capture"] = {
            "path": args.capture,
            "frames_written": capture_writer.frames_written,
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
    parser.add_argument("--capture", help="also write the session to this capture file")
    parser.add_argument(
        "--determinism",
        action="store_true",
        help="with --replay, replay twice and verify the runs are identical",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
