"""The tick has to reach the repository, because that is the only way out.

The owner reads the loop through `docs/evidence/build-0.1/paper/report.txt`
and nothing else. A tick that decides correctly and cannot push has, from
every reader's point of view, not run.

It happened. The branch is shared, I pushed three commits to it during a
day's work, and from the first of them every tick's `git push` was rejected
as non-fast-forward. Four reports piled up locally. Worse, the old code only
attempted a push when *this* tick had changed the report, so later ticks said
"nothing to push" and the backlog was silent.

These tests use real git repositories — a bare remote and two clones — so the
rejection is the real one rather than a mock of it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

# Resolved once: a bare "git" is a partial path, and a test that shells out
# should name the binary it means.
GIT = shutil.which("git") or "git"
BASH = shutil.which("bash") or "bash"

REPO = Path(__file__).resolve().parents[2]
TICK = REPO / "infrastructure" / "scripts" / "paper_tick.sh"
REPORT = Path("docs/evidence/build-0.1/paper/report.txt")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        [GIT, "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _commit(cwd: Path, message: str) -> None:
    _git(cwd, "add", "-A")
    _git(cwd, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)


@pytest.fixture
def world(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A bare remote, the server's clone, and somebody else's clone."""
    remote = tmp_path / "remote.git"
    subprocess.run([GIT, "init", "-q", "--bare", "-b", "main", str(remote)], check=True)  # noqa: S603

    server = tmp_path / "server"
    subprocess.run([GIT, "clone", "-q", str(remote), str(server)], check=True)  # noqa: S603
    (server / "infrastructure" / "scripts").mkdir(parents=True)
    (server / REPORT).parent.mkdir(parents=True)
    (server / REPORT).write_text("first report\n")
    _commit(server, "base")
    _git(server, "push", "-q", "origin", "main")

    other = tmp_path / "other"
    subprocess.run([GIT, "clone", "-q", str(remote), str(other)], check=True)  # noqa: S603

    return remote, server, other


def _run_push_stage(server: Path, report_text: str) -> subprocess.CompletedProcess[str]:
    """Run the tick with its work skipped, so only the push path is exercised.

    UV points at a command that does nothing and succeeds, so the refresh and
    decide steps are no-ops; the report is supplied directly. What is under
    test is what happens between writing a report and the remote having it.
    """
    (server / REPORT).write_text(report_text)
    script = server / "infrastructure" / "scripts" / "paper_tick.sh"
    script.write_text(TICK.read_text())
    # Neutralise the parts that need a venue: replace the report-generating
    # command with one that keeps whatever is already in the file.
    body = script.read_text().replace(
        'if ! "$UV" run python -m services.strategy_engine.paper_report_cli > "$REPORT" 2>&1; then',
        "if ! true; then",
    )
    script.write_text(body)

    return subprocess.run(  # noqa: S603
        [BASH, str(script)],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "UV": "true", "HOME": str(server)},
    )


def test_a_report_reaches_the_remote(world: tuple[Path, Path, Path]) -> None:
    remote, server, _ = world
    result = _run_push_stage(server, "second report\n")
    assert "pushed" in result.stdout, result.stdout
    assert _git(remote, "show", "main:" + str(REPORT)) == "second report"


def test_it_recovers_when_the_branch_moved_underneath(
    world: tuple[Path, Path, Path],
) -> None:
    """The actual outage: somebody pushed code, so the tick's push is stale.

    Before the fix this printed "push failed" and the report stayed on the
    server where nobody could read it.
    """
    remote, server, other = world
    (other / "somefile.py").write_text("# work by a person\n")
    _commit(other, "a person pushes code")
    _git(other, "push", "-q", "origin", "main")

    result = _run_push_stage(server, "report written while behind\n")

    assert "push failed" not in result.stdout, result.stdout
    assert "pushed" in result.stdout
    assert _git(remote, "show", "main:" + str(REPORT)) == "report written while behind"
    # The person's commit must survive: rebasing our report onto their work
    # means keeping it, not replacing it.
    assert _git(remote, "show", "main:somefile.py") == "# work by a person"


def test_a_backlog_is_sent_even_when_this_tick_changed_nothing(
    world: tuple[Path, Path, Path],
) -> None:
    """The silent half of the bug.

    Reports committed by earlier ticks sat unpushed while every later tick
    reported "nothing to push", because the old code only tried to push when
    it had just changed the report itself.
    """
    remote, server, other = world
    # Two ticks' worth of reports that never reached the remote.
    for index in range(2):
        (server / REPORT).write_text(f"stuck report {index}\n")
        _commit(server, f"Paper trading report stuck {index}")
    (other / "somefile.py").write_text("# blocks the stale push\n")
    _commit(other, "a person pushes code")
    _git(other, "push", "-q", "origin", "main")

    # This tick writes exactly what is already committed, so it has no change
    # of its own to contribute.
    result = _run_push_stage(server, "stuck report 1\n")

    assert "nothing to push" not in result.stdout, result.stdout
    assert "pushed" in result.stdout
    assert _git(remote, "show", "main:" + str(REPORT)) == "stuck report 1"


def test_a_truly_idle_tick_says_so_and_succeeds(world: tuple[Path, Path, Path]) -> None:
    """Nothing committed and nothing waiting is not a failure."""
    _, server, _ = world
    result = _run_push_stage(server, "first report\n")
    assert "nothing to push" in result.stdout
    assert result.returncode == 0


def test_an_unreachable_remote_leaves_no_rebase_in_progress(
    world: tuple[Path, Path, Path],
) -> None:
    """A half-finished rebase would break every later tick.

    The owner would then be debugging git on a phone instead of reading a
    report, which is the state this whole day was spent getting out of.
    """
    remote, server, _ = world
    _git(server, "remote", "set-url", "origin", str(remote) + "-gone")

    result = _run_push_stage(server, "report with no remote\n")

    assert "push failed" in result.stdout
    assert result.returncode == 1
    assert not (server / ".git" / "rebase-merge").exists()
    assert not (server / ".git" / "rebase-apply").exists()
    # And the decision is still recorded locally, which the message must say.
    assert "committed locally" in result.stdout
