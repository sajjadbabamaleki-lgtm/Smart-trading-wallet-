#!/usr/bin/env python3
"""Verify replay determinism and produce M3's evidence artifacts.

Build 0.1 Rev.1 §77 asks two things of replay: that recorded events can be
replayed deterministically, and that replay does not depend on real wall-clock
time. §36 adds that screenshots are not evidence — automated logs and tests are.
This script is how those claims are checked and written down.

    python infrastructure/scripts/verify_replay.py CAPTURE...          # text
    python infrastructure/scripts/verify_replay.py CAPTURE --json      # machine-readable
    python infrastructure/scripts/verify_replay.py CAPTURE --out DIR   # write artifacts

Exits non-zero if any capture replays non-deterministically, so it can gate a
later milestone.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs.observability.logging import configure_logging  # noqa: E402
from libs.schemas.enums import DataQualityStatus  # noqa: E402
from services.market_data.capture import CaptureError, load_session  # noqa: E402
from services.market_data.replay import (  # noqa: E402
    ReplayEngine,
    ReplayReport,
    verify_determinism,
)


def _quality_breakdown(report: ReplayReport) -> dict[str, int]:
    counts = dict.fromkeys((status.value for status in DataQualityStatus), 0)
    for event in report.result.market_events:
        counts[event.quality_status.value] += 1
    return counts


async def _examine(path: Path) -> tuple[ReplayReport, bool]:
    session = load_session(path)
    if not session.frames:
        raise CaptureError(f"{path} contains no replayable frames")

    comparison = await verify_determinism(session)
    result = await ReplayEngine(session).run()
    report = ReplayReport(result=result, comparison=comparison)

    if session.malformed_lines:
        report.findings.append(
            f"{len(session.malformed_lines)} unreadable line(s): "
            f"{', '.join(str(number) for number in session.malformed_lines[:10])}"
        )
    if result.metrics.messages_received and not result.metrics.market_events_written:
        report.findings.append(
            "frames were received but no events were written — the message "
            "shapes do not match what the parser expects"
        )
    if result.metrics.messages_invalid:
        report.findings.append(f"{result.metrics.messages_invalid} frame(s) could not be used")
    if result.metrics.quality_invalid:
        report.findings.append(
            f"{result.metrics.quality_invalid} event(s) failed validation (recorded, not discarded)"
        )
    if result.gaps:
        report.findings.append(f"{len(result.gaps)} gap(s) detected during replay")

    return report, comparison.identical


def _render(path: Path, report: ReplayReport) -> str:
    data = report.as_dict()
    metrics = data["recorder"]["metrics"]
    lines = [
        f"capture        {path.name}",
        f"frames         {data['capture']['frames']} over {data['capture']['duration_seconds']}s",
    ]
    header = data["capture"]["header"]
    if header:
        lines.append(
            f"session        {header['venue']} "
            f"{'/'.join(header['assets'])} — {header['recorder_version']}"
        )
    else:
        lines.append("session        no capture header (hand-written fixture?)")

    determinism = data["determinism"]
    verdict = "deterministic" if determinism and determinism["identical"] else "DIVERGED"
    lines += [
        f"replay         {verdict} over {determinism['events_compared']} events"
        if determinism
        else "replay         not compared",
        f"events         {data['events']['market']} market, "
        f"{data['events']['trader']} trader, {data['events']['gaps']} gaps",
        "quality        "
        + ", ".join(
            f"{status.lower()}={count}"
            for status, count in _quality_breakdown(report).items()
            if count
        ),
        f"frames used    {metrics['messages_parsed']} parsed, "
        f"{metrics['messages_invalid']} unusable, "
        f"{metrics['duplicates_dropped']} duplicates dropped",
        f"final state    {data['recorder']['final_state']}",
    ]
    if determinism and not determinism["identical"]:
        lines.append(f"divergence     {determinism['divergence']}")
    for finding in data["findings"]:
        lines.append(f"  finding      {finding}")
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    # The recorder logs as it replays. Those lines go to stderr so stdout
    # carries only the report, which --json promises is machine-readable.
    configure_logging("WARNING", stream=sys.stderr)

    reports: dict[str, dict[str, Any]] = {}
    deterministic = True

    for raw_path in args.captures:
        path = Path(raw_path)
        try:
            report, identical = await _examine(path)
        except CaptureError as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            return 2
        deterministic = deterministic and identical
        payload = report.as_dict()
        payload["quality_breakdown"] = _quality_breakdown(report)
        reports[str(path)] = payload
        if not args.json:
            print(_render(path, report))
            print()

    if args.json:
        print(json.dumps({"captures": reports, "deterministic": deterministic}, indent=2))

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "replay-determinism-test.json").write_text(
            json.dumps({"captures": reports, "deterministic": deterministic}, indent=2),
            encoding="utf-8",
        )
        quality = {name: payload["quality_breakdown"] for name, payload in reports.items()}
        (out / "data-quality-report.json").write_text(
            json.dumps(quality, indent=2), encoding="utf-8"
        )
        gaps = {name: payload["events"]["gaps"] for name, payload in reports.items()}
        (out / "gap-detection-test.json").write_text(json.dumps(gaps, indent=2), encoding="utf-8")
        if not args.json:
            print(f"artifacts written to {out}")

    if not deterministic:
        print("REPLAY IS NOT DETERMINISTIC", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="+", help="capture or fixture files to replay")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--out", help="directory to write evidence artifacts into")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
