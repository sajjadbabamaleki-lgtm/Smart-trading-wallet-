"""The trader CLI end to end, on Hyperliquid, against the simulated SDK."""

from __future__ import annotations

import pytest

from services.trader import cli
from services.trader.config import TraderSettings
from services.trader.venue import Venue
from services.trader.venues.hyperliquid import HyperliquidVenue
from tests.unit.test_hyperliquid_venue import ACCOUNT, MAIN, FakeHyperliquid


@pytest.fixture
def hl(monkeypatch: pytest.MonkeyPatch) -> FakeHyperliquid:
    monkeypatch.setattr("services.trader.trader.FILL_CONFIRM_INTERVAL_SECONDS", 0)
    monkeypatch.setenv("TRADER_ACCOUNT", ACCOUNT)
    return FakeHyperliquid()


def _run(hl: FakeHyperliquid, argv: list[str]) -> int:
    def factory(settings: TraderSettings, needs_signer: bool) -> tuple[Venue, bool]:
        venue = HyperliquidVenue(
            info=hl, exchange=hl, account_address=settings.account, mainnet=settings.is_mainnet
        )
        return venue, venue.signs_as_api_wallet

    return cli.main(argv, factory=factory)


def test_open_without_execute_is_a_dry_run(
    hl: FakeHyperliquid, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(hl, ["open", "--side", "long", "--sl", "145", "--tp", "160"]) == 0
    out = capsys.readouterr().out
    assert "HYPERLIQUID TESTNET" in out
    assert "DRY RUN" in out
    assert "loss at stop" in out
    assert "reward : risk" in out
    assert hl.calls == []


def test_open_execute_then_status_then_close(
    hl: FakeHyperliquid, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(hl, ["open", "--side", "short", "--sl", "155", "--rr", "2", "--execute"]) == 0
    out = capsys.readouterr().out
    assert "SENT" in out
    assert "filled @ 150" in out
    assert "take profit       140" in out  # 150 - 2 x (155 - 150)
    assert "WARNING" not in out

    assert _run(hl, ["status"]) == 0
    status = capsys.readouterr().out
    assert "SOL SHORT" in status
    assert "trigger 155" in status

    assert _run(hl, ["close", "--execute"]) == 0
    assert "close SOL SHORT" in capsys.readouterr().out
    assert hl.positions == {}


def test_refusal_exits_non_zero_with_the_reason(
    hl: FakeHyperliquid, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(hl, ["open", "--side", "long", "--sl", "151"]) == 1
    assert "stop loss must be below" in capsys.readouterr().err


def test_tpsl_needs_a_price(hl: FakeHyperliquid, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(hl, ["open", "--side", "long", "--sl", "145", "--execute"]) == 0
    assert _run(hl, ["tpsl", "--execute"]) == 1
    assert "--sl and/or --tp" in capsys.readouterr().err
    assert _run(hl, ["tpsl", "--sl", "148", "--execute"]) == 0


def test_mainnet_asks_for_confirmation(
    hl: FakeHyperliquid, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TRADER_NETWORK", "MAINNET")
    monkeypatch.setenv("TRADER_ALLOW_MAINNET", "true")
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert _run(hl, ["open", "--side", "long", "--sl", "145", "--execute"]) == 1
    assert "not confirmed" in capsys.readouterr().err
    assert hl.calls == []


def test_main_wallet_key_is_warned_about(
    hl: FakeHyperliquid, capsys: pytest.CaptureFixture[str]
) -> None:
    hl.wallet = MAIN
    assert _run(hl, ["open", "--side", "long", "--sl", "145"]) == 0
    assert "Use an API wallet" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["abc", "-5", "0", "nan"])
def test_invalid_prices_are_rejected_by_the_parser(hl: FakeHyperliquid, value: str) -> None:
    with pytest.raises(SystemExit):
        _run(hl, ["open", "--side", "long", "--sl", value])
