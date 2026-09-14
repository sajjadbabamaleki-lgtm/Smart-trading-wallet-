"""Duplicate detection.

Build 0.1 Rev.1 §31: reconnect and backfill create duplicates, and every
ingestion path needs deterministic deduplication — but removal must not
accidentally delete a legitimate repeated market event.

That caveat is the whole difficulty. Two trades of the same size at the same
price in the same millisecond are entirely ordinary in an active market. They
are *not* duplicates, and a naive "same price, same size, same time" rule would
silently delete real market activity, understating volume in a way no later
check would catch.

So identity comes from the venue's own identifier when it supplies one
(`tid` for a trade), and only falls back to content when it does not. A
content-derived key is scoped to a short window, because its purpose is
catching redelivery across a reconnect rather than asserting global uniqueness.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta

from libs.schemas.market_event import MarketEvent

DEFAULT_WINDOW = timedelta(minutes=5)
"""How long a key is remembered.

Sized for redelivery after a reconnect, which takes seconds. Minutes give ample
margin; hours would grow memory without adding protection.
"""

DEFAULT_CAPACITY = 500_000
"""Hard bound on remembered keys, whatever the window implies.

An active BTC feed can exceed the window's expected volume during a volatility
burst. A bound that is never reached is free; one that is reached evicts oldest
first, which is also the least likely to be redelivered.
"""


@dataclass(frozen=True, slots=True)
class DedupStats:
    seen: int = 0
    duplicates: int = 0
    evicted: int = 0

    @property
    def duplicate_fraction(self) -> float:
        return self.duplicates / self.seen if self.seen else 0.0


class DuplicateDetector:
    """Remembers recently seen event identities.

    Not a correctness guarantee — a bounded window cannot provide one — but the
    guarantee that matters here: a frame redelivered after a reconnect is
    recognised, and a genuinely repeated market event is not.
    """

    def __init__(
        self,
        *,
        window: timedelta = DEFAULT_WINDOW,
        capacity: int = DEFAULT_CAPACITY,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._window = window
        self._capacity = capacity
        self._seen: OrderedDict[str, datetime] = OrderedDict()
        self._count = 0
        self._duplicates = 0
        self._evicted = 0

    @staticmethod
    def identity(event: MarketEvent) -> str:
        """A stable identity for an event.

        Prefers the venue's identifier. `sequence` carries the venue's trade id
        where one was supplied, and a venue id is authoritative in a way that
        content never is: two distinct trades can share content, but not an id.

        Content is hashed only as a fallback, and includes the event type and
        venue timestamp so that a BBO update and a book snapshot at the same
        quote do not collide.
        """
        if event.sequence is not None:
            return f"{event.asset}:{event.event_type.value}:seq:{event.sequence}"

        material = "|".join(
            (
                event.asset,
                event.instrument,
                event.event_type.value,
                event.timestamps.best_event_time.isoformat(),
                "" if event.price is None else str(event.price),
                "" if event.quantity is None else str(event.quantity),
                "" if event.side is None else event.side.value,
                "" if event.bid_price is None else str(event.bid_price),
                "" if event.ask_price is None else str(event.ask_price),
                "" if event.funding_rate is None else str(event.funding_rate),
                "" if event.open_interest is None else str(event.open_interest),
            )
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
        return f"{event.asset}:{event.event_type.value}:content:{digest}"

    def is_duplicate(self, event: MarketEvent) -> bool:
        """Whether this event has been seen, recording it either way.

        The event's own receipt time drives expiry rather than the wall clock,
        so a replay evicts at the same points the live run did.
        """
        now = event.timestamps.local_receive_time
        self._expire(now)

        key = self.identity(event)
        self._count += 1
        if key in self._seen:
            self._duplicates += 1
            return True

        self._seen[key] = now
        while len(self._seen) > self._capacity:
            self._seen.popitem(last=False)
            self._evicted += 1
        return False

    def _expire(self, now: datetime) -> None:
        cutoff = now - self._window
        while self._seen:
            key, seen_at = next(iter(self._seen.items()))
            if seen_at >= cutoff:
                break
            del self._seen[key]

    @property
    def stats(self) -> DedupStats:
        return DedupStats(seen=self._count, duplicates=self._duplicates, evicted=self._evicted)

    @property
    def tracked(self) -> int:
        return len(self._seen)
