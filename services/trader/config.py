"""Trader settings, read from `TRADER_*` environment variables or `.env.trader`.

A separate file and prefix from the research pipeline on purpose: the Build 0.1
`Settings` rejects any unknown key in `.env`, and hard-blocks mainnet for the
Hyperliquid research pipeline. This trader is a separate, user-operated tool
with its own guard: mainnet needs `TRADER_ALLOW_MAINNET=true` in addition to
`TRADER_NETWORK=MAINNET`, so no single edit reaches real money.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from services.trader.planner import HARD_MAX_RISK_PERCENT


class TraderConfigError(RuntimeError):
    """Configuration is unsafe or incomplete."""


class VenueName(StrEnum):
    HYPERLIQUID = "HYPERLIQUID"
    PACIFICA = "PACIFICA"


class Network(StrEnum):
    TESTNET = "TESTNET"
    MAINNET = "MAINNET"


class TraderSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRADER_",
        env_file=".env.trader",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    venue: VenueName = VenueName.HYPERLIQUID
    network: Network = Network.TESTNET
    allow_mainnet: bool = False

    account: str = Field(
        default="",
        description="The main wallet's public address: on Hyperliquid, the 0x address "
        "Phantom trades perps from.",
    )
    api_private_key: SecretStr = Field(
        default=SecretStr(""),
        description="An API wallet key approved on the exchange. Never the main wallet's "
        "own private key or seed phrase.",
    )

    default_risk_percent: Decimal = Field(default=Decimal(1), gt=0, le=HARD_MAX_RISK_PERCENT)
    max_leverage: int = Field(default=3, ge=1, le=20)
    slippage_percent: Decimal = Field(default=Decimal("0.5"), gt=0, le=5)
    taker_fee_rate: Decimal = Field(
        default=Decimal("0.00045"),
        ge=0,
        description="Assumed taker fee per side, as a fraction (0.00045 = 0.045%, "
        "Hyperliquid's base tier). Set it to your actual tier.",
    )

    @property
    def is_mainnet(self) -> bool:
        return self.network is Network.MAINNET

    @model_validator(mode="after")
    def _check_mainnet_is_deliberate(self) -> TraderSettings:
        if self.is_mainnet and not self.allow_mainnet:
            raise ValueError(
                "TRADER_NETWORK=MAINNET trades real money and also requires "
                "TRADER_ALLOW_MAINNET=true"
            )
        return self


def load_trader_settings() -> TraderSettings:
    try:
        return TraderSettings()
    except ValueError as exc:
        raise TraderConfigError(str(exc)) from exc
