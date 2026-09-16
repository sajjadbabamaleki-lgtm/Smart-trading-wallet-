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
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from clickhouse_connect.driver.client import Client  # noqa: E402

from libs.config import ConfigurationError, load_settings  # noqa: E402
from libs.storage import clickhouse as ch  # noqa: E402


def rows(client: Client, sql: str, **parameters: object) -> list[tuple[Any, ...]]:
    return list(client.query(sql, parameters=parameters or None).result_rows)


def window(client: Client, hours: int) -> dict[str, Any]:
    result = rows(
        client,
        "SELECT min(local_receive_time), max(local_receive_time), count() "
        "FROM market_events WHERE local_receive_time >= now() - INTERVAL %(hours)s HOUR",
        hours=hours,
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
        "FROM market_events WHERE local_receive_time >= now() - INTERVAL %(hours)s HOUR "
        "GROUP BY asset, event_type ORDER BY count() DESC",
        hours=hours,
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
        "FROM market_events WHERE local_receive_time >= now() - INTERVAL %(hours)s HOUR "
        "GROUP BY h, event_type ORDER BY h, event_type",
        hours=hours,
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
        "    WHERE local_receive_time >= now() - INTERVAL %(hours)s HOUR"
        "  ) WHERE toUnixTimestamp64Milli(prev) > 0"
        ") GROUP BY asset, event_type ORDER BY longest DESC LIMIT %(top)s",
        hours=hours,
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


def arrival_latency(client: Client, hours: int) -> dict[str, Any]:
    """Quantiles of venue-time to receipt-time, where the venue supplied one."""
    result = rows(
        client,
        "SELECT count(), quantile(0.50)(source_to_receive_ms), "
        "quantile(0.90)(source_to_receive_ms), quantile(0.99)(source_to_receive_ms), "
        "min(source_to_receive_ms), max(source_to_receive_ms) "
        "FROM market_events WHERE local_receive_time >= now() - INTERVAL %(hours)s HOUR "
        "AND source_to_receive_ms IS NOT NULL",
        hours=hours,
    )
    count, p50, p90, p99, low, high = result[0]
    if count == 0:
        return {"events_with_venue_time": 0}
    return {
        "events_with_venue_time": int(count),
        "p50_ms": round(float(p50), 1),
        "p90_ms": round(float(p90), 1),
        "p99_ms": round(float(p99), 1),
        "min_ms": int(low),
        "max_ms": int(high),
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
        "WHERE local_receive_time >= now() - INTERVAL %(hours)s HOUR GROUP BY quality_status",
        hours=hours,
    )
    duplicate_ids = rows(
        client,
        "SELECT count() FROM (SELECT event_id FROM market_events "
        "WHERE local_receive_time >= now() - INTERVAL %(hours)s HOUR "
        "GROUP BY event_id HAVING count() > 1)",
        hours=hours,
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
            "WHERE local_receive_time >= now() - INTERVAL %(hours)s HOUR "
            "AND venue_event_id IS NOT NULL AND venue_event_id != '' "
            "GROUP BY venue_event_id HAVING count() > 1)",
            hours=hours,
        )
        report["duplicate_venue_event_ids"] = int(duplicate_venue_ids[0][0])
    else:
        report["duplicate_venue_event_ids"] = "column absent — migration 005 not applied"

    raw = rows(
        client,
        "SELECT count() FROM raw_messages "
        "WHERE local_receive_time >= now() - INTERVAL %(hours)s HOUR",
        hours=hours,
    )
    report["raw_messages"] = int(raw[0][0])
    return report


def inspect(hours: int) -> dict[str, Any]:
    settings = load_settings()
    with ch.connect_from_settings(settings) as client:
        summary = window(client, hours)
        if summary["events"] == 0:
            return {"window_hours": hours, "summary": summary}
        return {
            "window_hours": hours,
            "summary": summary,
            "streams": by_stream(client, hours),
            "hourly": hourly(client, hours),
            "silences": silences(client, hours),
            "arrival_latency": arrival_latency(client, hours),
            "integrity": integrity(client, hours),
        }


def render(report: dict[str, Any]) -> str:
    lines: list[str] = []
    summary = report["summary"]
    if summary["events"] == 0:
        return f"No market events in the last {report['window_hours']} hours."

    lines.append(
        f"{summary['events']:,} events over {summary['hours_covered']} h "
        f"({summary['events_per_second']}/s)"
    )
    lines.append(f"  {summary['first']}  ->  {summary['last']}")

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

    integrity_report = report["integrity"]
    lines.append("\nIntegrity")
    for status, count in sorted(integrity_report["quality"].items()):
        lines.append(f"  quality {status:<8} {count:>10,}")
    lines.append(f"  duplicate event ids        {integrity_report['duplicate_event_ids']}")
    lines.append(f"  duplicate venue event ids  {integrity_report['duplicate_venue_event_ids']}")
    lines.append(f"  raw messages retained      {integrity_report['raw_messages']:,}")

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
