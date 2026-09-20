"""The units are configuration, and configuration ships untested by default.

These exist because of one real outage. `stw-paper.service` was written
without `Environment=PATH=`, so systemd ran the tick with its own default
PATH — which has no `/root/.local/bin` — and every `uv run` in the script
failed with `uv: command not found`. The loop was dead for eleven hours and
the report it pushes is the only thing that would have said so.

The recorder and the watchdog both had the line. The new unit did not, and
nothing compared them. That comparison is what this file is.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

UNITS = Path(__file__).resolve().parents[2] / "infrastructure" / "systemd"

# Where uv actually lands. `~/.local/bin` is the installer's default for root;
# some packagings use /usr/local/bin. A unit that names neither cannot run uv
# on either machine.
UV_DIRECTORIES = ("/root/.local/bin", "/usr/local/bin")


def _services() -> list[Path]:
    found = sorted(UNITS.glob("*.service"))
    assert found, f"no unit files under {UNITS}"
    return found


def _directives(unit: Path, name: str) -> list[str]:
    # Comments in these units are long and mention the directives they explain,
    # so match only at the start of a line.
    pattern = re.compile(rf"^{re.escape(name)}=(.*)$", re.MULTILINE)
    return [match.group(1).strip() for match in pattern.finditer(unit.read_text())]


@pytest.mark.parametrize("unit", _services(), ids=lambda path: path.name)
def test_unit_that_runs_uv_sets_path(unit: Path) -> None:
    """A unit whose ExecStart reaches uv must say where uv is.

    systemd does not read a login shell, so nothing puts ~/.local/bin on PATH
    unless the unit does. This is the exact failure that killed the loop.
    """
    exec_start = " ".join(_directives(unit, "ExecStart"))
    script = " ".join(
        (UNITS.parent / "scripts" / word.split("/")[-1]).read_text()
        for word in exec_start.split()
        if word.endswith(".sh") and (UNITS.parent / "scripts" / word.split("/")[-1]).exists()
    )
    if "uv" not in f"{exec_start} {script}".split("#")[0] and "uv " not in script:
        pytest.skip(f"{unit.name} does not invoke uv")

    paths = [value for value in _directives(unit, "Environment") if value.startswith("PATH=")]
    assert paths, (
        f"{unit.name} runs uv but sets no Environment=PATH. Under systemd this "
        f"fails with `uv: command not found` on every call."
    )
    entries = paths[0].removeprefix("PATH=").split(":")
    assert any(directory in entries for directory in UV_DIRECTORIES), (
        f"{unit.name} sets PATH={paths[0]} which contains none of {UV_DIRECTORIES}"
    )


@pytest.mark.parametrize("unit", _services(), ids=lambda path: path.name)
def test_unit_cannot_carry_a_trading_credential(unit: Path) -> None:
    """Non-negotiable 1, enforced on the units rather than trusted.

    An empty value is still a value, and it is what clears a key inherited
    from the shared .env — the mechanism that ended the 39-hour outage.
    """
    environment = _directives(unit, "Environment")
    pinned = {
        entry.split("=", 1)[0]: entry.split("=", 1)[1] for entry in environment if "=" in entry
    }

    assert pinned.get("STW_EXECUTION_ENVIRONMENT") == "DEVELOPMENT", unit.name
    assert pinned.get("STW_TRADING_ENABLED") == "false", unit.name
    assert pinned.get("STW_TESTNET_API_WALLET_ADDRESS") == "", unit.name
    assert pinned.get("STW_TESTNET_API_WALLET_PRIVATE_KEY") == "", unit.name


def test_paper_tick_refuses_before_it_blames_a_venue() -> None:
    """The script must check uv itself, not discover it thirteen times.

    The unit is the fix; this is the message that would have made the outage
    one line to read instead of a screenshot to interpret.
    """
    script = (UNITS.parent / "scripts" / "paper_tick.sh").read_text()
    # Comments in this script quote the messages they explain, so compare
    # positions of real code rather than searching for text anywhere.
    check = script.index('command -v "$UV"')
    first_run = script.index('"$UV" run')
    assert check < first_run, "the uv check must run before the first uv call"

    # And it must stop, rather than counting the missing binary as one more
    # failure alongside the twelve it causes.
    tail = script[check : check + 600]
    assert "exit 1" in tail
    assert "failures=$((failures + 1))" not in tail


def _timers() -> list[Path]:
    found = sorted(UNITS.glob("*.timer"))
    assert found, f"no timer files under {UNITS}"
    return found


@pytest.mark.parametrize("timer", _timers(), ids=lambda path: path.name)
def test_calendar_schedule_is_pinned_to_utc(timer: Path) -> None:
    """A schedule about a venue's clock must be written in the venue's clock.

    systemd reads a bare OnCalendar in the machine's local timezone. The
    recording host runs at UTC+2, so `00/4:05` — written to fire five minutes
    after each 4h candle closes — fired at 22:05, 02:05, 06:05 UTC instead:
    two hours late, every tick. It also moves when the host changes clock,
    which happens twice a year without anyone touching this file.
    """
    for schedule in _directives(timer, "OnCalendar"):
        # A weekday or monotonic-style schedule is about the host's own day
        # and is allowed to follow it. Anything naming a clock time is about
        # the venue.
        assert schedule.endswith(" UTC"), (
            f"{timer.name} has OnCalendar={schedule!r} with no timezone, so "
            f"systemd reads it in the host's local time, not UTC."
        )


@pytest.mark.parametrize("timer", _timers(), ids=lambda path: path.name)
def test_systemd_accepts_the_schedule(timer: Path) -> None:
    """Parse it with systemd's own parser rather than trusting the syntax.

    A rejected OnCalendar does not fail loudly — the timer is installed and
    simply never fires, which is indistinguishable from the outage this file
    exists because of.
    """
    analyze = shutil.which("systemd-analyze")
    if analyze is None:
        pytest.skip("systemd-analyze not installed")

    for schedule in _directives(timer, "OnCalendar"):
        result = subprocess.run(  # noqa: S603
            [analyze, "calendar", schedule],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{timer.name}: {schedule!r} — {result.stderr.strip()}"


def test_the_schedule_means_the_same_thing_on_a_host_that_is_not_utc() -> None:
    """The regression itself, reproduced.

    Every other test here would have passed on the developer's UTC sandbox
    while the server ran two hours late. This one sets the timezone the server
    actually uses and checks the fire times land on the candle closes.
    """
    analyze = shutil.which("systemd-analyze")
    if analyze is None:
        pytest.skip("systemd-analyze not installed")

    schedule = _directives(UNITS / "stw-paper.timer", "OnCalendar")[0]
    result = subprocess.run(  # noqa: S603
        [analyze, "calendar", "--iterations=6", schedule],
        capture_output=True,
        text=True,
        check=True,
        # The host's offset, and one that also changes clock in October, so a
        # schedule that only works on a fixed offset fails here too.
        env={**os.environ, "TZ": "Europe/Berlin"},
    )
    hours = {
        int(match.group(1))
        for match in re.finditer(r"\(in UTC\): \w+ [\d-]+ (\d\d):(\d\d)", result.stdout)
    }
    minutes = {
        int(match.group(2))
        for match in re.finditer(r"\(in UTC\): \w+ [\d-]+ (\d\d):(\d\d)", result.stdout)
    }
    assert hours, f"could not read fire times from:\n{result.stdout}"
    # Binance 4h candles close at these hours UTC, and five minutes after is
    # what the unit says it wants.
    assert hours <= {0, 4, 8, 12, 16, 20}, f"fires at {sorted(hours)} UTC, not on candle closes"
    assert minutes == {5}, f"fires at minute {sorted(minutes)}, not 5"
