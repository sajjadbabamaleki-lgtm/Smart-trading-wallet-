#!/usr/bin/env python3
"""Ask the store whether the recorder is still receiving, and act if not.

    python infrastructure/scripts/watch_recording.py
    python infrastructure/scripts/watch_recording.py --limit-minutes 10 --json
    python infrastructure/scripts/watch_recording.py --no-restart

Run on a timer, from outside the recorder. The decision is in
`services.market_data.watchdog`; this is the part that touches the world:
reading ClickHouse for the newest event, reading and writing the outage in
PostgreSQL, and asking systemd to restart the recorder.

Exit codes are the interface a timer reports on:

    0  receiving, or the store is empty
    1  not receiving — an outage is open
    2  the watchdog itself could not run

Three properties this has that the recorder's own monitors cannot:

* **It survives the recorder.** A process that never started writes no gap; a
  process that exited writes no gap. This one is not that process.
* **It records the outage where a dataset will find it.** The row goes into
  `data_gaps` against the traded asset, so M4 reads it through the same query
  it uses for every other gap and refuses to call the range clean.
* **It restarts once, not forever.** A recorder refusing to start for a
  configuration reason refuses again, and a five-minute restart loop buries the
  one legible error in a thousand identical ones.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs.config import ConfigurationError, load_settings  # noqa: E402
from libs.observability.email import Alert, send  # noqa: E402
from libs.observability.logging import configure_logging, get_logger  # noqa: E402
from libs.storage import clickhouse as ch  # noqa: E402
from libs.storage import postgres as pg  # noqa: E402
from services.market_data.watchdog import (  # noqa: E402
    ALL_STREAMS,
    WATCHDOG_SOURCE,
    Decision,
    OpenOutage,
    StoreState,
    alert_for,
    assess,
)

logger = get_logger("market_data.watchdog")

SERVICE = "stw-recorder"

# Where the watchdog remembers that it already complained about not being able
# to run. That failure cannot be deduplicated in PostgreSQL, because being
# unable to reach PostgreSQL is one of its causes.
FAILURE_MARKER = Path("/var/lib/stw-watchdog/last-failure-alert")
FAILURE_ALERT_INTERVAL = timedelta(hours=6)


def newest_event(client: Any) -> datetime | None:
    """When the store last received anything, by our clock rather than its own.

    `max(local_receive_time)` is stamped by the recorder from this machine's
    clock. Comparing it against ClickHouse's `now()` would measure the two
    clocks against each other, which on this host differ by two hours.
    """
    rows = list(client.query("SELECT max(local_receive_time) FROM market_events").result_rows)
    newest = rows[0][0] if rows else None
    if newest is None:
        return None
    return newest.replace(tzinfo=UTC) if newest.tzinfo is None else newest


def open_outage(connection: Any, asset: str) -> OpenOutage | None:
    """The outage this watchdog opened and has not closed, if there is one."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT gap_id::text, gap_start, backfill_attempts FROM data_gaps "
            "WHERE source = %s AND asset = %s AND gap_end IS NULL "
            "ORDER BY gap_start DESC LIMIT 1",
            (WATCHDOG_SOURCE, asset),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    gap_id, started_at, attempts = row
    return OpenOutage(gap_id=gap_id, started_at=started_at, restarts_attempted=int(attempts))


def record_outage(connection: Any, *, asset: str, decision: Decision) -> str:
    """Open the outage, so a dataset built over it cannot call itself clean."""
    gap_id = str(uuid.uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO data_gaps (gap_id, source, venue, asset, event_type, "
            "gap_start, detection_reason, quality_impact) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'MATERIAL')",
            (
                gap_id,
                WATCHDOG_SOURCE,
                "hyperliquid",
                asset,
                ALL_STREAMS,
                decision.started_at,
                decision.describe(),
            ),
        )
    connection.commit()
    return gap_id


def close_outage(connection: Any, decision: Decision) -> None:
    """Close it, with the moment data resumed rather than the moment we looked."""
    assert decision.open_outage is not None  # noqa: S101 - implied by RESUMED
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE data_gaps SET gap_end = %s, backfill_status = 'UNRECOVERABLE', "
            "resolution = %s, updated_at = now() WHERE gap_id = %s",
            (
                decision.ended_at,
                # Not RECOVERED. The recorder resumed, but the events published
                # while it was down are gone: Hyperliquid's public history is
                # bounded and this feed is not replayable. Recording it as
                # recovered would claim data the store does not hold.
                "recording resumed; the events published during the outage were not captured",
                decision.open_outage.gap_id,
            ),
        )
    connection.commit()


def note_restart(connection: Any, gap_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE data_gaps SET backfill_attempts = backfill_attempts + 1, "
            "updated_at = now() WHERE gap_id = %s",
            (gap_id,),
        )
    connection.commit()


def restart_recorder() -> dict[str, Any]:
    """Ask systemd to restart the recorder, and report what happened.

    Failures are reported rather than raised. A watchdog that dies because it
    could not restart something has stopped watching, which is worse than the
    thing it failed to fix.
    """
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
            ["/usr/bin/systemctl", "restart", SERVICE],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"attempted": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "attempted": True,
        "ok": done.returncode == 0,
        "returncode": done.returncode,
        "stderr": done.stderr.strip()[:500],
    }


def hostname() -> str:
    """Which machine this is, for a subject line read on a phone."""
    return socket.gethostname()


def due_for_failure_alert(now: datetime) -> bool:
    """Whether to complain again that the watchdog cannot run.

    Rate-limited on disk rather than in a store, because the store being
    unreachable is the main reason this fires. A missing or unreadable marker
    means send: failing closed here would mean silence about silence.
    """
    try:
        stamp = datetime.fromisoformat(FAILURE_MARKER.read_text().strip())
    except (OSError, ValueError):
        return True
    return now - stamp >= FAILURE_ALERT_INTERVAL


def note_failure_alert(now: datetime) -> None:
    try:
        FAILURE_MARKER.parent.mkdir(parents=True, exist_ok=True)
        FAILURE_MARKER.write_text(now.isoformat())
    except OSError as exc:
        # Losing the rate limit costs extra email, not the watch.
        logger.warning("failure_marker_not_written", extra={"error": type(exc).__name__})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-minutes", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--no-restart", action="store_true", help="detect and record, but do not restart"
    )
    parser.add_argument(
        "--test-email",
        action="store_true",
        help="send one alert now and exit, to prove the mail path before it matters",
    )
    args = parser.parse_args()

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"configuration refused: {exc}", file=sys.stderr)
        return 2

    configure_logging(settings.log_level, stream=sys.stderr)

    if args.test_email:
        # Worth its own flag. An alerting path is only ever exercised at the
        # worst possible moment, and finding out then that the password was
        # wrong is finding out too late.
        delivery = send(
            Alert(
                subject=f"[{hostname()}] recording watchdog test",
                body=(
                    "This is a test. Nothing is wrong.\n\n"
                    "If you are reading it, the watchdog can reach you, which is "
                    "the only thing it could not tell you by itself."
                ),
            ),
            settings=settings,
        )
        print(json.dumps(delivery.as_dict(), indent=2))
        return 0 if delivery.sent else 2

    asset = settings.asset_allowlist[0]
    limit = timedelta(minutes=args.limit_minutes)
    now = datetime.now(UTC)

    try:
        with ch.connect_from_settings(settings) as client:
            newest = newest_event(client)
        with pg.connect(settings.postgres_dsn) as connection:
            state = StoreState(newest_event_at=newest, open_outage=open_outage(connection, asset))
            decision = assess(state, now=now, limit=limit)

            action: dict[str, Any] = {}
            if decision.should_open:
                gap_id = record_outage(connection, asset=asset, decision=decision)
                action["opened"] = gap_id
            elif decision.should_close:
                close_outage(connection, decision)
                assert decision.open_outage is not None  # noqa: S101 - implied
                action["closed"] = decision.open_outage.gap_id

            if decision.should_restart and not args.no_restart:
                action["restart"] = restart_recorder()
                target = action.get("opened") or (
                    decision.open_outage.gap_id if decision.open_outage else None
                )
                if target is not None:
                    note_restart(connection, target)
    except Exception as exc:  # noqa: BLE001 - a watchdog reports its own failure
        # Exit 2, not 1: "the watchdog could not run" and "the recorder is not
        # receiving" are different states, and a timer that cannot tell them
        # apart reports an outage every time a database is restarted.
        reason = f"{type(exc).__name__}: {exc}"
        print(f"the watchdog could not complete its check: {reason}", file=sys.stderr)
        if due_for_failure_alert(now):
            send(
                Alert(
                    subject=f"[{hostname()}] the recording watchdog cannot run",
                    body=(
                        f"The watchdog could not complete its check: {reason}\n\n"
                        "This is not the same as the recorder having stopped - it means "
                        "nothing is currently able to tell you whether it has. The usual "
                        "cause is ClickHouse or PostgreSQL being down.\n\n"
                        "  make stack-verify\n"
                        "  make watch\n\n"
                        "At most one of these every six hours."
                    ),
                ),
                settings=settings,
            )
            note_failure_alert(now)
        return 2

    alert = alert_for(decision, host=hostname())
    if alert is not None:
        action["alert"] = send(alert, settings=settings).as_dict()

    report = {
        "checked_at": now.isoformat(),
        "verdict": decision.verdict.value,
        "summary": decision.describe(),
        "newest_event_at": None if newest is None else newest.isoformat(),
        "limit_seconds": limit.total_seconds(),
        "action": action,
    }
    print(json.dumps(report, indent=2) if args.json else decision.describe())

    if decision.is_healthy:
        logger.info("recording_watchdog", extra=report)
        return 0
    logger.error("recording_stopped", extra=report)
    return 1


if __name__ == "__main__":
    sys.exit(main())
