"""Recorder state machine.

Build 0.1 Rev.1 §27 lists the states and adds one requirement: **no hidden
reconnect behaviour**. A recorder that silently drops to a retry loop looks
healthy from outside while recording nothing, which is the failure mode Phase 3
§29 warns about.

So the state is explicit, every transition is declared, and an undeclared
transition raises rather than being absorbed. That makes the recorder's
behaviour auditable from its own event log: `HEALTHY -> RECONNECTING ->
CONNECTED -> SUBSCRIBING -> HEALTHY` is a legible record of an outage, whereas a
silent internal retry leaves nothing behind.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final


class RecorderState(StrEnum):
    STARTING = "STARTING"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    SUBSCRIBING = "SUBSCRIBING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    RECONNECTING = "RECONNECTING"
    BACKFILLING = "BACKFILLING"
    FAILED = "FAILED"

    @property
    def is_recording(self) -> bool:
        """Whether data is expected to be flowing into storage.

        `DEGRADED` counts: the recorder is still writing, but something about
        the stream is wrong — stale data, a quality problem — and that must be
        visible rather than reported as healthy.
        """
        return self in (RecorderState.HEALTHY, RecorderState.DEGRADED)

    @property
    def is_terminal(self) -> bool:
        return self is RecorderState.FAILED


PERMITTED: Final[dict[RecorderState, frozenset[RecorderState]]] = {
    RecorderState.STARTING: frozenset({RecorderState.CONNECTING, RecorderState.FAILED}),
    RecorderState.CONNECTING: frozenset(
        {RecorderState.CONNECTED, RecorderState.RECONNECTING, RecorderState.FAILED}
    ),
    RecorderState.CONNECTED: frozenset(
        {RecorderState.SUBSCRIBING, RecorderState.RECONNECTING, RecorderState.FAILED}
    ),
    RecorderState.SUBSCRIBING: frozenset(
        {RecorderState.HEALTHY, RecorderState.RECONNECTING, RecorderState.FAILED}
    ),
    RecorderState.HEALTHY: frozenset(
        {
            RecorderState.DEGRADED,
            RecorderState.RECONNECTING,
            RecorderState.BACKFILLING,
            RecorderState.FAILED,
        }
    ),
    RecorderState.DEGRADED: frozenset(
        {
            RecorderState.HEALTHY,
            RecorderState.RECONNECTING,
            RecorderState.BACKFILLING,
            RecorderState.FAILED,
        }
    ),
    # Reconnecting returns to CONNECTING, never straight to HEALTHY: a restored
    # socket still has to resubscribe before data can be expected, and treating
    # the two as one step is how a "connected but silent" recorder happens.
    RecorderState.RECONNECTING: frozenset({RecorderState.CONNECTING, RecorderState.FAILED}),
    RecorderState.BACKFILLING: frozenset(
        {RecorderState.HEALTHY, RecorderState.DEGRADED, RecorderState.FAILED}
    ),
    RecorderState.FAILED: frozenset(),
}
"""Declared transitions. Anything absent here is a defect, not a state."""


class TransitionError(RuntimeError):
    """An undeclared state transition was attempted."""


@dataclass(frozen=True, slots=True)
class Transition:
    """One recorded state change."""

    previous: RecorderState
    current: RecorderState
    at: datetime
    reason: str


@dataclass
class StateMachine:
    """The recorder's state, with its history.

    History is bounded: a recorder reconnecting in a loop for a week must not
    accumulate unbounded memory, and the recent transitions are what diagnosis
    needs.
    """

    state: RecorderState = RecorderState.STARTING
    history: list[Transition] = field(default_factory=list)
    history_limit: int = 512
    on_transition: Callable[[Transition], None] | None = None

    def transition(self, target: RecorderState, *, at: datetime, reason: str) -> Transition:
        """Move to `target`, or raise if that transition is not declared."""
        if target not in PERMITTED[self.state]:
            permitted = ", ".join(sorted(state.value for state in PERMITTED[self.state]))
            raise TransitionError(
                f"{self.state.value} -> {target.value} is not a declared transition; "
                f"permitted: {permitted or 'none (terminal)'}"
            )
        record = Transition(previous=self.state, current=target, at=at, reason=reason)
        self.state = target
        self.history.append(record)
        if len(self.history) > self.history_limit:
            del self.history[: len(self.history) - self.history_limit]
        if self.on_transition is not None:
            self.on_transition(record)
        return record

    def can_transition(self, target: RecorderState) -> bool:
        return target in PERMITTED[self.state]

    @property
    def is_recording(self) -> bool:
        return self.state.is_recording
