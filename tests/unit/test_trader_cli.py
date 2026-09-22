"""The trader CLI end to end, against the in-memory venue."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from solders.keypair import Keypair

from libs.exchange.pacifica.client import PacificaClient
from services.trader import cli
from tests.unit.test_trader_flow import ACCOUNT, AGENT, FakeVenue


@pytest.fixture
def venue(monkeypatch: pytest.MonkeyPatch) -> FakeVenue:
    fake = FakeVenue()

    def client_factory(*args: Any, **kwargs: Any) -> PacificaClient:
        return PacificaClient(*args, transport=httpx.MockTransport(fake.handler), **kwargs)

    monkeypatch.setattr(cli, "PacificaClient", client_factory)
    monkeypatch.setattr("services.trader.trader.FILL_CONFIRM_INTERVAL_SECONDS", 0)
    monkeypatch.setenv("PACIFICA_ACCOUNT", ACCOUNT)
    monkeypatch.setenv("PACIFICA_AGENT_PRIVATE_KEY", str(AGENT))
    return fake


def test_open_without_execute_is_a_dry_run(
    venue: FakeVenue, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["open", "--side", "long", "--sl", "145", "--tp", "160"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "loss at stop" in out
    assert "reward : risk" in out
    assert venue.posts == []


def test_open_execute_then_status_then_close(
    venue: FakeVenue, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["open", "--side", "short", "--sl", "155", "--rr", "2", "--execute"]) == 0
    out = capsys.readouterr().out
    assert "SENT" in out
    assert "filled @ 150" in out
    assert "take profit       140" in out  # 150 - 2 x (155 - 150)
    assert "WARNING" not in out

    assert cli.main(["status"]) == 0
    status = capsys.readouterr().out
    assert "SOL SHORT" in status
    assert "trigger 155" in status

    assert cli.main(["close", "--execute"]) == 0
    assert "close SOL SHORT" in capsys.readouterr().out
    assert venue.positions == []


def test_refusal_exits_non_zero_with_the_reason(
    venue: FakeVenue, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["open", "--side", "long", "--sl", "151"]) == 1
    assert "stop loss must be below" in capsys.readouterr().err


def test_tpsl_needs_a_price(venue: FakeVenue, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["open", "--side", "long", "--sl", "145", "--execute"]) == 0
    assert cli.main(["tpsl", "--execute"]) == 1
    assert "--sl and/or --tp" in capsys.readouterr().err
    assert cli.main(["tpsl", "--sl", "148", "--execute"]) == 0


def test_mainnet_asks_for_confirmation(
    venue: FakeVenue, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PACIFICA_NETWORK", "MAINNET")
    monkeypatch.setenv("PACIFICA_ALLOW_MAINNET", "true")
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert cli.main(["open", "--side", "long", "--sl", "145", "--execute"]) == 1
    assert "not confirmed" in capsys.readouterr().err
    assert venue.posts == []


def test_main_wallet_key_is_warned_about(
    venue: FakeVenue, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    main_key = Keypair()
    monkeypatch.setenv("PACIFICA_ACCOUNT", str(main_key.pubkey()))
    monkeypatch.setenv("PACIFICA_AGENT_PRIVATE_KEY", str(main_key))
    assert cli.main(["open", "--side", "long", "--sl", "145"]) == 0
    assert "Use an API agent key" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["abc", "-5", "0", "nan"])
def test_invalid_prices_are_rejected_by_the_parser(venue: FakeVenue, value: str) -> None:
    with pytest.raises(SystemExit):
        cli.main(["open", "--side", "long", "--sl", value])
