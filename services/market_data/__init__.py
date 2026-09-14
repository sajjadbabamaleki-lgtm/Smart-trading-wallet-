"""Market data recorder.

Build 0.1 Rev.2 §19 defines the pipeline:

    CONNECT -> SUBSCRIBE -> CAPTURE RAW -> TIMESTAMP -> VALIDATE
    -> NORMALIZE -> PERSIST -> MONITOR

with reconnect and gap detection required from the beginning rather than added
later. Rev.1 §36 is explicit about what counts as done: screenshots are not
evidence, automated logs and tests are.

The guiding standard is Phase 3 §29 — a recorder that silently misses twenty
minutes of market data is worse than one that explicitly reports a twenty-minute
gap, because research over the silent version produces a confident wrong answer.
"""

from services.market_data.capture import (
    CapturedSession,
    CapturedSessionSource,
    CaptureError,
    CaptureHeader,
    SessionWriter,
    load_session,
)
from services.market_data.dedup import DuplicateDetector
from services.market_data.gaps import GapDetector, GapKind, GapReport, Heartbeat
from services.market_data.monitor import FreshnessSnapshot, Monitor, MonitorCheck
from services.market_data.quality import QualityEngine, QualityVerdict
from services.market_data.recorder import Recorder, RecorderMetrics
from services.market_data.registry import (
    BackfillStatus,
    GapRegistry,
    GapSummary,
    InMemoryGapRegistry,
    RegisteredGap,
)
from services.market_data.replay import (
    ReplayComparison,
    ReplayEngine,
    ReplayReport,
    ReplayResult,
    verify_determinism,
)
from services.market_data.sinks import InMemorySink, RawFrame, Sink
from services.market_data.source import FixtureSource, IncomingFrame, IterableSource, MessageSource
from services.market_data.state import RecorderState, StateMachine, TransitionError

__all__ = [
    "BackfillStatus",
    "CaptureError",
    "CaptureHeader",
    "CapturedSession",
    "CapturedSessionSource",
    "DuplicateDetector",
    "FixtureSource",
    "FreshnessSnapshot",
    "GapDetector",
    "GapKind",
    "GapRegistry",
    "GapReport",
    "GapSummary",
    "Heartbeat",
    "InMemoryGapRegistry",
    "InMemorySink",
    "IncomingFrame",
    "IterableSource",
    "MessageSource",
    "Monitor",
    "MonitorCheck",
    "QualityEngine",
    "QualityVerdict",
    "RawFrame",
    "Recorder",
    "RecorderMetrics",
    "RecorderState",
    "RegisteredGap",
    "ReplayComparison",
    "ReplayEngine",
    "ReplayReport",
    "ReplayResult",
    "SessionWriter",
    "Sink",
    "StateMachine",
    "TransitionError",
    "load_session",
    "verify_determinism",
]
