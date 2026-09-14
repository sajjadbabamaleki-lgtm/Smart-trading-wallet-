"""Where frames come from.

A `MessageSource` yields raw frames with the timestamps taken at receipt. Two
implementations exist, and the fact that they are interchangeable is the point:

`FixtureSource`
    Replays recorded frames from a file. Deterministic, needs no network, and
    is what the replay tests use — "given this recorded sequence of messages,
    normalization must produce exactly these events" (Build 0.1 Rev.1 §64).

`HyperliquidWebSocketSource`
    The live feed (`libs/exchange/hyperliquid/websocket.py`).

The recorder consumes the protocol, so every part of it except the socket
itself is testable without a venue.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from libs.domain.clock import Clock
from libs.domain.timestamps import EventTimestamps


@dataclass(frozen=True, slots=True)
class IncomingFrame:
    """One frame as received, with our own timestamps already attached.

    Timestamps are taken at the moment of receipt rather than when processing
    begins, because the interval between those two points is exactly what the
    latency instrumentation is trying to measure (ADR-007).
    """

    payload: str
    receipt: EventTimestamps


@runtime_checkable
class MessageSource(Protocol):
    """A stream of raw frames."""

    @property
    def name(self) -> str:
        """Identifies this source in recorded data and logs."""
        ...

    def frames(self) -> AsyncIterator[IncomingFrame]:
        """Yield frames until the source is exhausted or fails."""
        ...


class FixtureSource:
    """Replays frames from newline-delimited JSON.

    Receipt timestamps come from the injected clock, so a replay driven by a
    `ManualClock` produces byte-identical output every run. A fixture line may
    carry its own `received_at`, in which case it is used — that is how a
    recorded session replays with its original timing rather than with the
    timing of the replay.
    """

    def __init__(self, path: Path, clock: Clock, *, name: str = "fixture") -> None:
        self._path = path
        self._clock = clock
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def frames(self) -> AsyncIterator[IncomingFrame]:
        for line in self._path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("//"):
                continue
            yield self._to_frame(text)

    def _to_frame(self, text: str) -> IncomingFrame:
        # A fixture line is either a bare venue frame or an envelope recording
        # when that frame was received. The envelope form is what a captured
        # session looks like; the bare form keeps hand-written fixtures short.
        payload = text
        received_at = None
        monotonic = None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and "frame" in parsed:
            payload = json.dumps(parsed["frame"], separators=(",", ":"))
            received_at = parsed.get("received_at")
            monotonic = parsed.get("received_monotonic_ns")

        if received_at is not None:
            receipt = EventTimestamps(
                local_receive_time=datetime.fromisoformat(str(received_at)),
                local_receive_monotonic_ns=int(monotonic or 0),
            )
        else:
            receipt = EventTimestamps(
                local_receive_time=self._clock.now(),
                local_receive_monotonic_ns=self._clock.monotonic_ns(),
            )
        return IncomingFrame(payload=payload, receipt=receipt)


class IterableSource:
    """Replays an in-memory sequence of frame payloads.

    For tests that construct their input inline rather than from a file.
    """

    def __init__(self, payloads: Iterable[str], clock: Clock, *, name: str = "iterable") -> None:
        self._payloads = list(payloads)
        self._clock = clock
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def frames(self) -> AsyncIterator[IncomingFrame]:
        for payload in self._payloads:
            yield IncomingFrame(
                payload=payload,
                receipt=EventTimestamps(
                    local_receive_time=self._clock.now(),
                    local_receive_monotonic_ns=self._clock.monotonic_ns(),
                ),
            )
