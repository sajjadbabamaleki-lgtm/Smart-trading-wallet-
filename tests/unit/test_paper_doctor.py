"""The diagnostic is the thing you run when nothing else works, so test it.

CLAUDE.md forbids asking the owner to read output a program could summarise,
and `make paper-status` prints forty lines of journalctl. This script is the
summariser that rule asks for — and a summariser that lies is worse than the
forty lines, because it ends the investigation.

Each case puts a fake `systemctl` on PATH and runs the real script against a
real git repository, so the verdicts are exercised rather than asserted about.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


def _run(
    command: list[str],
    *,
    check: bool = False,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Every argument list in this file is a literal written above it.

    S603 asks whether the input is untrusted; it is not, and saying so once
    here beats a suppression on each of the seven call sites. Named arguments
    rather than **kwargs so the return type stays `CompletedProcess[str]`
    under --strict instead of decaying to Any.
    """
    return subprocess.run(  # noqa: S603
        command, check=check, capture_output=capture, text=True, env=env
    )


REPO = Path(__file__).resolve().parents[2]
DOCTOR = REPO / "infrastructure" / "scripts" / "paper_doctor.sh"
REPORT = "docs/evidence/build-0.1/paper/report.txt"

# A service that is fine: armed, next fire on a candle close, uv reachable.
HEALTHY = {
    "is-active stw-paper.timer": "active",
    "show stw-paper.timer -p NextElapseUSecRealtime --value": "Mon 2026-09-21 08:05:00 UTC",
    "show stw-paper.service -p Result --value": "success",
    "show stw-paper.service -p ExecMainExitTimestamp --value": "Mon 2026-09-21 04:06:00 UTC",
    # FAKEBIN is replaced with the directory holding the fake uv, so the
    # healthy case really does find it rather than being asserted to.
    "show stw-paper.service -p Environment --value": "PATH=FAKEBIN STW_TRADING_ENABLED=false",
}


@pytest.fixture
def doctor(tmp_path: Path) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run the real script in a throwaway clone with a fake systemctl."""
    work = tmp_path / "repo"
    (work / "infrastructure" / "scripts").mkdir(parents=True)
    shutil.copy(DOCTOR, work / "infrastructure" / "scripts" / DOCTOR.name)
    (work / REPORT).parent.mkdir(parents=True)
    (work / REPORT).write_text("Paper trading, as of 2026-09-21 04:06 UTC\n")

    git = ["git", "-C", str(work)]
    _run([*git, "init", "-q", "-b", "main"], check=True)
    _run([*git, "add", "-A"], check=True)
    _run(
        [*git, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"],
        check=True,
    )
    # A remote-tracking ref pointing at the same commit: nothing unpushed.
    _run([*git, "update-ref", "refs/remotes/origin/main", "HEAD"], check=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Something for `command -v uv` to find when the fake PATH is /fakebin.
    fake_uv_dir = tmp_path / "fakebin"
    fake_uv_dir.mkdir()
    (fake_uv_dir / "uv").write_text("#!/bin/sh\n")
    (fake_uv_dir / "uv").chmod(0o755)

    def run(
        answers: dict[str, str] | None = None,
        unpushed: int = 0,
        report: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        table = {
            query: answer.replace("FAKEBIN", str(fake_uv_dir))
            for query, answer in {**HEALTHY, **(answers or {})}.items()
        }
        # A fake systemctl that answers by exact argument string, and says
        # nothing for anything it was not told about.
        script = ["#!/bin/sh", 'case "$*" in']
        for query, answer in table.items():
            script.append(f'  "{query}") echo "{answer}" ;;')
        script += ["  *) exit 1 ;;", "esac"]
        (bin_dir / "systemctl").write_text("\n".join(script) + "\n")
        (bin_dir / "systemctl").chmod(0o755)

        for index in range(unpushed):
            (work / f"extra{index}").write_text("x")
            _run([*git, "add", "-A"], check=True)
            _run(
                [*git, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "more"],
                check=True,
            )
        if report is not None:
            (work / REPORT).write_text(report)

        env = {**os.environ, "PATH": f"{bin_dir}:{fake_uv_dir}:{os.environ['PATH']}"}
        return _run(
            ["bash", str(work / "infrastructure" / "scripts" / DOCTOR.name)],
            capture=True,
            env=env,
        )

    return run


def test_a_healthy_loop_reports_nothing_wrong(
    doctor: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = doctor()
    assert result.returncode == 0, result.stdout
    assert "nothing wrong" in result.stdout
    assert "timer        armed" in result.stdout
    assert "2026-09-21 08:05 UTC" in result.stdout


def test_a_disarmed_timer_is_named_with_its_remedy(
    doctor: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = doctor({"is-active stw-paper.timer": "inactive"})
    assert result.returncode == 1
    assert "NOT armed" in result.stdout
    assert "make paper-install" in result.stdout


def test_the_old_local_time_schedule_is_caught(
    doctor: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """The timer bug, asked as a question the owner can answer from one line.

    02:05 UTC is what `OnCalendar=00/4:05` produced on a UTC+2 host. It is not
    a candle close, and that is the whole tell.
    """
    result = doctor(
        {"show stw-paper.timer -p NextElapseUSecRealtime --value": "Mon 2026-09-21 02:05:00 UTC"}
    )
    assert result.returncode == 1
    assert "not a 4h candle close" in result.stdout
    assert "the timer file is the old one" in result.stdout


def test_a_service_without_path_is_caught(
    doctor: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """The outage of 2026-09-20, asked directly instead of inferred."""
    result = doctor({"show stw-paper.service -p Environment --value": "STW_TRADING_ENABLED=false"})
    assert result.returncode == 1
    assert "sets no PATH" in result.stdout


def test_uv_missing_from_the_services_own_path_is_caught(
    doctor: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """The shell running the doctor may have uv when the service does not.

    This is precisely why the outage was hard to see: `make paper-tick` from a
    login shell worked every time.
    """
    result = doctor({"show stw-paper.service -p Environment --value": "PATH=/nowhere"})
    assert result.returncode == 1
    assert "not found on the service" in result.stdout


def test_an_unpushed_tick_is_visible(
    doctor: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """A tick that ran and could not push is invisible from the repository.

    That is the one failure mode a reader on the other end cannot detect, so
    the diagnostic has to be the thing that detects it.
    """
    result = doctor(unpushed=2)
    assert result.returncode == 1
    assert "2 commit(s) written but never pushed" in result.stdout


def test_a_report_holding_an_error_is_not_counted_as_a_record(
    doctor: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """What the broken tick actually left behind on 2026-09-20 at 10:05."""
    result = doctor(report="infrastructure/scripts/paper_tick.sh: line 72: uv: command not found\n")
    assert result.returncode == 1
    assert "holds an error, not a record" in result.stdout


def test_every_problem_is_counted_not_just_the_first(
    doctor: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """A diagnostic that stops at the first fault sends the owner round twice."""
    result = doctor(
        {
            "is-active stw-paper.timer": "inactive",
            "show stw-paper.service -p Environment --value": "PATH=/nowhere",
        },
        unpushed=1,
    )
    assert result.returncode == 1
    assert "3 problem(s)" in result.stdout
