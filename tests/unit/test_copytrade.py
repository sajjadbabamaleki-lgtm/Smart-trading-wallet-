"""The copy-trading persistence study."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from services.lab import copytrade

NOW = datetime(2026, 9, 22, tzinfo=UTC)
DAY = timedelta(days=1)


def portfolio(equity: float, daily_a: float, daily_b: float) -> Any:
    """Daily history over 200 days: a PnL rate per day in period A and in period B."""
    selection = NOW - copytrade.PERIOD
    points, pnl = [], 0.0
    for d in range(200, -1, -1):
        t = NOW - DAY * d
        points.append((int(t.timestamp() * 1000), pnl))
        pnl += equity * (daily_a if t < selection else daily_b)
    history = {
        "accountValueHistory": [[t, str(equity)] for t, _ in points],
        "pnlHistory": [[t, str(p)] for t, p in points],
        "vlm": "0",
    }
    return [["day", {}], ["allTime", history], ["perpAllTime", history]]


def histories(persistent: bool) -> dict[str, copytrade.History]:
    out = {}
    for k in range(40):
        skill = (k - 20) / 10_000
        later = skill if persistent else -skill
        out[f"0x{k:02x}"] = copytrade.parse_portfolio(portfolio(50_000, skill, later))
    return out


def test_persistent_winners_pass() -> None:
    study = copytrade.run_study(histories(True), now=NOW)
    assert study.spearman == pytest.approx(1.0)
    assert all(study.checks.values())


def test_reversing_winners_fail() -> None:
    study = copytrade.run_study(histories(False), now=NOW)
    assert study.spearman < 0
    assert not any(study.checks.values())


def test_returns_use_pnl_over_starting_equity() -> None:
    history = copytrade.parse_portfolio(portfolio(10_000, 0.001, -0.002))
    o = copytrade.outcome("x", history, NOW - copytrade.PERIOD)
    assert o is not None
    assert o.return_a == pytest.approx(0.09)
    assert o.return_b == pytest.approx(-0.18)


def test_traders_without_covering_history_or_equity_are_skipped() -> None:
    short = copytrade.parse_portfolio(portfolio(10_000, 0.001, 0.001))
    short = copytrade.History(short.equity[-50:], short.pnl[-50:])
    assert copytrade.outcome("x", short, NOW - copytrade.PERIOD) is None
    small = copytrade.parse_portfolio(portfolio(500, 0.001, 0.001))
    assert copytrade.outcome("x", small, NOW - copytrade.PERIOD) is None


def test_pool_is_the_largest_accounts_not_the_most_profitable() -> None:
    rows = {
        "leaderboardRows": [
            {"ethAddress": "0xA", "accountValue": "5000"},
            {"ethAddress": "0xB", "accountValue": "90000"},
            {"ethAddress": "0xC", "accountValue": "20000"},
            {"ethAddress": "0xD", "accountValue": "bad"},
        ]
    }
    pool = copytrade.select_pool(copytrade.parse_leaderboard(rows), size=5)
    assert [c.address for c in pool] == ["0xb", "0xc"]


def test_spearman_handles_ties_and_constants() -> None:
    rho, p = copytrade.spearman([1, 2, 2, 3], [1, 2, 2, 3])
    assert rho == pytest.approx(1.0) and p < 0.1
    assert copytrade.spearman([1, 1, 1], [1, 2, 3]) == (0.0, 1.0)


def test_fetch_caches_readable_histories_and_the_cli_reports(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.lab import cli  # noqa: PLC0415

    rows = [{"ethAddress": f"0x{k:02x}", "accountValue": str(50_000 + k)} for k in range(40)]

    class Info:
        def portfolio(self, user: str) -> Any:
            if user == "0x00":
                return {"unexpected": True}
            k = int(user, 16)
            return portfolio(50_000, (k - 20) / 10_000, (k - 20) / 10_000)

    pool, failed = copytrade.fetch(
        Info(), get_json=lambda _url: {"leaderboardRows": rows}, sleep=lambda _s: None
    )
    assert pool == 40 and failed == ["0x00"]
    assert json.loads((copytrade.COPY_DIR / "pool.json").read_text())[0] == "0x27"

    monkeypatch.setattr(cli, "datetime", type("D", (), {"now": staticmethod(lambda _tz: NOW)}))
    assert cli.main(["copy-study"]) == 0
    out = capsys.readouterr().out
    assert "39 of 39 accounts" in out and "PASSED" in out


def test_copy_study_refuses_without_data(capsys: pytest.CaptureFixture[str]) -> None:
    from services.lab.cli import main  # noqa: PLC0415

    assert main(["copy-study"]) == 1
    assert "copy-fetch" in capsys.readouterr().err
