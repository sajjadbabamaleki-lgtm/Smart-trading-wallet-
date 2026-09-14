"""Redis access.

Cache and ephemeral coordination only. Build 0.1 Rev.1 §15 is explicit: Redis
must never become the authoritative source of capital state. The compose file
runs it with persistence disabled so that assumption cannot quietly be relied
upon, and this module offers no API that would encourage it — there is no
"store position" here, only a health check and a namespaced key helper.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Final, cast

from libs.storage.health import StoreHealth, StoreStatus

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from redis import Redis

KEY_PREFIX: Final = "stw"


def namespaced(*parts: str) -> str:
    """Build a namespaced key, e.g. `stw:recorder:btc:last_event`.

    Namespacing keeps one environment's keys from colliding with another's when
    a developer points two processes at the same local Redis.
    """
    if not parts:
        raise ValueError("a key needs at least one part")
    if any(not part for part in parts):
        raise ValueError("key parts must not be empty")
    if any(":" in part for part in parts):
        raise ValueError("key parts must not contain ':' — pass them separately")
    return ":".join((KEY_PREFIX, *parts))


@contextmanager
def connect(url: str, *, timeout_seconds: float = 5.0) -> Iterator[Redis]:
    """Open a Redis client, closing it on exit."""
    # Lazy import: see the note in libs/storage/clickhouse.py.
    import redis  # noqa: PLC0415

    client = redis.Redis.from_url(
        url,
        socket_connect_timeout=timeout_seconds,
        socket_timeout=timeout_seconds,
        decode_responses=True,
    )
    try:
        yield client
    finally:
        client.close()


def check_health(url: str, *, timeout_seconds: float = 5.0) -> StoreHealth:
    """Verify Redis responds and confirm persistence is off.

    The persistence check is deliberate. If someone enables saving, Redis starts
    to look durable, and a future change may lean on that — which is exactly the
    assumption §15 prohibits. Reporting DEGRADED makes the drift visible rather
    than letting it become load-bearing.
    """
    started = time.monotonic()
    try:
        with connect(url, timeout_seconds=timeout_seconds) as client:
            if not client.ping():
                return StoreHealth(
                    store="redis",
                    status=StoreStatus.DEGRADED,
                    latency_ms=(time.monotonic() - started) * 1000,
                    detail="PING did not return a positive response",
                )
            # The redis stubs type these as possibly-awaitable because the
            # same class backs the async client; this is the sync client.
            info = cast("dict[str, Any]", client.info("server"))
            persistence = cast("dict[str, Any]", client.config_get("save"))
            elapsed_ms = (time.monotonic() - started) * 1000
            save_policy = str(persistence.get("save", "")).strip()
            facts = {
                "version": str(info.get("redis_version", "unknown")),
                "save_policy": save_policy or "disabled",
            }
            if save_policy:
                return StoreHealth(
                    store="redis",
                    status=StoreStatus.DEGRADED,
                    latency_ms=elapsed_ms,
                    detail=(
                        f"persistence is enabled (save '{save_policy}'); Redis must "
                        f"stay ephemeral so nothing comes to depend on it for "
                        f"capital state"
                    ),
                    facts=facts,
                )
            return StoreHealth(
                store="redis",
                status=StoreStatus.HEALTHY,
                latency_ms=elapsed_ms,
                facts=facts,
            )
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return StoreHealth(
            store="redis",
            status=StoreStatus.UNREACHABLE,
            latency_ms=(time.monotonic() - started) * 1000,
            detail=f"{type(exc).__name__}: {exc}",
        )
