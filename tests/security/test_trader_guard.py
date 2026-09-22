"""The trader's mainnet guard and key handling."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from libs.config import load_settings
from services.trader.cli import main
from services.trader.config import (
    Network,
    TraderConfigError,
    TraderSettings,
    VenueName,
    load_trader_settings,
)
from services.trader.venues.factory import build_venue

API_KEY = "0x" + "22" * 32


def test_defaults_to_hyperliquid_testnet() -> None:
    settings = load_trader_settings()
    assert settings.venue is VenueName.HYPERLIQUID
    assert settings.network is Network.TESTNET


def test_mainnet_alone_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADER_NETWORK", "MAINNET")
    with pytest.raises(TraderConfigError, match="TRADER_ALLOW_MAINNET"):
        load_trader_settings()


def test_mainnet_requires_both_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADER_NETWORK", "MAINNET")
    monkeypatch.setenv("TRADER_ALLOW_MAINNET", "true")
    assert load_trader_settings().is_mainnet


@pytest.mark.parametrize(
    ("name", "value"), [("TRADER_DEFAULT_RISK_PERCENT", "6"), ("TRADER_MAX_LEVERAGE", "50")]
)
def test_limits_cannot_exceed_hard_bounds(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(TraderConfigError):
        load_trader_settings()


def test_api_key_is_not_exposed_by_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADER_API_PRIVATE_KEY", API_KEY)
    settings = load_trader_settings()
    assert API_KEY not in repr(settings)
    assert API_KEY not in str(settings.model_dump())


def test_trader_file_is_separate_from_the_research_settings(tmp_path: Path) -> None:
    # The research Settings rejects unknown keys in `.env`, so the trader must
    # never need to put its keys there.
    (tmp_path / ".env").write_text("STW_EXECUTION_ENVIRONMENT=DEVELOPMENT\n")
    (tmp_path / ".env.trader").write_text("TRADER_NETWORK=TESTNET\nTRADER_ACCOUNT=x\n")
    load_settings()
    assert load_trader_settings().account == "x"


def test_cli_without_an_account_fails_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["status"]) == 2
    assert "TRADER_ACCOUNT" in capsys.readouterr().err


def test_sending_orders_requires_a_key() -> None:
    settings = TraderSettings(account="0x" + "11" * 20)
    with pytest.raises(TraderConfigError, match="TRADER_API_PRIVATE_KEY"):
        build_venue(settings, needs_signer=True)


def test_malformed_hyperliquid_account_is_refused_before_any_request() -> None:
    settings = TraderSettings(account="not-an-address", api_private_key=SecretStr(API_KEY))
    with pytest.raises(TraderConfigError, match="not a Hyperliquid account"):
        build_venue(settings, needs_signer=True)
