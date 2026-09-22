"""Trader settings, read from `PACIFICA_*` environment variables or `.env.trader`.

A separate file and prefix from the research pipeline on purpose: the Build 0.1
`Settings` rejects any unknown key in `.env`, and hard-blocks mainnet for the
Hyperliquid research pipeline. This trader is a separate, user-operated tool with its own guard:
mainnet needs `PACIFICA_ALLOW_MAINNET=true` in addition to
`PACIFICA_NETWORK=MAINNET`, so no single edit reaches real money.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from libs.exchange.pacifica.client import PacificaNetwork
from services.trader.planner import HARD_MAX_RISK_PERCENT


class TraderConfigError(RuntimeError):
    """Configuration is unsafe or incomplete."""


class TraderSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PACIFICA_",
        env_file=".env.trader",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    network: PacificaNetwork = PacificaNetwork.TESTNET
    allow_mainnet: bool = False

    account: str = Field(default="", description="The Phantom wallet's public address.")
    agent_private_key: SecretStr = Field(
        default=SecretStr(""),
        description="API agent key created on Pacifica while connected with Phantom. "
        "Never the Phantom wallet's own private key.",
    )

    default_risk_percent: Decimal = Field(default=Decimal(1), gt=0, le=HARD_MAX_RISK_PERCENT)
    max_leverage: int = Field(default=3, ge=1, le=20)
    slippage_percent: Decimal = Field(default=Decimal("0.5"), gt=0, le=5)
    taker_fee_rate: Decimal = Field(
        default=Decimal("0.0005"),
        ge=0,
        description="Assumed taker fee per side, as a fraction. Deliberately on the high "
        "side; check your actual tier on Pacifica and lower it if it is less.",
    )

    @model_validator(mode="after")
    def _check_mainnet_is_deliberate(self) -> TraderSettings:
        if self.network is PacificaNetwork.MAINNET and not self.allow_mainnet:
            raise ValueError(
                "PACIFICA_NETWORK=MAINNET trades real money and also requires "
                "PACIFICA_ALLOW_MAINNET=true"
            )
        return self


def load_trader_settings() -> TraderSettings:
    try:
        return TraderSettings()
    except ValueError as exc:
        raise TraderConfigError(str(exc)) from exc
