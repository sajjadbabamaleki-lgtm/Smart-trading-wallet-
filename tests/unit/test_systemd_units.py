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

import re
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
