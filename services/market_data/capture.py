"""Capturing and reloading recorded sessions.

M2's fixtures were hand-written. This is how real sessions become test input:
a captured session is the raw frames exactly as they arrived, with the receipt
timestamps taken at the time, so replaying it reproduces what the recorder saw
rather than an approximation of it.

The format is newline-delimited JSON, one envelope per frame:

    {"received_at": "...", "received_monotonic_ns": 123, "frame": {...}}

The envelope exists because the frame alone is not enough. A venue frame carries
the venue's timestamp; it cannot carry ours. Replaying without our receipt times
would silently substitute the replay's timing for the capture's, which is
exactly the substitution ADR-007 exists to prevent — and it would make the
source-to-receipt delay, the one measurement Gate 0 needs, unrecoverable.

`monotonic_ns` is preserved as captured and is only meaningful relative to other
readings from the same session. Comparing it across sessions is meaningless,
which is why the loader keeps it rather than normalising it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from libs.domain.timestamps import EventTimestamps
from libs.observability.logging import get_logger
from services.market_data.sinks import RawFrame
from services.market_data.source import IncomingFrame

logger = get_logger(__name__)

CAPTURE_FORMAT_VERSION = 1


class CaptureError(ValueError):
    """A capture file cannot be read. It is not partially used."""


@dataclass(frozen=True, slots=True)
class CaptureHeader:
    """First line of a capture file, describing the session.

    Written so a capture is self-describing: which venue, which assets, when,
    and under which schema version. A capture without this is still readable —
    the loader treats a missing header as an older, headerless file — but a new
    capture always writes one, because a fixture whose provenance is unknown is
    a fixture nobody can trust.
    """

    format_version: int
    venue: str
    source: str
    assets: tuple[str, ...]
    channels: tuple[str, ...]
    started_at: str
    recorder_version: str = "build-0.1"

    def to_json(self) -> str:
        return json.dumps(
            {
                "capture_header": {
                    "format_version": self.format_version,
                    "venue": self.venue,
                    "source": self.source,
                    "assets": list(self.assets),
                    "channels": list(self.channels),
                    "started_at": self.started_at,
                    "recorder_version": self.recorder_version,
                }
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> CaptureHeader:
        assets = payload.get("assets")
        channels = payload.get("channels")
        return cls(
            format_version=int(str(payload.get("format_version", 0))),
            venue=str(payload.get("venue", "")),
            source=str(payload.get("source", "")),
            assets=tuple(str(item) for item in assets) if isinstance(assets, list) else (),
            channels=tuple(str(item) for item in channels) if isinstance(channels, list) else (),
            started_at=str(payload.get("started_at", "")),
            recorder_version=str(payload.get("recorder_version", "unknown")),
        )


class SessionWriter:
    """Writes a capture file.

    Appends rather than buffering the whole session: a capture interrupted by a
    crash must still be replayable up to the point of the crash, which is often
    precisely the session worth examining.
    """

    def __init__(self, path: Path, header: CaptureHeader) -> None:
        self._path = path
        self._header = header
        self._handle: object | None = None
        self._count = 0

    def __enter__(self) -> SessionWriter:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("w", encoding="utf-8")
        self._write_line(self._header.to_json())
        return self

    def __exit__(self, *exc: object) -> None:
        if self._handle is not None:
            self._handle.close()  # type: ignore[attr-defined]
            self._handle = None

    def write(self, frame: RawFrame) -> None:
        """Append one frame with the timestamps it was received with."""
        self._write_line(
            json.dumps(
                {
                    "received_at": frame.received_at_iso,
                    "received_monotonic_ns": frame.received_monotonic_ns,
                    "channel": frame.channel,
                    "sha256": frame.payload_sha256,
                    "frame": json.loads(frame.payload)
                    if _looks_like_json(frame.payload)
                    else frame.payload,
                },
                separators=(",", ":"),
            )
        )
        self._count += 1

    def _write_line(self, line: str) -> None:
        if self._handle is None:
            raise CaptureError("SessionWriter used outside its context manager")
        self._handle.write(line + "\n")  # type: ignore[attr-defined]
        self._handle.flush()  # type: ignore[attr-defined]

    @property
    def frames_written(self) -> int:
        return self._count


def _looks_like_json(payload: str) -> bool:
    stripped = payload.lstrip()
    return stripped.startswith(("{", "["))


SYNTHETIC_FALLBACK_BASE = datetime(2000, 1, 1, tzinfo=UTC)
"""Receipt base for the first bare frame when nothing carries a venue time.

Fixed and far from any real session, so such a timestamp is obvious on sight.
Only reached at the start of a file whose opening frames carry no time at all —
a subscription acknowledgement, say. Subsequent timeless frames carry forward
from the previous frame instead, because a session's receipt times must be
monotonic: `ReplayClock` refuses to move backwards, and mixing a derived 2026
timestamp with a fixed 2000 one inside one file produced exactly that error
during development.
"""

SYNTHETIC_ANCHOR_CUTOFF = datetime(2001, 1, 1, tzinfo=UTC)
"""Receipts before this are treated as the fallback base rather than real.

Used only to recognise leading fallback frames so they can be re-anchored. Any
genuine capture is decades later, so the test cannot misfire on real data.
"""

SYNTHETIC_RECEIPT_DELAY_MS = 1
"""Offset from the venue timestamp when synthesizing a receipt time.

Where a bare frame carries a venue timestamp, the synthetic receipt is derived
from it rather than from a fixed epoch. Two reasons: the resulting
source-to-receipt delay is plausible, so the quality engine is not flagging an
artifact of this constant as clock skew on every event; and the value stays a
pure function of the frame, so replay remains deterministic.

It is still synthetic. One millisecond is not what the network did.
"""


@dataclass(frozen=True, slots=True)
class CapturedSession:
    """A loaded capture."""

    header: CaptureHeader | None
    frames: tuple[IncomingFrame, ...]
    path: Path
    malformed_lines: tuple[int, ...] = ()
    """Line numbers that could not be read.

    Reported rather than raised: a capture with one bad line is still worth
    replaying, and knowing which line failed is more useful than refusing the
    whole file. An unreadable *header* is different — that is a format problem.
    """

    synthetic_receipts: bool = False
    """True when receipt times were synthesized rather than captured.

    A bare venue frame carries the venue's timestamp but not ours, so replaying
    one requires inventing a receipt time. That is fine for testing parsing and
    normalization, and useless for anything timing-related: the
    source-to-receipt delay of a synthetic session is an artifact of this
    constant, not a measurement. Flagged here so a latency analysis can refuse
    such a session rather than quietly report a fabricated number — which is
    precisely the confusion ADR-007 and TBIE v1.1 §18 exist to prevent.
    """

    @property
    def span(self) -> tuple[datetime, datetime] | None:
        """First and last receipt time, when the session has frames."""
        if not self.frames:
            return None
        return (
            self.frames[0].receipt.local_receive_time,
            self.frames[-1].receipt.local_receive_time,
        )

    @property
    def duration_seconds(self) -> float:
        span = self.span
        return 0.0 if span is None else (span[1] - span[0]).total_seconds()


def load_session(path: Path) -> CapturedSession:
    """Load a capture file.

    Frames are returned in file order, which is receipt order. The loader does
    not sort them: reordering would hide a recorder that delivered frames out of
    order, and that is a defect worth seeing rather than smoothing over.
    """
    if not path.is_file():
        raise CaptureError(f"capture file does not exist: {path}")

    header: CaptureHeader | None = None
    frames: list[IncomingFrame] = []
    malformed: list[int] = []
    synthesized = 0
    last_receipt: datetime | None = None

    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("//"):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            malformed.append(number)
            continue

        if not isinstance(payload, dict):
            malformed.append(number)
            continue

        if "capture_header" in payload:
            if number != 1:
                raise CaptureError(
                    f"{path}: capture_header must be the first line, found it at {number}"
                )
            inner = payload["capture_header"]
            if not isinstance(inner, dict):
                raise CaptureError(f"{path}: capture_header is not an object")
            header = CaptureHeader.from_payload(inner)
            continue

        if "frame" in payload:
            frame = _envelope_to_frame(payload, path, number)
            if frame is None:
                malformed.append(number)
            else:
                frames.append(frame)
            continue

        # A bare venue frame. Accepted so hand-written fixtures stay short,
        # with a receipt time derived from the frame itself — deterministic, and
        # flagged on the session so nothing mistakes it for a measurement.
        bare = _bare_frame(text, len(frames), _venue_time_ms(payload), last_receipt)
        last_receipt = bare.receipt.local_receive_time
        frames.append(bare)
        synthesized += 1

    return CapturedSession(
        header=header,
        frames=_anchor_leading_frames(frames),
        path=path,
        malformed_lines=tuple(malformed),
        synthetic_receipts=synthesized > 0,
    )


def _anchor_leading_frames(frames: list[IncomingFrame]) -> tuple[IncomingFrame, ...]:
    """Pull leading timeless frames up next to the first timed one.

    A file that opens with a subscription acknowledgement gets the fixed
    fallback base for that frame, then jumps to the venue's real time on the
    next — reporting a session duration of decades. The frames are in the right
    order and the replay is correct, but the duration is nonsense, and this
    number lands in an evidence artifact where someone will read it.

    So leading fallback frames are re-anchored to just before the first derived
    receipt. Order is preserved, determinism is preserved, and the reported span
    describes the session rather than the constant.
    """
    if not frames:
        return ()

    leading = 0
    while (
        leading < len(frames)
        and frames[leading].receipt.local_receive_time < SYNTHETIC_ANCHOR_CUTOFF
    ):
        leading += 1

    if leading == 0 or leading == len(frames):
        return tuple(frames)

    anchor = frames[leading].receipt.local_receive_time
    rebased: list[IncomingFrame] = []
    for index, frame in enumerate(frames[:leading]):
        offset = timedelta(milliseconds=(leading - index) * SYNTHETIC_RECEIPT_DELAY_MS)
        rebased.append(
            IncomingFrame(
                payload=frame.payload,
                receipt=frame.receipt.model_copy(update={"local_receive_time": anchor - offset}),
            )
        )
    return (*rebased, *frames[leading:])


def _venue_time_ms(payload: dict[str, Any]) -> int | None:
    """Find the venue timestamp in a bare frame, if it has one.

    Handles both shapes the venue uses: `data` as an object carrying `time`
    (quotes, book, context) and `data` as a list of records each carrying one
    (trades). A frame with neither returns None.
    """
    data = payload.get("data")
    if isinstance(data, dict):
        value = data.get("time")
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        value = data[0].get("time")
    else:
        return None
    return value if isinstance(value, int) and value > 0 else None


def _bare_frame(
    text: str, index: int, venue_time_ms: int | None, previous: datetime | None
) -> IncomingFrame:
    """Wrap a bare venue frame with a synthetic receipt time.

    Receipt times across a file must be non-decreasing, so a frame with no
    venue timestamp carries forward from the previous frame rather than
    restarting at a fixed base. A derived time that would move backwards — an
    out-of-order fixture — is also clamped forward, since the ordering defect
    belongs to the fixture and should not make the whole file unreplayable.
    """
    if venue_time_ms is not None:
        received = datetime.fromtimestamp(venue_time_ms / 1000, tz=UTC) + timedelta(
            milliseconds=SYNTHETIC_RECEIPT_DELAY_MS
        )
    elif previous is not None:
        received = previous + timedelta(milliseconds=SYNTHETIC_RECEIPT_DELAY_MS)
    else:
        received = SYNTHETIC_FALLBACK_BASE

    if previous is not None and received < previous:
        received = previous + timedelta(milliseconds=SYNTHETIC_RECEIPT_DELAY_MS)

    return IncomingFrame(
        payload=text,
        receipt=EventTimestamps(
            local_receive_time=received,
            local_receive_monotonic_ns=index * SYNTHETIC_RECEIPT_DELAY_MS * 1_000_000,
        ),
    )


def _envelope_to_frame(payload: dict[str, object], path: Path, number: int) -> IncomingFrame | None:
    frame_payload = payload.get("frame")
    if frame_payload is None:
        return None

    received_at = payload.get("received_at")
    if received_at is None:
        logger.warning(
            "capture_line_without_receipt_time",
            extra={"path": str(path), "line": number},
        )
        return None

    try:
        moment = datetime.fromisoformat(str(received_at))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)

    text = (
        frame_payload
        if isinstance(frame_payload, str)
        else json.dumps(frame_payload, separators=(",", ":"))
    )
    return IncomingFrame(
        payload=text,
        receipt=EventTimestamps(
            local_receive_time=moment,
            local_receive_monotonic_ns=int(str(payload.get("received_monotonic_ns", 0))),
        ),
    )


class CapturedSessionSource:
    """A `MessageSource` over a loaded capture.

    Replays the frames with their captured receipt timestamps, so the recorder
    observes the session exactly as it originally arrived.
    """

    def __init__(self, session: CapturedSession, *, name: str | None = None) -> None:
        self._session = session
        self._name = name or (
            session.header.source if session.header else f"capture:{session.path.name}"
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def session(self) -> CapturedSession:
        return self._session

    async def frames(self) -> AsyncIterator[IncomingFrame]:
        for frame in self._session.frames:
            yield frame


def iter_frames(session: CapturedSession) -> Iterator[IncomingFrame]:
    """Synchronous iteration, for report generation."""
    yield from session.frames
