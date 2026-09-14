"""Data Quality Engine 0.1.

Build 0.1 Rev.1 §33 lists the initial checks and §34 the statuses. The rule
that makes it matter is Rev.2 §21: unknown data quality must never silently
become valid research data. So an event arrives as `UNKNOWN` from the
normalizer and only this engine may promote it to `VALID`.

Phase 2 §11 states where this leads once trading exists:

    Data Quality Failure -> Trading Restriction -> NO TRADE / SAFE MODE

At M2 there is nothing to restrict — the engine classifies and records. The
classification is what a later milestone gates on, which is why an `INVALID`
verdict is recorded rather than discarded: a dataset must be able to exclude
bad segments, and that requires knowing they existed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from libs.schemas.enums import DataQualityStatus
from libs.schemas.market_event import MarketEvent

MAX_PLAUSIBLE_SOURCE_DELAY = timedelta(seconds=30)
"""Beyond this, the venue timestamp and our receipt disagree implausibly.

Not a latency threshold — a sanity bound. A delay this large means a stalled
feed, a clock problem, or a unit error, all of which need a human rather than a
quality flag.
"""

MAX_PLAUSIBLE_CLOCK_SKEW = timedelta(seconds=2)
"""How far ahead of us a venue timestamp may plausibly be.

A venue event cannot really be in our future; a small margin allows for
ordinary clock drift between two hosts. Anything beyond it is skew worth
seeing, since it corrupts every latency measurement taken from it.
"""

MAX_PLAUSIBLE_SPREAD_FRACTION: Final = Decimal("0.10")
"""A quoted spread wider than 10% of mid is treated as suspect.

BTC perpetual spreads are measured in fractions of a basis point in normal
conditions. A spread this wide is either a genuine liquidity event — which
research must be able to find rather than have silently dropped — or corrupt
data. It is flagged, never discarded.
"""


@dataclass(frozen=True, slots=True)
class QualityVerdict:
    """The outcome of validating one event."""

    status: DataQualityStatus
    findings: tuple[str, ...] = ()

    @property
    def usable_for_training(self) -> bool:
        return self.status.usable_for_training

    def with_status(self, status: DataQualityStatus) -> QualityVerdict:
        return QualityVerdict(status=status, findings=self.findings)


class QualityEngine:
    """Validates normalized events.

    Stateless with respect to the stream: sequence continuity and duplicate
    detection are separate concerns (`gaps.py`, `dedup.py`) because they need
    per-stream memory, whereas these checks are properties of a single event.
    Keeping them apart means a quality verdict is reproducible from the event
    alone, which is what makes a replay's verdicts identical to the live ones.
    """

    def __init__(
        self,
        *,
        max_source_delay: timedelta = MAX_PLAUSIBLE_SOURCE_DELAY,
        max_clock_skew: timedelta = MAX_PLAUSIBLE_CLOCK_SKEW,
    ) -> None:
        self._max_source_delay = max_source_delay
        self._max_clock_skew = max_clock_skew

    def validate(self, event: MarketEvent, *, now: datetime) -> QualityVerdict:
        """Classify one event.

        `now` is passed in rather than read from a clock so that a replay
        produces the same verdict as the original live run.
        """
        findings: list[str] = []
        invalid = False

        # Impossible values. The schema already rejects the clearly impossible
        # (non-positive price, negative quantity, crossed book), so reaching
        # here means those passed; what remains is the implausible.
        if event.event_type.value == "TRADE" and event.quantity == 0:
            findings.append("trade_quantity_is_zero")
            invalid = True

        # Timestamp sanity.
        delay = event.timestamps.source_to_receive_seconds
        if delay is not None:
            if delay > self._max_source_delay.total_seconds():
                findings.append(f"source_delay_{delay:.1f}s_exceeds_plausible")
                invalid = True
            elif delay < -self._max_clock_skew.total_seconds():
                # A venue event dated in our future. Reported, never corrected:
                # clock skew must be visible because it invalidates latency
                # measurement (ADR-007).
                findings.append(f"clock_skew_venue_ahead_by_{-delay:.1f}s")

        if event.timestamps.local_receive_time > now:
            findings.append("receive_time_is_in_the_future")
            invalid = True

        # Quote sanity, where both sides are present.
        spread_finding = self._check_spread(event)
        if spread_finding is not None:
            findings.append(spread_finding)

        if invalid:
            return QualityVerdict(status=DataQualityStatus.INVALID, findings=tuple(findings))
        if findings:
            return QualityVerdict(status=DataQualityStatus.WARNING, findings=tuple(findings))
        return QualityVerdict(status=DataQualityStatus.VALID)

    def _check_spread(self, event: MarketEvent) -> str | None:
        mid = event.mid_price
        if mid is None or mid <= 0:
            return None
        assert event.bid_price is not None  # noqa: S101 - implied by mid_price
        assert event.ask_price is not None  # noqa: S101 - implied by mid_price
        spread = event.ask_price - event.bid_price
        if spread / mid > MAX_PLAUSIBLE_SPREAD_FRACTION:
            fraction = (spread / mid * 100).quantize(Decimal("0.01"))
            return f"spread_{fraction}pct_of_mid_is_implausible"
        return None
