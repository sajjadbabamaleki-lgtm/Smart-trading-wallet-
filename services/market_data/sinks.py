"""Where recorded data goes.

The pipeline writes to two places, and the order is not interchangeable:

1. **Raw first.** The original frame is archived before normalization is
   attempted, so a normalization defect cannot destroy the evidence
   (Build 0.1 Rev.2 §20). If normalization then fails, the frame is still
   recoverable and the failure is a bug to fix, not data to re-collect.
2. **Normalized second**, carrying a reference back to the raw frame.

A `Sink` is a protocol so the recorder can be driven against an in-memory sink
in tests — deterministically, with no store running (Build 0.1 Rev.1 §64).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from libs.schemas.market_event import MarketEvent
from libs.schemas.trader_event import TraderEvent
from services.market_data.gaps import GapReport


@dataclass(frozen=True, slots=True)
class RawFrame:
    """One preserved source frame."""

    raw_id: str
    source: str
    venue: str
    channel: str
    payload: str
    received_at_iso: str
    received_monotonic_ns: int

    @property
    def payload_sha256(self) -> str:
        return hashlib.sha256(self.payload.encode("utf-8")).hexdigest()

    @property
    def payload_bytes(self) -> int:
        return len(self.payload.encode("utf-8"))


@runtime_checkable
class Sink(Protocol):
    """Destination for recorded data."""

    async def write_raw(self, frame: RawFrame) -> None:
        """Persist one raw frame. Called before normalization is attempted."""
        ...

    async def write_market_events(self, events: tuple[MarketEvent, ...]) -> None:
        """Persist normalized market events."""
        ...

    async def write_trader_events(self, events: tuple[TraderEvent, ...]) -> None:
        """Persist normalized trader events."""
        ...

    async def write_gap(self, gap: GapReport) -> None:
        """Record a detected gap."""
        ...

    async def flush(self) -> None:
        """Force any buffered writes through."""
        ...


@dataclass
class InMemorySink:
    """Collects everything in memory.

    Used by the replay and unit tests. Records in arrival order so a test can
    assert that raw frames precede the events derived from them, which is the
    ordering guarantee that makes re-derivation possible.
    """

    raw: list[RawFrame] = field(default_factory=list)
    market_events: list[MarketEvent] = field(default_factory=list)
    trader_events: list[TraderEvent] = field(default_factory=list)
    gaps: list[GapReport] = field(default_factory=list)
    order: list[str] = field(default_factory=list)
    flushes: int = 0

    async def write_raw(self, frame: RawFrame) -> None:
        self.raw.append(frame)
        self.order.append(f"raw:{frame.raw_id}")

    async def write_market_events(self, events: tuple[MarketEvent, ...]) -> None:
        self.market_events.extend(events)
        self.order.extend(f"market:{event.event_id}" for event in events)

    async def write_trader_events(self, events: tuple[TraderEvent, ...]) -> None:
        self.trader_events.extend(events)
        self.order.extend(f"trader:{event.event_id}" for event in events)

    async def write_gap(self, gap: GapReport) -> None:
        self.gaps.append(gap)
        self.order.append(f"gap:{gap.gap_id}")

    async def flush(self) -> None:
        self.flushes += 1


@dataclass
class FailingSink:
    """A sink that fails on demand, for failure-injection tests.

    Build 0.1 Rev.1 §33 lists persistence failure among the conditions the
    quality engine must detect, and §8 requires that failures be created
    deliberately rather than waited for. A recorder that loses data silently
    when its store rejects a write is the failure this exists to catch.
    """

    inner: InMemorySink = field(default_factory=InMemorySink)
    fail_raw_after: int | None = None
    fail_events_after: int | None = None
    raw_calls: int = 0
    event_calls: int = 0

    async def write_raw(self, frame: RawFrame) -> None:
        self.raw_calls += 1
        if self.fail_raw_after is not None and self.raw_calls > self.fail_raw_after:
            raise OSError("simulated raw archive failure")
        await self.inner.write_raw(frame)

    async def write_market_events(self, events: tuple[MarketEvent, ...]) -> None:
        self.event_calls += 1
        if self.fail_events_after is not None and self.event_calls > self.fail_events_after:
            raise OSError("simulated event store failure")
        await self.inner.write_market_events(events)

    async def write_trader_events(self, events: tuple[TraderEvent, ...]) -> None:
        await self.inner.write_trader_events(events)

    async def write_gap(self, gap: GapReport) -> None:
        await self.inner.write_gap(gap)

    async def flush(self) -> None:
        await self.inner.flush()
