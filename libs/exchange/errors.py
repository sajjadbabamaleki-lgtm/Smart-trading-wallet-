"""Errors shared by every venue integration.

The trader reacts to these, never to a venue's own exception types, so a new
venue only has to translate its failures into this vocabulary.
"""

from __future__ import annotations


class VenueError(RuntimeError):
    """The venue rejected a request, or answered with something unparseable."""


class OrderOutcomeUnknownError(VenueError):
    """An order request may or may not have reached the venue.

    Raised instead of a plain failure so the caller checks positions before
    retrying, rather than opening the same trade twice (Phase 6 §41).
    """
