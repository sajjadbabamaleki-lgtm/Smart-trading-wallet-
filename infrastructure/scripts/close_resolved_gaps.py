#!/usr/bin/env python3
"""Close silences that the data shows ended, but the registry never closed.

    python infrastructure/scripts/close_resolved_gaps.py            # show, change nothing
    python infrastructure/scripts/close_resolved_gaps.py --apply

The monitor learned to close a silence when its stream came back only after
several days of recording had already happened. Everything written before that
is still open, and an open gap is a claim that data is still missing — so the
first research dataset this project built came back INVALID on the strength of
320 rows saying a stream had been quiet for thirty-one seconds overnight, each
of which had in fact resumed seconds later.

The resumption is not a guess. Every one of those streams is in ClickHouse with
the event that ended the silence, so this asks the store when each gap actually
ended and closes it with that timestamp.

**It closes only what it can prove.** A gap whose stream has no event after it
stays open, because that one is real — the thirty-nine-hour outage is exactly
that case, and it must not be swept up by a repair aimed at the noise around it.

Read-only by default. `--apply` is a separate decision because this rewrites
the record of what the recorder saw, and a rewrite that runs by accident is
worse than a dataset that is wrongly INVALID.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs.config import ConfigurationError, load_settings  # noqa: E402
from libs.storage import clickhouse as ch  # noqa: E402
from libs.storage import postgres as pg  # noqa: E402
from services.market_data.watchdog import ALL_STREAMS, WATCHDOG_SOURCE  # noqa: E402

RESOLUTION = "closed retroactively: the store holds the event that ended this silence"

# Events from one frame share a receipt time, and the column's nanoseconds are
# finer than Python's microseconds. A silence is reported only after tens of
# seconds, so nothing within a second of its start ended it.
SAME_FRAME_EPSILON = timedelta(seconds=1)


def open_silences(connection: Any) -> list[tuple[str, str, str, datetime]]:
    """Every open gap the recorder itself opened.

    The watchdog's own rows are excluded. It closes its outages from its own
    evidence, and one of them is the case this must not touch.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT gap_id::text, asset, event_type, gap_start FROM data_gaps "
            "WHERE gap_end IS NULL AND source <> %s ORDER BY gap_start",
            (WATCHDOG_SOURCE,),
        )
        return [(str(a), str(b), str(c), d) for a, b, c, d in cursor.fetchall()]


def resumed_at(client: Any, *, asset: str, event_type: str, after: datetime) -> datetime | None:
    """The first event on this stream after the silence began, if there is one.

    A second is skipped first, and that is the whole of why an earlier version
    of this reported that all 324 silences had lasted zero seconds.

    `local_receive_time` is stamped per frame, and one frame can carry several
    trades — the diagnostic found four events sharing the microsecond a gap
    started on. The column holds nanoseconds; Python sees microseconds. So
    "the first event strictly after the gap started" matched the gap's own
    frame-mates, a few nanoseconds along, and the difference rounded to zero.

    A silence is only recorded after tens of seconds of quiet, so the event
    that ended one cannot be within a second of its start. Anything that close
    is the same frame, and stepping over it costs nothing and settles the
    ambiguity that microsecond arithmetic could not.
    """
    rows = list(
        client.query(
            "SELECT min(local_receive_time) FROM market_events "
            "WHERE asset = %(asset)s AND event_type = %(event_type)s "
            "AND local_receive_time > %(after)s",
            parameters={
                "asset": asset,
                "event_type": event_type,
                "after": (after + SAME_FRAME_EPSILON).astimezone(UTC).replace(tzinfo=None),
            },
        ).result_rows
    )
    resumed = rows[0][0] if rows else None
    if resumed is None:
        return None
    return resumed.replace(tzinfo=UTC) if resumed.tzinfo is None else resumed


def close(connection: Any, gap_id: str, ended_at: datetime) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE data_gaps SET gap_end = %s, backfill_status = 'RECOVERED', "
            "quality_impact = 'NONE', resolution = %s, updated_at = now() "
            "WHERE gap_id = %s AND gap_end IS NULL",
            (ended_at, RESOLUTION, gap_id),
        )


@dataclass
class Findings:
    """What one pass over the registry concluded, grouped so it travels as one."""

    closed: list[dict[str, Any]] = field(default_factory=list)
    left_open: list[dict[str, Any]] = field(default_factory=list)
    implausible: list[dict[str, Any]] = field(default_factory=list)
    outages: list[dict[str, Any]] = field(default_factory=list)


def collect(settings: Any, args: argparse.Namespace, found: Findings) -> None:
    """Walk the open gaps and decide each one, writing only under --apply."""
    with ch.connect_from_settings(settings) as client, pg.connect(settings.postgres_dsn) as conn:
        for gap_id, asset, event_type, gap_start in open_silences(conn):
            ended = resumed_at(client, asset=asset, event_type=event_type, after=gap_start)
            entry = {
                "gap_id": gap_id,
                "stream": f"{asset}/{event_type}",
                "started": gap_start.isoformat(),
            }
            if ended is None:
                # No event after it. Either the stream never came back, or this
                # is the tail of the recording — both stay open, and both are
                # honest answers to "is data still missing?".
                found.left_open.append(entry)
                continue

            seconds = (ended - gap_start).total_seconds()
            entry["ended"] = ended.isoformat()
            entry["seconds"] = round(seconds, 3)

            # A silence was reported because a stream went quiet for longer
            # than its threshold, so an end at or before its start is not a
            # closure — it is a query that answered the wrong question. The
            # first version of this script asked ClickHouse with a timestamp in
            # the wrong zone and computed exactly this for all 324 rows. It
            # would have written all of them.
            if seconds <= 0:
                entry["refused"] = "the computed end is not after the start"
                found.implausible.append(entry)
                continue

            found.closed.append(entry)
            if args.apply:
                close(conn, gap_id, ended)

        if args.record_outages:
            minimum = timedelta(minutes=args.outage_minutes)
            for start, end in data_outages(client, asset=asset, minimum=minimum):
                if already_recorded(conn, asset=asset, start=start, end=end):
                    continue
                entry = {
                    "stream": f"{asset}/{ALL_STREAMS}",
                    "started": start.isoformat(),
                    "ended": end.isoformat(),
                    "seconds": round((end - start).total_seconds(), 3),
                }
                found.outages.append(entry)
                if args.apply:
                    record_outage(conn, asset=asset, start=start, end=end)
        if args.apply:
            conn.commit()


def data_outages(client: Any, *, asset: str, minimum: timedelta) -> list[tuple[datetime, datetime]]:
    """Holes the data itself proves, whatever was or was not running at the time.

    Asked of every stream at once rather than per stream: when the recorder
    stops, every stream stops together, and a hole in all of them is a recorder
    outage rather than a quiet market. A quiet market still carries mark-price
    updates about once a second.

    This exists because the registry can only hold what something was alive to
    write. The thirty-nine-hour outage has no row anywhere — the recorder had
    exited and the watchdog did not yet exist — so a dataset built across it
    would have found nothing to declare and called the range clean. The store
    remembers what no process was there to record.
    """
    rows = list(
        client.query(
            "SELECT previous, current FROM ("
            "  SELECT local_receive_time AS current, "
            "         lagInFrame(local_receive_time) OVER ("
            "           ORDER BY local_receive_time "
            "           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS previous "
            "  FROM (SELECT DISTINCT local_receive_time FROM market_events "
            "        WHERE asset = %(asset)s ORDER BY local_receive_time)"
            ") WHERE previous > toDateTime64(0, 9) "
            "AND dateDiff('second', previous, current) >= %(minimum)s "
            "ORDER BY previous",
            parameters={"asset": asset, "minimum": int(minimum.total_seconds())},
        ).result_rows
    )
    return [
        (
            a.replace(tzinfo=UTC) if a.tzinfo is None else a,
            b.replace(tzinfo=UTC) if b.tzinfo is None else b,
        )
        for a, b in rows
    ]


def already_recorded(connection: Any, *, asset: str, start: datetime, end: datetime) -> bool:
    """Whether some row already covers this hole, so it is not recorded twice."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM data_gaps WHERE asset = %s AND gap_start <= %s "
            "AND (gap_end IS NULL OR gap_end >= %s) LIMIT 1",
            (asset, start, end),
        )
        return cursor.fetchone() is not None


def record_outage(connection: Any, *, asset: str, start: datetime, end: datetime) -> str:
    gap_id = str(uuid.uuid4())
    seconds = (end - start).total_seconds()
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO data_gaps (gap_id, source, venue, asset, event_type, gap_start, "
            "gap_end, detection_reason, backfill_status, quality_impact, resolution) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'UNRECOVERABLE', 'MATERIAL', %s)",
            (
                gap_id,
                WATCHDOG_SOURCE,
                "hyperliquid",
                asset,
                ALL_STREAMS,
                start,
                end,
                f"no event of any type for {seconds:.0f}s; found in the data afterwards",
                # Not recovered, and never will be. The venue published during
                # those hours and this system did not capture it; Hyperliquid's
                # public history is bounded, so it cannot be fetched back.
                "the recorder was not running; these events were never captured",
            ),
        )
    return gap_id


def explain(settings: Any, count: int) -> None:
    """Print what the two stores actually say about the first few gaps.

    Written because two hypotheses about why every closure computed to zero
    were both wrong, and a third guess is worth less than one look. Every value
    the comparison depends on is printed: what PostgreSQL holds, what is sent
    to ClickHouse, what ClickHouse echoes back of it, and the events on either
    side of the moment in question.
    """
    with ch.connect_from_settings(settings) as client, pg.connect(settings.postgres_dsn) as conn:
        gaps = open_silences(conn)[:count]
        with conn.cursor() as cursor:
            cursor.execute("SHOW timezone")
            row = cursor.fetchone()
            print(f"postgres session timezone: {row[0] if row else 'unknown'}")
        echoed = list(client.query("SELECT timezone(), now()").result_rows)
        print(f"clickhouse timezone / now:  {echoed[0] if echoed else 'unknown'}")
        print()

        for gap_id, asset, event_type, gap_start in gaps:
            sent = gap_start.astimezone(UTC).replace(tzinfo=None)
            rows = list(
                client.query(
                    "SELECT min(local_receive_time), max(local_receive_time), count() "
                    "FROM market_events WHERE asset = %(asset)s "
                    "AND event_type = %(event_type)s AND local_receive_time > %(after)s",
                    parameters={
                        "asset": asset,
                        "event_type": event_type,
                        "after": sent + SAME_FRAME_EPSILON,
                    },
                ).result_rows
            )
            around = list(
                client.query(
                    "SELECT local_receive_time FROM market_events "
                    "WHERE asset = %(asset)s AND event_type = %(event_type)s "
                    "ORDER BY abs(dateDiff('millisecond', local_receive_time, "
                    "toDateTime64(%(after)s, 9))) ASC LIMIT 4",
                    parameters={"asset": asset, "event_type": event_type, "after": sent},
                ).result_rows
            )
            print(f"gap {gap_id[:8]}  {asset}/{event_type}")
            print(f"  postgres gap_start : {gap_start.isoformat()}")
            print(f"  sent to clickhouse : {sent.isoformat()}")
            print(f"  min/max/count after: {rows[0] if rows else 'no rows'}")
            print(f"  nearest events     : {[r[0].isoformat() for r in around]}")
            print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the closures")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--record-outages",
        action="store_true",
        help="also record holes the data proves but nothing was alive to write",
    )
    parser.add_argument(
        "--outage-minutes",
        type=float,
        default=10.0,
        help="how long a hole in every stream must be to count as an outage",
    )
    parser.add_argument(
        "--explain",
        type=int,
        default=0,
        metavar="N",
        help="print the raw timestamps behind the first N gaps, and change nothing",
    )
    args = parser.parse_args()

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"configuration refused: {exc}", file=sys.stderr)
        return 2

    if args.explain:
        try:
            explain(settings, args.explain)
        except Exception as exc:  # noqa: BLE001 - a diagnostic reports its own failure
            print(f"could not reach the stores: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        return 0

    found = Findings()

    try:
        collect(settings, args, found)
    except Exception as exc:  # noqa: BLE001 - a repair reports why it could not run
        print(f"could not reach the stores: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    lengths = sorted(float(e["seconds"]) for e in found.closed)
    report = {
        "applied": args.apply,
        "closeable": len(found.closed),
        "left_open": len(found.left_open),
        "refused_as_implausible": len(found.implausible),
        # The spread, not just the longest. One number cannot show that every
        # closure came out identical, which is what a broken query looks like.
        "shortest_closed_seconds": lengths[0] if lengths else 0,
        "median_closed_seconds": lengths[len(lengths) // 2] if lengths else 0,
        "longest_closed_seconds": lengths[-1] if lengths else 0,
        "still_open": found.left_open,
        "implausible": found.implausible[:10],
        "outages_found": found.outages,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        verb = "closed" if args.apply else "would close"
        print(f"{verb} {len(found.closed)} silence(s) the store shows ended")
        print(f"left open {len(found.left_open)} with no event after them")
        if found.implausible:
            print(
                f"REFUSED {len(found.implausible)}: the computed end was not after the start. "
                "That is a query answering the wrong question, not a gap."
            )
        if found.closed:
            print(
                f"length: shortest {report['shortest_closed_seconds']}s, "
                f"median {report['median_closed_seconds']}s, "
                f"longest {report['longest_closed_seconds']}s"
            )
        for entry in found.left_open:
            print(f"  still open  {entry['stream']:<18} since {entry['started'][:19]}")
        for entry in found.outages:
            hours = float(entry["seconds"]) / 3600
            print(
                f"  OUTAGE      nothing arrived for {hours:.1f}h "
                f"from {entry['started'][:19]} — no row existed for it"
            )
        if not args.apply:
            print("\nnothing was written. Re-run with --apply to write these closures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
