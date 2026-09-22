"""Scheduled US macro events around which no new position is opened.

Evidence: Bitcoin's mean absolute hourly return roughly doubles in the FOMC
statement hour (0.66% to 1.25%) with volume up 2.5x, and volatility starts
rising before CPI and FOMC releases (studies cited in the README). A stop set
at 2 x ATR from ordinary volatility is too tight for that hour, so the
analyst does not open trades in the window around them. Open positions keep
their stops; this only blocks new entries.

Dates are published a year ahead:
- FOMC: federalreserve.gov/monetarypolicy/fomccalendars.htm — the statement
  is released at 14:00 US Eastern on the second day of each meeting.
- CPI: bls.gov release schedule — 08:30 US Eastern.

**This list must be extended each year.** Past its last date the calendar
reports itself stale, and the analyst refuses to auto-execute rather than
trading blind through events it no longer knows about.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

EASTERN: Final = ZoneInfo("America/New_York")

BLOCK_BEFORE: Final = timedelta(hours=12)
BLOCK_AFTER: Final = timedelta(hours=3)

FOMC_STATEMENTS_2026: Final = (
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 9),
)
CPI_RELEASES_2026: Final = (
    date(2026, 10, 14),
    date(2026, 11, 10),
    date(2026, 12, 10),
)
CALENDAR_VALID_UNTIL: Final = date(2026, 12, 31)


@dataclass(frozen=True)
class MacroEvent:
    name: str
    at: datetime


def _events() -> list[MacroEvent]:
    events = [
        MacroEvent("FOMC statement", datetime.combine(d, time(14, 0), tzinfo=EASTERN))
        for d in FOMC_STATEMENTS_2026
    ]
    events += [
        MacroEvent("US CPI release", datetime.combine(d, time(8, 30), tzinfo=EASTERN))
        for d in CPI_RELEASES_2026
    ]
    return sorted(events, key=lambda e: e.at)


EVENTS: Final = _events()


@dataclass(frozen=True)
class CalendarCheck:
    stale: bool
    blocking: MacroEvent | None
    next_event: MacroEvent | None


def check(now: datetime) -> CalendarCheck:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    stale = now.date() > CALENDAR_VALID_UNTIL
    blocking = next((e for e in EVENTS if e.at - BLOCK_BEFORE <= now <= e.at + BLOCK_AFTER), None)
    upcoming = next((e for e in EVENTS if e.at > now), None)
    return CalendarCheck(stale=stale, blocking=blocking, next_event=upcoming)
