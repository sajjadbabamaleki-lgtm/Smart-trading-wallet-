"""The Crypto Fear & Greed Index, from alternative.me.

Free, no key, no quota, and it reaches back to February 2018 — which makes it
the only sentiment input this project can test against history rather than
collect forward for months.

**What it is, honestly.** A composite scored 0 to 100, where 0 is extreme fear
and 100 extreme greed. Its published components are volatility (25%), market
momentum and volume (25%), social media (15%), Bitcoin dominance (10%) and
search trends (10%). So roughly half of it *is* derived from price, and to that
extent it is another transformation of the series this project has already
mined. The other half — social posts and search interest — is not, and that is
the part worth testing.

Said plainly because the alternative is to present it as an independent signal
and quietly rediscover momentum.

**The hypothesis it supports is contrarian and old.** Extreme fear marks
capitulation, extreme greed marks crowding, and both are moments to take the
other side. It is the same shape as the funding hypothesis, with sentiment in
place of positioning — and the funding edge decayed, so the null hypothesis
here is that this one has too, or never existed.

**Publication is lagged by a day on purpose.** The index updates daily and the
API's timestamp is the update, but the window it describes ends somewhere
inside that day and the documentation does not pin down where. Treating a
value as available only from the day after its timestamp costs a little signal
and cannot leak; the reverse would let a backtest read the afternoon's
sentiment at breakfast.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import httpx

INDEX_URL: Final = "https://api.alternative.me/fng/"
"""Public, unauthenticated, no quota published."""

SOURCE: Final = "alternative.me"

REQUEST_TIMEOUT_SECONDS: Final = 30.0

PUBLICATION_LAG: Final = timedelta(days=1)
"""How long after its timestamp a reading is treated as known.

One day, conservatively. The index describes a window ending somewhere inside
its own day and the API does not say where, so this assumes the worst: the
value is usable only once that day is over.
"""

EXTREME_FEAR: Final = Decimal(25)
EXTREME_GREED: Final = Decimal(75)
"""The published band boundaries, not thresholds chosen here.

alternative.me labels 0 to 24 extreme fear and 75 to 100 extreme greed, and using
its own bands rather than numbers fitted on this data is the difference
between testing a hypothesis and fitting one.
"""


class SentimentError(RuntimeError):
    """A sentiment series this module will not interpret."""


@dataclass(frozen=True, slots=True)
class Reading:
    """One daily index value, as published."""

    moment: datetime
    """The timestamp the source gave. Not when we may use it — see `known_from`."""

    value: Decimal
    classification: str

    @property
    def known_from(self) -> datetime:
        """The earliest moment a decision may use this reading."""
        return self.moment + PUBLICATION_LAG

    @property
    def is_extreme_fear(self) -> bool:
        return self.value < EXTREME_FEAR

    @property
    def is_extreme_greed(self) -> bool:
        return self.value >= EXTREME_GREED


@dataclass(frozen=True, slots=True)
class SentimentHistory:
    """A sentiment series that can only be asked about what was known.

    Indexed on `known_from` rather than on the source's timestamp, so a
    point-in-time cut is a cut on our own availability. Indexing on the
    source's time and subtracting the lag at each query would work too, and
    would put the lag in every call site instead of in one place.
    """

    moments: tuple[datetime, ...]
    """Ascending `known_from` times, one per reading."""
    readings: tuple[Reading, ...]

    def __post_init__(self) -> None:
        if len(self.moments) != len(self.readings):
            raise SentimentError("a sentiment history needs one moment per reading")
        if any(
            later < earlier for earlier, later in zip(self.moments, self.moments[1:], strict=False)
        ):
            raise SentimentError(
                "sentiment moments are not in order; a point-in-time cut over an "
                "unsorted series silently includes the future"
            )

    @classmethod
    def build(cls, readings: Sequence[Reading]) -> SentimentHistory:
        if not readings:
            raise SentimentError("cannot build a sentiment history from no readings")
        ordered = sorted(readings, key=lambda entry: entry.known_from)
        return cls(
            moments=tuple(entry.known_from for entry in ordered),
            readings=tuple(ordered),
        )

    def at(self, moment: datetime) -> Reading | None:
        """The most recent reading knowable at `moment`, or None before the first."""
        index = bisect.bisect_right(self.moments, moment)
        if index == 0:
            return None
        return self.readings[index - 1]


def parse_reading(payload: dict[str, Any]) -> Reading:
    """One entry from the API, refusing anything malformed."""
    for key in ("value", "timestamp"):
        if key not in payload:
            raise SentimentError(f"sentiment record is missing {key!r}: {payload!r}")
    try:
        value = Decimal(str(payload["value"]))
        moment = datetime.fromtimestamp(int(payload["timestamp"]), tz=UTC)
    except (ArithmeticError, ValueError, OSError) as exc:
        raise SentimentError(f"sentiment record is not readable: {payload!r}") from exc
    if not Decimal(0) <= value <= Decimal(100):
        raise SentimentError(f"sentiment value {value} is outside 0..100")
    return Reading(
        moment=moment,
        value=value,
        classification=str(payload.get("value_classification", "")),
    )


async def fetch_history(
    *,
    limit: int = 0,
    client: httpx.AsyncClient | None = None,
    endpoint: str = INDEX_URL,
) -> tuple[Reading, ...]:
    """Every published reading, oldest first.

    `limit=0` asks the API for its whole history, which is one request for
    about three thousand days. There is no pagination to get wrong here, which
    is a pleasant change.
    """
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        response = await http.get(endpoint, params={"limit": limit, "format": "json"})
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            await http.aclose()

    if not isinstance(payload, dict) or "data" not in payload:
        raise SentimentError(f"expected an object with a 'data' list, got {type(payload).__name__}")
    entries = payload["data"]
    if not isinstance(entries, list):
        raise SentimentError(f"'data' is {type(entries).__name__}, expected a list")
    readings = [parse_reading(entry) for entry in entries]
    return tuple(sorted(readings, key=lambda entry: entry.moment))
