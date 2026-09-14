#!/usr/bin/env python3
"""Live acceptance verification for Build 0.1 Rev.2 milestones M1 and M2.

Runs the recorder against real public Hyperliquid market data, preserves the
raw frames, tests our parser's assumptions against what actually arrived, and
produces an explicit acceptance decision per milestone.

    python infrastructure/scripts/acceptance_m1_m2.py \
        --minutes 5 --out docs/evidence/build-0.1 \
        --storage-report storage.json --integration-report integration.json

Read-only by construction: the recorder holds no credential, the execution
guard is asserted before connecting, and `market_data_is_read_only` is recorded
in the evidence. A run that finds execution enabled fails outright.

Exits non-zero when either milestone is not accepted. The evidence is written
before the exit code is decided, so a failed run still leaves its evidence
behind — which is the more valuable outcome of the two.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs.config import ConfigurationError, Settings, load_settings  # noqa: E402
from libs.domain.clock import SystemClock  # noqa: E402
from libs.exchange.hyperliquid.subscriptions import RECORDED_CHANNELS  # noqa: E402
from libs.exchange.hyperliquid.websocket import HyperliquidWebSocketSource  # noqa: E402
from libs.observability.logging import configure_logging, get_logger  # noqa: E402
from services.market_data.acceptance import (  # noqa: E402
    AcceptanceReport,
    analyse_latency,
    analyse_schema,
    analyse_users,
    decide_m1,
    decide_m2,
)
from services.market_data.capture import (  # noqa: E402
    CaptureHeader,
    SessionWriter,
    load_session,
)
from services.market_data.recorder import Recorder  # noqa: E402
from services.market_data.replay import verify_determinism  # noqa: E402
from services.market_data.sinks import InMemorySink, RawFrame, Sink  # noqa: E402
from services.market_data.source import IterableSource  # noqa: E402

logger = get_logger("acceptance")

CLOCK_NOTE = (
    "Receipt timestamps come from the runner's system clock; venue timestamps "
    "come from Hyperliquid. The two are not synchronised, so a small constant "
    "offset is possible and negative observations indicate clock disagreement "
    "rather than negative transit. GitHub-hosted runners use NTP but the "
    "offset is unmeasured here."
)


class _OrderedSink:
    """Records the order of writes, to prove raw-before-interpretation.

    Wraps a real sink and appends a marker per call. The proof is an ordering
    property of the live run, so it has to be observed rather than asserted:
    the raw marker for a frame must precede every event marker derived from it.
    """

    def __init__(self, inner: Sink) -> None:
        self.inner = inner
        self.order: list[tuple[str, str]] = []

    async def write_raw(self, frame: RawFrame) -> None:
        self.order.append(("raw", frame.raw_id))
        await self.inner.write_raw(frame)

    async def write_market_events(self, events: tuple[Any, ...]) -> None:
        for event in events:
            self.order.append(("market", event.raw_reference or ""))
        await self.inner.write_market_events(events)

    async def write_trader_events(self, events: tuple[Any, ...]) -> None:
        for event in events:
            self.order.append(("trader", event.raw_reference or ""))
        await self.inner.write_trader_events(events)

    async def write_gap(self, gap: Any) -> None:
        await self.inner.write_gap(gap)

    async def flush(self) -> None:
        await self.inner.flush()

    def raw_first_holds(self) -> tuple[bool, str]:
        """Whether every event marker followed its frame's raw marker."""
        seen_raw: set[str] = set()
        for kind, reference in self.order:
            if kind == "raw":
                seen_raw.add(reference)
                continue
            if not reference:
                return False, "an event carried no raw reference"
            if reference not in seen_raw:
                return (
                    False,
                    f"an event referencing {reference} was written before its raw frame",
                )
        if not seen_raw:
            return False, "no raw frame was written, so the ordering is untested"
        return True, f"verified across {len(seen_raw)} raw frame(s)"


def _command_output(command: list[str]) -> str:
    try:
        return subprocess.run(  # noqa: S603 - fixed argument lists, no shell
            command, capture_output=True, text=True, timeout=60, check=False
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _environment(settings: Settings) -> dict[str, Any]:
    lock = REPO_ROOT / "uv.lock"

    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "uv_version": _command_output(["uv", "--version"]),
        "docker_version": _command_output(["docker", "--version"]),
        "lockfile_sha256": hashlib.sha256(lock.read_bytes()).hexdigest()
        if lock.is_file()
        else "missing",
        "execution": settings.describe(),
        "recorded_channels": list(RECORDED_CHANNELS),
        "asset_allowlist": list(settings.asset_allowlist),
    }


async def _record_live(
    settings: Settings, minutes: float, capture_path: Path
) -> tuple[Recorder, InMemorySink, _OrderedSink, int]:
    """Record from the live venue for `minutes`, capturing every frame."""
    clock = SystemClock()
    memory = InMemorySink()
    ordered = _OrderedSink(memory)

    writer = SessionWriter(
        capture_path,
        CaptureHeader(
            format_version=1,
            venue="hyperliquid",
            source="hyperliquid_ws",
            assets=settings.asset_allowlist,
            channels=RECORDED_CHANNELS,
            started_at=clock.now().isoformat(),
        ),
    )

    class _Capturing:
        async def write_raw(self, frame: RawFrame) -> None:
            writer.write(frame)
            await ordered.write_raw(frame)

        async def write_market_events(self, events: tuple[Any, ...]) -> None:
            await ordered.write_market_events(events)

        async def write_trader_events(self, events: tuple[Any, ...]) -> None:
            await ordered.write_trader_events(events)

        async def write_gap(self, gap: Any) -> None:
            await ordered.write_gap(gap)

        async def flush(self) -> None:
            await ordered.flush()

    source = HyperliquidWebSocketSource(
        url=settings.market_data_endpoint,
        assets=settings.asset_allowlist,
        clock=clock,
    )
    recorder = Recorder(source=source, sink=_Capturing(), clock=clock)  # type: ignore[arg-type]

    with writer:
        try:
            await asyncio.wait_for(recorder.run(), timeout=minutes * 60)
        except TimeoutError:
            await ordered.flush()
        frames_captured = writer.frames_written

    return recorder, memory, ordered, frames_captured


async def _fault_injection() -> dict[str, Any]:
    """Prove a parse failure does not destroy raw evidence.

    Run separately from the live observation and with synthetic input, so a
    deliberately malformed frame never contaminates the live statistics
    (task §7). The claim under test is narrow: a frame that cannot be parsed is
    still archived.
    """
    clock = SystemClock()
    memory = InMemorySink()
    ordered = _OrderedSink(memory)
    payloads = [
        '{"channel":"trades","data":[{"coin":"BTC","side":"B","px":"1","sz":"1","time":1789387199900,"tid":1}]}',
        "this frame cannot be parsed",
        '{"channel":"trades","data":[{"coin":"BTC","side":"ZZ","px":"1","sz":"1","time":1789387199901}]}',
        '{"channel":"trades","data":[{"coin":"BTC","side":"A","px":"2","sz":"1","time":1789387199902,"tid":2}]}',
    ]
    recorder = Recorder(
        source=IterableSource(payloads, clock),
        sink=ordered,  # type: ignore[arg-type]
        clock=clock,
    )
    metrics = await recorder.run()
    raw_first, detail = ordered.raw_first_holds()

    return {
        "note": "synthetic input, run separately from the live observation",
        "frames_submitted": len(payloads),
        "frames_archived": metrics.messages_archived,
        "frames_unusable": metrics.messages_invalid,
        "events_written": metrics.market_events_written,
        "all_frames_archived_despite_failures": metrics.messages_archived == len(payloads),
        "raw_first_ordering_holds": raw_first,
        "raw_first_detail": detail,
        "recorder_still_recording": recorder.machine.state.is_recording,
    }


def _decode_frames(capture_path: Path) -> list[tuple[str, Any]]:
    """Decode captured frames into `(channel, payload)` for analysis."""
    frames: list[tuple[str, Any]] = []
    session = load_session(capture_path)
    for frame in session.frames:
        try:
            payload = json.loads(frame.payload)
        except json.JSONDecodeError:
            frames.append(("<unparseable>", None))
            continue
        channel = payload.get("channel") if isinstance(payload, dict) else None
        frames.append((str(channel) if channel else "<no channel>", payload))
    return frames


def _latency_samples(memory: InMemorySink) -> tuple[dict[str, list[float]], tuple[str, ...]]:
    """Data arrival latency per stream, in milliseconds.

    Only events with a venue timestamp contribute. Streams that publish none —
    `activeAssetCtx` does not — are listed separately rather than pooled with
    those that do, because averaging them would describe nothing (task §8).
    """
    samples: dict[str, list[float]] = {}
    without: set[str] = set()
    for event in memory.market_events:
        stream = event.event_type.value
        delay = event.timestamps.source_to_receive_seconds
        if delay is None:
            without.add(stream)
            continue
        samples.setdefault(stream, []).append(delay * 1000)
    return samples, tuple(sorted(without - set(samples)))


def _stream_health(recorder: Recorder, memory: InMemorySink) -> dict[str, Any]:
    metrics = recorder.metrics
    per_stream: dict[str, dict[str, Any]] = {}
    for event in memory.market_events:
        entry = per_stream.setdefault(
            event.event_type.value,
            {"events": 0, "first_receipt": None, "last_receipt": None},
        )
        entry["events"] += 1
        moment = event.timestamps.local_receive_time.isoformat()
        if entry["first_receipt"] is None:
            entry["first_receipt"] = moment
        entry["last_receipt"] = moment

    for stream, entry in per_stream.items():
        first, last = entry["first_receipt"], entry["last_receipt"]
        if first and last and first != last:
            span = (datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds()
            entry["events_per_second"] = round(entry["events"] / span, 4) if span else None
        else:
            entry["events_per_second"] = None
        del stream

    proven = [gap for gap in memory.gaps if not gap.suspected]
    suspected = [gap for gap in memory.gaps if gap.suspected]

    return {
        "connection_attempts": getattr(recorder.source, "attempts", None),
        "disconnects": 1 if getattr(recorder.source, "disconnected_at", None) else 0,
        "final_state": recorder.machine.state.value,
        "state_transitions": [
            {"from": t.previous.value, "to": t.current.value, "reason": t.reason}
            for t in recorder.machine.history
        ],
        "heartbeat_messages": recorder.heartbeat.messages,
        "heartbeat_last_data_at": (
            recorder.heartbeat.last_data_at.isoformat() if recorder.heartbeat.last_data_at else None
        ),
        "per_stream": per_stream,
        "metrics": metrics.as_dict(),
        "duplicates": {
            "dropped": metrics.duplicates_dropped,
            "tracked_keys": recorder.dedup.tracked,
        },
        "gaps": {
            "proven": len(proven),
            "suspected_silence": len(suspected),
            "detail": [
                {
                    "kind": gap.kind.value,
                    "asset": gap.asset,
                    "event_type": gap.event_type,
                    "suspected": gap.suspected,
                    "missing_count": gap.missing_count,
                    "reason": gap.detection_reason,
                }
                for gap in memory.gaps[:20]
            ],
        },
        "failures": {
            "parse": metrics.messages_invalid,
            "quality_invalid": metrics.quality_invalid,
            "quality_warning": metrics.quality_warning,
            "persistence": metrics.persist_failures,
        },
    }


def _load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    file = Path(path)
    if not file.is_file():
        return {"error": f"{path} does not exist"}
    try:
        loaded = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"error": f"{path} is not valid JSON: {exc}"}
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _m1_store_results(storage: dict[str, Any]) -> dict[str, bool]:
    """Extract per-store pass/fail from `verify_stack.py --json` output.

    A store that is absent from the report counts as failed, not as passing:
    an unreported store is an unverified one.
    """
    required = ("postgres", "clickhouse", "redis", "object_store")
    reported = {
        str(entry.get("store")): str(entry.get("status")) == "HEALTHY"
        for entry in storage.get("stores", [])
        if isinstance(entry, dict)
    }
    return {name: reported.get(name, False) for name in required}


async def run(args: argparse.Namespace) -> int:
    configure_logging("WARNING", stream=sys.stderr)
    started = datetime.now(UTC)

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"configuration refused: {exc}", file=sys.stderr)
        return 2

    # Safety gate, before any network activity. A run that could reach capital
    # is not a market-data verification and must not proceed.
    if settings.may_submit_orders or settings.execution_environment.reaches_real_capital:
        print(
            "refusing to run: execution is enabled or the execution environment "
            "can reach real capital. This is a read-only market-data verification.",
            file=sys.stderr,
        )
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    capture_path = out / "live-btc-capture.jsonl"

    live: dict[str, Any] = {
        "requested_minutes": args.minutes,
        "endpoint": settings.market_data_endpoint,
        "market_data_environment": settings.market_data_environment.value,
        "read_only_invariant_holds": settings.market_data_is_read_only,
    }

    recorder = None
    memory = InMemorySink()
    ordered: _OrderedSink | None = None
    frames_captured = 0

    try:
        recorder, memory, ordered, frames_captured = await _record_live(
            settings, args.minutes, capture_path
        )
    except Exception as exc:
        live["error"] = f"{type(exc).__name__}: {exc}"
        logger.exception("live_recording_failed")

    # Derived from evidence, not from the absence of an exception. The source's
    # retry loop swallows connection failures by design, so a run that never
    # reached the venue completes without raising — and reporting that as
    # "connected" would claim a connection we never had.
    source = getattr(recorder, "source", None)
    successes = getattr(source, "successful_connections", 0)
    live["connected"] = successes > 0
    live["successful_connections"] = successes
    live["connection_attempts"] = getattr(source, "attempts", 0)
    live["subscriptions_sent"] = getattr(source, "subscriptions_sent", 0)
    if getattr(source, "last_error", None):
        live["last_connection_error"] = source.last_error  # type: ignore[union-attr]

    live["frames_captured"] = frames_captured
    live["capture_path"] = str(capture_path)

    decoded = _decode_frames(capture_path) if capture_path.is_file() else []
    schema = analyse_schema(decoded, expected_channels=RECORDED_CHANNELS)
    users = analyse_users(decoded)
    samples, without_timestamp = _latency_samples(memory)
    latency = analyse_latency(
        samples, streams_without_venue_timestamp=without_timestamp, clock_note=CLOCK_NOTE
    )

    raw_first, raw_first_detail = (
        ordered.raw_first_holds() if ordered is not None else (False, "no live run")
    )
    live["raw_first_ordering"] = {"holds": raw_first, "detail": raw_first_detail}

    replay: dict[str, Any] = {"checked": False}
    replay_deterministic: bool | None = None
    if frames_captured > 0:
        session = load_session(capture_path)
        if session.frames:
            comparison = await verify_determinism(session)
            replay_deterministic = comparison.identical
            replay = {
                "checked": True,
                "identical": comparison.identical,
                "events_compared": comparison.first_count,
                "divergence": comparison.first_divergence,
                "excluded_fields": ["event_id", "raw_reference"],
                "exclusion_rationale": (
                    "event_id is generated per run and raw_reference points at "
                    "the archive row written this run; neither is part of what "
                    "the event asserts about the market. Every other field is "
                    "compared."
                ),
                "synthetic_receipts": session.synthetic_receipts,
            }

    fault = await _fault_injection()

    storage = _load_json(args.storage_report)
    integration = _load_json(args.integration_report)
    integration_passed = integration.get("passed")

    m1 = decide_m1(
        store_results=_m1_store_results(storage),
        integration_passed=None if integration_passed is None else bool(integration_passed),
    )

    trader_events = len(memory.trader_events)
    m2 = decide_m2(
        schema=schema,
        users=users,
        latency=latency,
        raw_first_proven=raw_first,
        replay_deterministic=replay_deterministic,
        events_written=len(memory.market_events),
        frames_received=frames_captured,
        persistence_failures=recorder.metrics.persist_failures if recorder else 0,
        execution_enabled=settings.may_submit_orders,
        minimum_frames=args.minimum_frames,
    )

    report = AcceptanceReport(
        commit_sha=args.commit or _command_output(["git", "rev-parse", "HEAD"]),
        workflow_run_id=args.run_id,
        started_at=started,
        finished_at=datetime.now(UTC),
        environment=_environment(settings),
        m1=m1,
        m2=m2,
        storage=storage,
        migrations=_load_json(args.migration_report),
        integration=integration,
        live=live | ({"stream_health": _stream_health(recorder, memory)} if recorder else {}),
        schema=schema,
        users=users,
        latency=latency,
        replay=replay,
        fault_injection=fault,
    )
    report.live["trader_events_written"] = trader_events

    (out / "m1-m2-acceptance.json").write_text(report.to_json(), encoding="utf-8")
    (out / "m1-m2-acceptance.md").write_text(report.to_markdown(), encoding="utf-8")

    print(report.to_markdown())
    print(f"\nevidence written to {out}", file=sys.stderr)

    return 0 if report.both_accepted else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=5.0)
    parser.add_argument("--out", default="docs/evidence/build-0.1")
    parser.add_argument("--storage-report", help="verify_stack.py --json output")
    parser.add_argument("--migration-report", help="migration output as JSON")
    parser.add_argument("--integration-report", help='{"passed": true/false, ...}')
    parser.add_argument("--commit", help="commit SHA under verification")
    parser.add_argument("--run-id", help="CI workflow run id")
    parser.add_argument(
        "--minimum-frames",
        type=int,
        default=50,
        help="below this the live observation is inconclusive rather than accepted",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
