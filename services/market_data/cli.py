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
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs.config import ConfigurationError, Settings, load_settings  # noqa: E402
from libs.domain.clock import SystemClock  # noqa: E402
from libs.exchange.hyperliquid.subscriptions import RECORDED_CHANNELS  # noqa: E402
from libs.exchange.hyperliquid.websocket import HyperliquidWebSocketSource  # noqa: E402
from libs.observability.logging import configure_logging, get_logger  # noqa: E402
from libs.storage import clickhouse as ch  # noqa: E402
from libs.storage import object_store as obj  # noqa: E402
from libs.storage import postgres as pg  # noqa: E402
from services.market_data.capture import (  # noqa: E402
    CaptureHeader,
    SessionWriter,
    load_session,
)
from services.market_data.monitor import Monitor  # noqa: E402
from services.market_data.reconcile import reconcile  # noqa: E402
from services.market_data.recorder import Recorder, RecorderMetrics  # noqa: E402
from services.market_data.registry import PersistingGapRegistry  # noqa: E402
from services.market_data.replay import (  # noqa: E402
    ReplayEngine,
    ReplayReport,
    verify_determinism,
)
from services.market_data.sinks import InMemorySink, RawFrame, Sink  # noqa: E402
from services.market_data.source import MessageSource  # noqa: E402
from services.market_data.store_sinks import StoreSink  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from clickhouse_connect.driver.client import Client

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


@dataclass
class _ChannelWatcher:
    """Wraps a sink and notes which channels delivered anything.

    The report used to derive this by reading the frames back out of the
    in-memory sink. A sink that writes to a store does not keep them — nor
    should it — so the fact is observed on the way past instead, and the report
    means the same thing whether the run persisted or not.
    """

    inner: Sink
    channels: set[str] = field(default_factory=set)

    async def write_raw(self, frame: RawFrame) -> None:
        self.channels.add(frame.channel)
        await self.inner.write_raw(frame)

    async def write_market_events(self, events: tuple[Any, ...]) -> None:
        await self.inner.write_market_events(events)

    async def write_trader_events(self, events: tuple[Any, ...]) -> None:
        await self.inner.write_trader_events(events)

    async def write_gap(self, gap: Any) -> None:
        await self.inner.write_gap(gap)

    async def flush(self) -> None:
        await self.inner.flush()


@dataclass(frozen=True)
class _Destination:
    """Where a run writes, and what it needs to check itself afterwards.

    The ClickHouse client is carried alongside the sink rather than dug back
    out of it: the reconciliation has to read from the same connection the run
    wrote through, and a sink's job is to write, not to be queried.
    """

    sink: Sink
    stack: ExitStack | None
    clickhouse: Client | None


def _open_sink(settings: Settings, *, clock: SystemClock, dry_run: bool) -> _Destination:
    """The recorder's destination, and the connections it owns.

    Persisting or not is the only difference between the two modes: both run the
    same recorder over the same source, so a --dry-run proves nothing about the
    store path and never did. Until this existed the recorder had never written
    a row anywhere and `store_sinks.py` had no caller at all, which is why M2's
    acceptance covered parsing, normalization and latency but not persistence.

    The returned stack owns three connections and must be closed by the caller,
    after the sink is flushed.
    """
    if dry_run:
        return _Destination(sink=InMemorySink(), stack=None, clickhouse=None)
    stack = ExitStack()
    client = stack.enter_context(ch.connect_from_settings(settings))
    return _Destination(
        sink=StoreSink(
            clickhouse=client,
            object_store=stack.enter_context(obj.connect_from_settings(settings)),
            postgres=stack.enter_context(pg.connect(settings.postgres_dsn)),
            bucket=settings.object_store_bucket,
            clock=clock,
        ),
        stack=stack,
        clickhouse=client,
    )


def _reconcile_against_store(
    destination: _Destination, recorder: Recorder, metrics: RecorderMetrics
) -> dict[str, object] | None:
    """Ask the store whether it holds what the run reported writing.

    Returns None for a dry run, which wrote nothing and has nothing to check.

    A failure to run the check is recorded rather than swallowed: "could not
    check" and "checked and agreed" are different states, and collapsing them
    is how a recorder that loses rows stays green.
    """
    if destination.clickhouse is None or not recorder.stream_start or not recorder.stream_end:
        return None
    try:
        checked = reconcile(
            destination.clickhouse,
            reported=metrics.market_events_written,
            range_start=recorder.stream_start,
            range_end=recorder.stream_end,
        )
    except Exception as exc:
        logger.exception("reconciliation_failed")
        return {"checked": False, "error": str(exc)}
    if not checked.agrees:
        logger.error("reconciliation_mismatch", extra=checked.as_dict())
    return {"checked": True, **checked.as_dict()}


def websocket_url(settings: Settings) -> str:
    """Market-data endpoint for the configured market-data environment.

    Derived from `market_data_environment`, never configured, and deliberately
    independent of `execution_environment` (ADR-009). Reading a public order
    book carries no capital risk; the execution guard is unaffected by what
    this returns, and `market_data_is_read_only` asserts that rather than
    assuming it.
    """
    if not settings.market_data_is_read_only:
        # Naming the fix is part of the refusal. The first time this fired it
        # was correct and unactionable: the recorder stopped, systemd exhausted
        # its start limit, and the message said what was wrong without saying
        # what to change. Thirty-nine hours of silence followed.
        raise ConfigurationError(
            "refusing to start the recorder: the execution guard reports that "
            "capital could be reached in this configuration, so a market-data "
            "read is no longer provably risk-free. The recorder only reads, so "
            "give it a configuration that cannot trade rather than relaxing the "
            "guard: STW_EXECUTION_ENVIRONMENT=DEVELOPMENT, "
            "STW_TRADING_ENABLED=false, and no testnet key. The systemd unit "
            "sets exactly these, so `make record-install` fixes this; only a "
            "recorder started by hand from a trading .env sees it."
        )
    return settings.market_data_endpoint


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

    destination = _open_sink(settings, clock=clock, dry_run=args.dry_run)
    sink, stack = destination.sink, destination.stack
    reconciliation: dict[str, object] | None = None

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

    watcher = _ChannelWatcher(
        sink if capture_writer is None else _CapturingSink(sink, capture_writer)
    )
    recording_sink: Sink = watcher
    # Through the same sink the recorder writes to, so a silence the monitor
    # notices lands in `data_gaps` while the run is still going. The monitor is
    # the only thing that can see a stopped stream, and a gap it only held in
    # memory was lost with every run that was killed rather than stopped.
    registry = PersistingGapRegistry(sink=recording_sink)
    recorder = Recorder(source=source, sink=recording_sink, clock=clock)
    monitor = Monitor(
        clock=clock,
        gaps=recorder.gaps,
        heartbeat=recorder.heartbeat,
        machine=recorder.machine,
        staleness_limit=timedelta(seconds=settings.data_staleness_limit_seconds),
        on_gap=registry.register,
        on_resume=registry.resume,
    )

    logger.info(
        "recorder_starting",
        extra={
            "execution_environment": settings.execution_environment.value,
            "market_data_environment": settings.market_data_environment.value,
            "market_data_endpoint": settings.market_data_endpoint,
            "execution_enabled": settings.may_submit_orders,
            "assets": list(settings.asset_allowlist),
            "source": source.name,
            "sink": "memory" if args.dry_run else "stores",
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
        # Flush before the connections close. Batched writes are the point of
        # StoreSink, and an unflushed batch is data the recorder observed,
        # reported in its metrics, and never persisted — the exact discrepancy
        # this project would otherwise discover much later from a dataset that
        # is short of what the run claims to have seen.
        await recording_sink.flush()
        if capture_writer is not None:
            capture_writer.__exit__()
        # Reconcile before the connections close, and before the exit code is
        # decided. A run that persisted must be able to say that what it
        # reported writing is what the store actually holds; without it, a
        # recorder losing rows is indistinguishable from a quiet market.
        reconciliation = _reconcile_against_store(destination, recorder, metrics)
        if stack is not None:
            stack.close()

    report: dict[str, Any] = {
        "settings": settings.describe(),
        "state": recorder.machine.state.value,
        "metrics": metrics.as_dict(),
        "freshness": None if monitor.last_check is None else monitor.last_check.freshness.as_dict(),
        "gaps": {
            **(await registry.summary()).as_dict(),
            # Detected and held, but refused by the store. Non-zero means the
            # registry in PostgreSQL is short of what this run actually saw.
            "persist_failures": registry.persist_failures,
        },
        "dedup": {
            "tracked": recorder.dedup.tracked,
            "duplicates": recorder.dedup.stats.duplicates,
        },
        "streams": [f"{asset}/{event_type}" for asset, event_type in recorder.gaps.streams],
        "persisted": not args.dry_run,
        "reconciliation": reconciliation,
        "channels_seen": sorted(watcher.channels),
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
