"""Identifier generation.

A correlation id ties one logical workflow together across services, so that
signal -> risk decision -> intent -> order -> fill can later be reconstructed as
a single chain. Build 0.1 Rev.1 §59 requires this from the start rather than as
a retrofit, because an id that was never assigned cannot be recovered.
"""

from __future__ import annotations

import uuid


def _new(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def new_correlation_id() -> str:
    """Identifier for one logical workflow spanning services."""
    return _new("cor")


def new_event_id() -> str:
    """Identifier for one recorded market or trader event."""
    return _new("evt")


def new_intent_id() -> str:
    """Identifier for one execution intent."""
    return _new("int")
