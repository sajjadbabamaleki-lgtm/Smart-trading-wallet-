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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs.config import ConfigurationError, load_settings  # noqa: E402
from libs.storage import clickhouse as ch  # noqa: E402
from libs.storage import postgres as pg  # noqa: E402
from services.market_data.watchdog import WATCHDOG_SOURCE  # noqa: E402

RESOLUTION = "closed retroactively: the store holds the event that ended this silence"


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

    `after` is converted to UTC before it is sent. PostgreSQL hands back a
    timestamp in the session's zone, which on the recording host is two hours
    from UTC, and ClickHouse stores UTC. Passing it across unconverted asks for
    the first event after a moment two hours off from the one meant — which is
    how the first run of this reported that all 324 silences had lasted zero
    seconds.
    """
    rows = list(
        client.query(
            "SELECT min(local_receive_time) FROM market_events "
            "WHERE asset = %(asset)s AND event_type = %(event_type)s "
            "AND local_receive_time > %(after)s",
            parameters={
                "asset": asset,
                "event_type": event_type,
                "after": after.astimezone(UTC).replace(tzinfo=None),
            },
        ).result_rows
    )
    found = rows[0][0] if rows else None
    if found is None:
        return None
    return found.replace(tzinfo=UTC) if found.tzinfo is None else found


def close(connection: Any, gap_id: str, ended_at: datetime) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE data_gaps SET gap_end = %s, backfill_status = 'RECOVERED', "
            "quality_impact = 'NONE', resolution = %s, updated_at = now() "
            "WHERE gap_id = %s AND gap_end IS NULL",
            (ended_at, RESOLUTION, gap_id),
        )


def collect(
    settings: Any,
    args: argparse.Namespace,
    closed: list[dict[str, Any]],
    left_open: list[dict[str, Any]],
    implausible: list[dict[str, Any]],
) -> None:
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
                left_open.append(entry)
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
                implausible.append(entry)
                continue

            closed.append(entry)
            if args.apply:
                close(conn, gap_id, ended)
        if args.apply:
            conn.commit()


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
                    parameters={"asset": asset, "event_type": event_type, "after": sent},
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

    closed: list[dict[str, Any]] = []
    left_open: list[dict[str, Any]] = []
    implausible: list[dict[str, Any]] = []

    try:
        collect(settings, args, closed, left_open, implausible)
    except Exception as exc:  # noqa: BLE001 - a repair reports why it could not run
        print(f"could not reach the stores: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    lengths = sorted(float(e["seconds"]) for e in closed)
    report = {
        "applied": args.apply,
        "closeable": len(closed),
        "left_open": len(left_open),
        "refused_as_implausible": len(implausible),
        # The spread, not just the longest. One number cannot show that every
        # closure came out identical, which is what a broken query looks like.
        "shortest_closed_seconds": lengths[0] if lengths else 0,
        "median_closed_seconds": lengths[len(lengths) // 2] if lengths else 0,
        "longest_closed_seconds": lengths[-1] if lengths else 0,
        "still_open": left_open,
        "implausible": implausible[:10],
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        verb = "closed" if args.apply else "would close"
        print(f"{verb} {len(closed)} silence(s) the store shows ended")
        print(f"left open {len(left_open)} with no event after them")
        if implausible:
            print(
                f"REFUSED {len(implausible)}: the computed end was not after the start. "
                "That is a query answering the wrong question, not a gap."
            )
        if closed:
            print(
                f"length: shortest {report['shortest_closed_seconds']}s, "
                f"median {report['median_closed_seconds']}s, "
                f"longest {report['longest_closed_seconds']}s"
            )
        for entry in left_open:
            print(f"  still open  {entry['stream']:<18} since {entry['started'][:19]}")
        if not args.apply:
            print("\nnothing was written. Re-run with --apply to write these closures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
