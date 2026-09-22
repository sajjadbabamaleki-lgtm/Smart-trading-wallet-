"""Shared fixtures.

Environment variables are cleared for every test: a `STW_`-prefixed variable
leaking in from the developer's shell would make settings tests pass or fail
depending on who ran them, which is exactly the non-determinism these tests
exist to catch (Build 0.1 Rev.1 §64).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from libs.domain.clock import ManualClock
from libs.domain.timestamps import EventTimestamps

FIXED_TIME = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    for key in list(os.environ):
        if key.startswith(("STW_", "PACIFICA_")):
            monkeypatch.delenv(key, raising=False)
    # Point the env_file at an empty directory so a developer's real .env is
    # never read during a test run.
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(FIXED_TIME)


@pytest.fixture
def timestamps() -> EventTimestamps:
    return EventTimestamps(
        local_receive_time=FIXED_TIME,
        local_receive_monotonic_ns=1_000_000,
        exchange_time=FIXED_TIME,
    )
