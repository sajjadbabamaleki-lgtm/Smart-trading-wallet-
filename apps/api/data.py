"""Live figures for the console's data screens.

Reads what the stores actually hold. Every number here was written by the
recorder; none is generated for display.

A store that cannot be reached is reported as unreachable rather than as zero.
Zero rows and an unreachable database look identical on a dashboard and mean
opposite things — one is a quiet market, the other is a broken deployment.
"""

from __future__ import annotations

from typing import Any

from libs.config import Settings
from libs.storage import clickhouse as ch


def recorder_stats(settings: Settings) -> dict[str, Any]:
    """Per-stream row counts and coverage, straight from ClickHouse."""
    try:
        with ch.connect_from_settings(settings) as client:
            rows = client.query(
                "SELECT event_type, count(), min(local_receive_time), "
                "max(local_receive_time) FROM market_events "
                "GROUP BY event_type ORDER BY count() DESC"
            ).result_rows
            total = client.query("SELECT count() FROM market_events").result_rows[0][0]
            traders = client.query("SELECT count() FROM trader_events").result_rows[0][0]
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, never hidden
        return {"reachable": False, "error": str(exc)[:200]}

    return {
        "reachable": True,
        "total_market_events": int(total),
        "total_trader_events": int(traders),
        "streams": [
            {
                "event_type": str(row[0]),
                "count": int(row[1]),
                "first": row[2].isoformat() if row[2] else None,
                "last": row[3].isoformat() if row[3] else None,
            }
            for row in rows
        ],
    }
