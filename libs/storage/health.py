"""Store health checks.

M1's deliverable is verification, not just definition: Build 0.1 Rev.2 §41
asks M1 to *verify* PostgreSQL, ClickHouse, Redis and raw object storage, and
Rev.1 §77 requires that a clean environment can start the entire stack.

A health check answers one question per store — can we reach it, authenticate,
and perform the operation we actually need? Reachability alone is not enough:
a store that accepts a connection and refuses a write is not healthy for our
purposes, so each check exercises its store's real operation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class StoreStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNREACHABLE = "UNREACHABLE"
    MISCONFIGURED = "MISCONFIGURED"

    @property
    def is_usable(self) -> bool:
        return self is StoreStatus.HEALTHY


@dataclass(frozen=True, slots=True)
class StoreHealth:
    """Result of checking one store."""

    store: str
    status: StoreStatus
    latency_ms: float | None = None
    detail: str = ""
    facts: dict[str, str] = field(default_factory=dict)

    @property
    def is_usable(self) -> bool:
        return self.status.is_usable

    def render(self) -> str:
        """One human-readable line."""
        symbol = {
            StoreStatus.HEALTHY: "ok",
            StoreStatus.DEGRADED: "degraded",
            StoreStatus.UNREACHABLE: "unreachable",
            StoreStatus.MISCONFIGURED: "misconfigured",
        }[self.status]
        timing = f" {self.latency_ms:.0f}ms" if self.latency_ms is not None else ""
        suffix = f" — {self.detail}" if self.detail else ""
        return f"{self.store:<14} {symbol:<14}{timing}{suffix}"


def check_all(checks: dict[str, Callable[[], StoreHealth]]) -> tuple[StoreHealth, ...]:
    """Run every check, returning one result per store.

    An exception inside a check becomes an `UNREACHABLE` result rather than
    propagating: the point of verification is a complete picture of which
    stores are usable, and aborting on the first failure would hide the state
    of the rest.
    """
    results: list[StoreHealth] = []
    for name, check in checks.items():
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001 - a failed check is a result, not a crash
            results.append(
                StoreHealth(
                    store=name,
                    status=StoreStatus.UNREACHABLE,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
    return tuple(results)
