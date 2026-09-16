#!/usr/bin/env python3
"""Read a completed recording out of ClickHouse and say what it contains.

The recorder prints a report about what it *believes* it wrote. This asks the
store what it *holds* — a different question, and the one a dataset is built
from. Nothing here writes anything.

    python infrastructure/scripts/inspect_recording.py
    python infrastructure/scripts/inspect_recording.py --hours 24 --json

It is written to answer the questions a long run exists to settle:

* Did the stream stay up, or are there silences? Per stream, the longest gap
  between consecutive events, which is the only honest measure of an outage
  after the fact.
* Is the BBO rate diurnal, or did we lose data? The two short runs this
  project made differed roughly tenfold, and an hour-by-hour table is what
  distinguishes a quiet market from a recorder that stopped receiving.
* Does the ~322 ms arrival floor hold over a day, or was it an artefact of a
  fifteen-minute sample?
* Is anything duplicated, and is anything of unknown quality?
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from clickhouse_connect.driver.client import Client  # noqa: E402

from libs.config import ConfigurationError, load_settings  # noqa: E402
from libs.storage import clickhouse as ch  # noqa: E402
from libs.storage import postgres as pg  # noqa: E402

SHOWN_QUIET_MINUTES = 20
# Below this the two clocks are close enough that saying so would be noise.
NOTABLE_SKEW_SECONDS = 60


def rows(client: Client, sql: str, **parameters: object) -> list[tuple[Any, ...]]:
    return list(client.query(sql, parameters=parameters or None).result_rows)


def cutoff_for(hours: int) -> datetime:
    """The start of the window, from our clock rather than the store's.

    `now()` is evaluated by ClickHouse against the server's own clock, and the
    rows were stamped by the recorder against ours. On the recording host those
    two disagree by two hours, which silently emptied every window: a run that
    had just written events reported none in the last hour. Passing the cutoff
    as a value removes the store's clock from the question entirely.
    """
    return datetime.now(UTC) - timedelta(hours=hours)


def clock_skew(client: Client) -> dict[str, Any]:
    """How far the store's clock is from ours, stated rather than assumed."""
    ours = datetime.now(UTC)
    theirs = rows(client, "SELECT toDateTime64(now(), 3, 'UTC')")[0][0]
    stamped = theirs if theirs.tzinfo else theirs.replace(tzinfo=UTC)
    return {
        "ours": ours.isoformat(),
        "store": stamped.isoformat(),
        "skew_seconds": round((stamped - ours).total_seconds(), 1),
    }


def window(client: Client, hours: int) -> dict[str, Any]:
    result = rows(
        client,
        "SELECT min(local_receive_time), max(local_receive_time), count() "
        "FROM market_events WHERE local_receive_time >= %(cutoff)s",
        cutoff=cutoff_for(hours),
    )
    first, last, total = result[0]
    if total == 0:
        return {"events": 0}
    span = (last - first).total_seconds()
    return {
        "events": int(total),
        "first": first.isoformat(),
        "last": last.isoformat(),
        "hours_covered": round(span / 3600, 2),
        "events_per_second": round(total / span, 2) if span else None,
    }


def by_stream(client: Client, hours: int) -> list[dict[str, Any]]:
    result = rows(
        client,
        "SELECT asset, event_type, count(), min(local_receive_time), max(local_receive_time) "
        "FROM market_events WHERE local_receive_time >= %(cutoff)s "
        "GROUP BY asset, event_type ORDER BY count() DESC",
        cutoff=cutoff_for(hours),
    )
    return [
        {
            "asset": asset,
            "event_type": event_type,
            "events": int(count),
            "first": first.isoformat(),
            "last": last.isoformat(),
        }
        for asset, event_type, count, first, last in result
    ]


def hourly(client: Client, hours: int) -> list[dict[str, Any]]:
    """Events per hour per stream — the diurnal-or-outage question."""
    result = rows(
        client,
        "SELECT toStartOfHour(local_receive_time) AS h, event_type, count() "
        "FROM market_events WHERE local_receive_time >= %(cutoff)s "
        "GROUP BY h, event_type ORDER BY h, event_type",
        cutoff=cutoff_for(hours),
    )
    return [
        {"hour": h.isoformat(), "event_type": event_type, "events": int(count)}
        for h, event_type, count in result
    ]


def silences(client: Client, hours: int, top: int = 10) -> list[dict[str, Any]]:
    """Longest gap between consecutive events, per stream.

    A recorder that reconnects quietly looks identical to a quiet market in a
    total count. It does not look identical here.

    `lagInFrame` returns the column's default for the first row of each
    partition rather than NULL, so the epoch rows are dropped explicitly —
    keeping them would report every stream as having a fifty-year silence.
    """
    result = rows(
        client,
        "SELECT asset, event_type, max(delta) AS longest, avg(delta) AS mean FROM ("
        "  SELECT asset, event_type,"
        "         dateDiff('millisecond', prev, local_receive_time) AS delta"
        "  FROM ("
        "    SELECT asset, event_type, local_receive_time,"
        "           lagInFrame(local_receive_time) OVER ("
        "             PARTITION BY asset, event_type ORDER BY local_receive_time"
        "           ) AS prev"
        "    FROM market_events"
        "    WHERE local_receive_time >= %(cutoff)s"
        "  ) WHERE toUnixTimestamp64Milli(prev) > 0"
        ") GROUP BY asset, event_type ORDER BY longest DESC LIMIT %(top)s",
        cutoff=cutoff_for(hours),
        top=top,
    )
    return [
        {
            "asset": asset,
            "event_type": event_type,
            "longest_gap_seconds": round(float(longest) / 1000, 2),
            "mean_gap_ms": round(float(mean), 1),
        }
        for asset, event_type, longest, mean in result
    ]


def timeline(client: Client, hours: int, quiet_under: int = 5) -> list[dict[str, Any]]:
    """Events per minute, and which minutes were quiet.

    A summary can say a stream was silent for twenty-six minutes without
    saying when — and when is the whole question, because a silence at the
    start is a slow connect, one in the middle is a stall, and one at the end
    is a process that died before anyone noticed.
    """
    result = rows(
        client,
        "SELECT toStartOfMinute(local_receive_time) AS m, count() FROM market_events "
        "WHERE local_receive_time >= %(cutoff)s "
        "GROUP BY m ORDER BY m",
        cutoff=cutoff_for(hours),
    )
    return [
        {"minute": minute.isoformat(), "events": int(count), "quiet": int(count) < quiet_under}
        for minute, count in result
    ]


def registered_gaps(dsn: str, hours: int) -> list[dict[str, Any]] | str:
    """What the recorder's own gap registry noticed.

    The point of asking is not the list. It is whether the silences visible in
    the data were detected at the time: a monitor that misses a
    twenty-six-minute outage is a monitor that will miss the next one, and
    that is a finding about the recorder rather than about the market.
    """
    try:
        with pg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT asset, event_type, gap_start, gap_end, detection_reason, "
                "backfill_status FROM data_gaps "
                "WHERE gap_start >= %s ORDER BY gap_start",
                (cutoff_for(hours),),
            )
            return [
                {
                    "asset": asset,
                    "event_type": event_type,
                    "start": start.isoformat(),
                    "end": None if end is None else end.isoformat(),
                    "reason": reason,
                    "backfill": status,
                }
                for asset, event_type, start, end, reason, status in cursor.fetchall()
            ]
    except Exception as exc:  # noqa: BLE001 - reported, not raised: this is a report
        return f"could not read the gap registry: {exc}"


def arrival_latency(client: Client, hours: int) -> dict[str, Any]:
    """Quantiles of venue-time to receipt-time, overall and per event type.

    Per type because the overall tail is not one phenomenon. A funding message
    carries the timestamp of the funding period, not of its own emission, and
    the first frames after a subscribe describe state that last changed
    minutes ago — both arrive "late" by this measure without anything being
    slow. Splitting the distribution is what tells those apart from a feed
    that is genuinely behind.
    """
    cutoff = cutoff_for(hours)
    overall = rows(
        client,
        "SELECT count(), quantile(0.50)(source_to_receive_ms), "
        "quantile(0.90)(source_to_receive_ms), quantile(0.99)(source_to_receive_ms), "
        "min(source_to_receive_ms), max(source_to_receive_ms) "
        "FROM market_events WHERE local_receive_time >= %(cutoff)s "
        "AND source_to_receive_ms IS NOT NULL",
        cutoff=cutoff,
    )
    count, p50, p90, p99, low, high = overall[0]
    if count == 0:
        return {"events_with_venue_time": 0, "by_type": []}

    per_type = rows(
        client,
        "SELECT event_type, count(), quantile(0.50)(source_to_receive_ms), "
        "quantile(0.90)(source_to_receive_ms), quantile(0.99)(source_to_receive_ms), "
        "max(source_to_receive_ms) "
        "FROM market_events WHERE local_receive_time >= %(cutoff)s "
        "AND source_to_receive_ms IS NOT NULL "
        "GROUP BY event_type ORDER BY quantile(0.99)(source_to_receive_ms) DESC",
        cutoff=cutoff,
    )
    return {
        "events_with_venue_time": int(count),
        "p50_ms": round(float(p50), 1),
        "p90_ms": round(float(p90), 1),
        "p99_ms": round(float(p99), 1),
        "min_ms": int(low),
        "max_ms": int(high),
        "by_type": [
            {
                "event_type": event_type,
                "events": int(n),
                "p50_ms": round(float(a), 1),
                "p90_ms": round(float(b), 1),
                "p99_ms": round(float(c), 1),
                "max_ms": int(worst),
            }
            for event_type, n, a, b, c, worst in per_type
        ],
    }


def has_column(client: Client, table: str, column: str) -> bool:
    """Whether a migration that adds a column has actually been applied here."""
    found = rows(
        client,
        "SELECT count() FROM system.columns WHERE database = currentDatabase() "
        "AND table = %(table)s AND name = %(column)s",
        table=table,
        column=column,
    )
    return int(found[0][0]) > 0


def integrity(client: Client, hours: int) -> dict[str, Any]:
    quality = rows(
        client,
        "SELECT quality_status, count() FROM market_events "
        "WHERE local_receive_time >= %(cutoff)s GROUP BY quality_status",
        cutoff=cutoff_for(hours),
    )
    duplicate_ids = rows(
        client,
        "SELECT count() FROM (SELECT event_id FROM market_events "
        "WHERE local_receive_time >= %(cutoff)s "
        "GROUP BY event_id HAVING count() > 1)",
        cutoff=cutoff_for(hours),
    )
    report: dict[str, Any] = {
        "quality": {status: int(count) for status, count in quality},
        "duplicate_event_ids": int(duplicate_ids[0][0]),
    }

    # Migration 005 introduced this. Reporting "0 duplicates" on a store that
    # does not have the column would be a clean bill of health nobody checked.
    if has_column(client, "market_events", "venue_event_id"):
        duplicate_venue_ids = rows(
            client,
            "SELECT count() FROM (SELECT venue_event_id FROM market_events "
            "WHERE local_receive_time >= %(cutoff)s "
            "AND venue_event_id IS NOT NULL AND venue_event_id != '' "
            "GROUP BY venue_event_id HAVING count() > 1)",
            cutoff=cutoff_for(hours),
        )
        report["duplicate_venue_event_ids"] = int(duplicate_venue_ids[0][0])
    else:
        report["duplicate_venue_event_ids"] = "column absent — migration 005 not applied"

    raw = rows(
        client,
        "SELECT count() FROM raw_messages WHERE local_receive_time >= %(cutoff)s",
        cutoff=cutoff_for(hours),
    )
    report["raw_messages"] = int(raw[0][0])
    return report


def whole_store(client: Client) -> dict[str, Any]:
    """What the store holds with no time filter at all.

    Asked only when the window is empty, because "nothing in the last day" has
    two very different causes — a recorder that did not run, and a store that
    lost what it wrote — and the difference is visible the moment you stop
    filtering by time.
    """
    result = rows(
        client,
        "SELECT count(), min(local_receive_time), max(local_receive_time) FROM market_events",
    )
    total, first, last = result[0]
    raw = rows(client, "SELECT count() FROM raw_messages")
    if total == 0:
        return {"events": 0, "raw_messages": int(raw[0][0])}
    return {
        "events": int(total),
        "first": first.isoformat(),
        "last": last.isoformat(),
        "raw_messages": int(raw[0][0]),
    }


def inspect(hours: int) -> dict[str, Any]:
    settings = load_settings()
    with ch.connect_from_settings(settings) as client:
        summary = window(client, hours)
        if summary["events"] == 0:
            return {
                "window_hours": hours,
                "clock": clock_skew(client),
                "summary": summary,
                "whole_store": whole_store(client),
            }
        return {
            "window_hours": hours,
            "clock": clock_skew(client),
            "summary": summary,
            "streams": by_stream(client, hours),
            "hourly": hourly(client, hours),
            "silences": silences(client, hours),
            "timeline": timeline(client, hours),
            "registered_gaps": registered_gaps(settings.postgres_dsn, hours),
            "arrival_latency": arrival_latency(client, hours),
            "integrity": integrity(client, hours),
        }


def missing_minutes(entries: list[dict[str, Any]]) -> list[str]:
    """Minutes between the first and last event that produced no row at all."""
    if not entries:
        return []
    seen = {entry["minute"] for entry in entries}
    first = datetime.fromisoformat(entries[0]["minute"])
    last = datetime.fromisoformat(entries[-1]["minute"])
    gone: list[str] = []
    cursor = first
    while cursor <= last:
        stamp = cursor.isoformat()
        if stamp not in seen:
            gone.append(stamp)
        cursor += timedelta(minutes=1)
    return gone


def continuity(report: dict[str, Any]) -> list[str]:
    """When the stream was quiet, and whether the recorder noticed at the time."""
    lines: list[str] = []
    quiet = [entry for entry in report["timeline"] if entry["quiet"]]
    if quiet:
        lines.append(f"\nQuiet minutes ({len(quiet)} of {len(report['timeline'])})")
        for entry in quiet[:SHOWN_QUIET_MINUTES]:
            lines.append(f"  {entry['minute'][:16]}  {entry['events']:>6} events")
        if len(quiet) > SHOWN_QUIET_MINUTES:
            lines.append(f"  ... and {len(quiet) - SHOWN_QUIET_MINUTES} more")

    missing = missing_minutes(report["timeline"])
    if missing:
        lines.append(f"\nMinutes with no events at all: {len(missing)}")
        lines.append(f"  from {missing[0][:16]} to {missing[-1][:16]}")

    registered = report["registered_gaps"]
    lines.append("\nGap registry")
    if isinstance(registered, str):
        lines.append(f"  {registered}")
    elif not registered:
        # The silence above was real; a registry that says nothing about it is
        # a finding of its own.
        lines.append("  nothing registered in this window")
    else:
        for gap in registered:
            lines.append(
                f"  {gap['asset']:<5} {gap['event_type']:<14} {gap['start'][:19]} -> "
                f"{(gap['end'] or 'open')[:19]}  {gap['reason']}"
            )
    return lines


def render(report: dict[str, Any]) -> str:
    lines: list[str] = []
    summary = report["summary"]
    if summary["events"] == 0:
        stored = report["whole_store"]
        lines.append(f"No market events in the last {report['window_hours']} hours.")
        if stored["events"] == 0:
            lines.append(
                f"  The table is empty: 0 market events, "
                f"{stored['raw_messages']:,} raw messages retained."
            )
            lines.append(
                "  Either the recorder never persisted (a --dry-run writes nothing), "
                "or this is not the store it wrote to."
            )
        else:
            lines.append(
                f"  The store holds {stored['events']:,} events, "
                f"newest {stored['last']}, oldest {stored['first']}."
            )
            lines.append("  Re-run with a wider --hours to inspect them.")
        return "\n".join(lines)

    lines.append(
        f"{summary['events']:,} events over {summary['hours_covered']} h "
        f"({summary['events_per_second']}/s)"
    )
    lines.append(f"  {summary['first']}  ->  {summary['last']}")
    skew = report["clock"]["skew_seconds"]
    if abs(skew) > NOTABLE_SKEW_SECONDS:
        lines.append(
            f"  note: the store's clock is {skew / 3600:+.1f} h from ours "
            "— windows are taken from ours"
        )

    lines.append("\nStreams")
    for stream in report["streams"]:
        lines.append(f"  {stream['asset']:<5} {stream['event_type']:<14} {stream['events']:>10,}")

    lines.append("\nLongest silence per stream")
    for gap in report["silences"]:
        lines.append(
            f"  {gap['asset']:<5} {gap['event_type']:<14} "
            f"longest {gap['longest_gap_seconds']:>8.2f}s   mean {gap['mean_gap_ms']:>8.1f}ms"
        )

    latency = report["arrival_latency"]
    if latency.get("events_with_venue_time"):
        lines.append("\nArrival latency (venue time -> our receipt)")
        lines.append(
            f"  p50 {latency['p50_ms']}ms   p90 {latency['p90_ms']}ms   "
            f"p99 {latency['p99_ms']}ms   min {latency['min_ms']}ms"
        )
        for entry in latency["by_type"]:
            lines.append(
                f"    {entry['event_type']:<14} p50 {entry['p50_ms']:>9.1f}   "
                f"p90 {entry['p90_ms']:>9.1f}   p99 {entry['p99_ms']:>10.1f}   "
                f"max {entry['max_ms']:>10,}"
            )

    integrity_report = report["integrity"]
    lines.append("\nIntegrity")
    for status, count in sorted(integrity_report["quality"].items()):
        lines.append(f"  quality {status:<8} {count:>10,}")
    lines.append(f"  duplicate event ids        {integrity_report['duplicate_event_ids']}")
    lines.append(f"  duplicate venue event ids  {integrity_report['duplicate_venue_event_ids']}")
    lines.append(f"  raw messages retained      {integrity_report['raw_messages']:,}")

    lines.extend(continuity(report))

    lines.append("\nEvents per hour")
    per_hour: dict[str, dict[str, int]] = {}
    for entry in report["hourly"]:
        per_hour.setdefault(entry["hour"], {})[entry["event_type"]] = entry["events"]
    types = sorted({entry["event_type"] for entry in report["hourly"]})
    lines.append("  hour                 " + "".join(f"{t:>12}" for t in types))
    for hour, counts in per_hour.items():
        lines.append(f"  {hour[:16]}  " + "".join(f"{counts.get(t, 0):>12,}" for t in types))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24, help="how far back to look")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()
    try:
        report = inspect(args.hours)
    except ConfigurationError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
