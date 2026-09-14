"""The acceptance runner's own mechanics.

`infrastructure/scripts/accept_m1_m2.sh` now carries the M1/M2 verification for
both the local path and the workflow, so a defect in it is a defect in
acceptance itself. Shell has no type checker and no import that fails loudly;
these tests are what stands in for one.

Nothing here starts Docker or reaches the network. Every case exits during
argument handling, before the script touches anything.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "infrastructure" / "scripts" / "accept_m1_m2.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "acceptance-m1-m2.yml"
MAKEFILE = REPO_ROOT / "Makefile"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash is unavailable")


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the script. Only ever called with arguments that exit early."""
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), *args],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
        check=False,  # a non-zero exit is what several of these assert on
    )


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111, "the script must be executable"


def test_script_parses() -> None:
    """`bash -n` over the whole script.

    A syntax error here would surface as an acceptance run that dies on its
    first line, which reads like an infrastructure failure rather than a typo.
    """
    result = subprocess.run(  # noqa: S603
        ["bash", "-n", str(SCRIPT)],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
        check=False,  # the assertion below reports the syntax error, not a traceback
    )
    assert result.returncode == 0, result.stderr


def test_help_exits_clean_and_states_the_safety_property() -> None:
    result = run_script("--help")
    assert result.returncode == 0
    assert "read-only" in result.stdout.lower()
    assert "no order is ever submitted" in result.stdout.lower()


def test_unknown_option_is_refused() -> None:
    """An unrecognised flag must not be silently ignored.

    Silently ignoring `--minuts 120` would produce a 15-minute run reported as
    a 120-minute one — a wrong number in an evidence artifact, which is the
    specific failure this project exists to avoid.
    """
    result = run_script("--not-a-real-option")
    assert result.returncode == 2
    assert "unknown option" in result.stderr


def test_unknown_market_data_environment_is_refused() -> None:
    result = run_script("--market-data", "MAINNET")
    assert result.returncode == 2
    assert "MAINNET_PUBLIC or TESTNET" in result.stderr


@pytest.mark.parametrize("environment", ["MAINNET_PUBLIC", "TESTNET"])
def test_permitted_market_data_environments_are_accepted(environment: str) -> None:
    """Both permitted values survive parsing.

    Checked through `--help`, which exits before the script does anything, so
    this asserts the argument handling and nothing else.
    """
    result = run_script("--market-data", environment, "--help")
    assert result.returncode == 0


def test_workflow_delegates_to_the_script() -> None:
    """The workflow must call the script, at a path that exists.

    The two used to hold separate copies of the same steps. They cannot drift
    now, but a renamed script would leave the workflow calling nothing — and a
    workflow that quietly verifies nothing is worse than one that fails.
    """
    workflow = WORKFLOW.read_text()
    relative = "infrastructure/scripts/accept_m1_m2.sh"
    assert relative in workflow
    assert (REPO_ROOT / relative).is_file()


def test_workflow_does_not_restate_the_acceptance_steps() -> None:
    """Guards the single-path property rather than trusting it.

    If these reappear in the workflow, there are two acceptance implementations
    again and they will eventually disagree.
    """
    workflow = WORKFLOW.read_text()
    for restated in ("docker compose", "verify_stack.py", "acceptance_m1_m2.py"):
        assert restated not in workflow, (
            f"{restated!r} is back in the workflow; acceptance steps belong in the script"
        )


def test_make_accept_calls_the_script() -> None:
    makefile = MAKEFILE.read_text()
    assert "accept:" in makefile
    assert "infrastructure/scripts/accept_m1_m2.sh" in makefile
