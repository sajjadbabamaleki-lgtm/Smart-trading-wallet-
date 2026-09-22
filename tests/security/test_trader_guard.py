"""The trader's mainnet guard and key handling."""

from __future__ import annotations

from pathlib import Path

import pytest
from solders.keypair import Keypair

from libs.config import load_settings
from libs.exchange.pacifica.client import PacificaNetwork
from services.trader.cli import main
from services.trader.config import TraderConfigError, load_trader_settings


def test_defaults_to_testnet() -> None:
    assert load_trader_settings().network is PacificaNetwork.TESTNET


def test_mainnet_alone_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PACIFICA_NETWORK", "MAINNET")
    with pytest.raises(TraderConfigError, match="PACIFICA_ALLOW_MAINNET"):
        load_trader_settings()


def test_mainnet_requires_both_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PACIFICA_NETWORK", "MAINNET")
    monkeypatch.setenv("PACIFICA_ALLOW_MAINNET", "true")
    assert load_trader_settings().network is PacificaNetwork.MAINNET


@pytest.mark.parametrize(("key", "value"), [("RISK_PERCENT", "6"), ("MAX_LEVERAGE", "50")])
def test_limits_cannot_exceed_hard_bounds(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    name = "PACIFICA_DEFAULT_RISK_PERCENT" if key == "RISK_PERCENT" else f"PACIFICA_{key}"
    monkeypatch.setenv(name, value)
    with pytest.raises(TraderConfigError):
        load_trader_settings()


def test_agent_key_is_not_exposed_by_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = str(Keypair())
    monkeypatch.setenv("PACIFICA_AGENT_PRIVATE_KEY", secret)
    settings = load_trader_settings()
    assert secret not in repr(settings)
    assert secret not in str(settings.model_dump())


def test_trader_file_is_separate_from_the_research_settings(tmp_path: Path) -> None:
    # The research Settings rejects unknown keys in `.env`, so the trader must
    # never need to put its keys there.
    (tmp_path / ".env").write_text("STW_EXECUTION_ENVIRONMENT=DEVELOPMENT\n")
    (tmp_path / ".env.trader").write_text("PACIFICA_NETWORK=TESTNET\nPACIFICA_ACCOUNT=x\n")
    load_settings()
    assert load_trader_settings().account == "x"


def test_cli_without_an_account_fails_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["status"]) == 2
    assert "PACIFICA_ACCOUNT" in capsys.readouterr().err


def test_cli_refuses_to_execute_without_a_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PACIFICA_ACCOUNT", str(Keypair().pubkey()))
    code = main(["open", "--side", "long", "--sl", "140", "--execute"])
    assert code == 2
    assert "no private key" in capsys.readouterr().err
