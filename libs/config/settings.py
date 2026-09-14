"""Application settings, validated at startup.

Invalid configuration fails startup rather than degrading at runtime
(Build 0.1 Rev.1 §69). Three guards here are safety controls, not conveniences:

1. Build 0.1 permits only DEVELOPMENT and TESTNET. Real capital is prohibited
   and mainnet execution is hard-blocked (Build 0.1 Rev.2 §42), so an
   environment beyond the permitted set is refused outright.

2. The venue endpoint is *derived* from the environment, never configured.
   Changing one URL must not be able to enable real-money trading
   (Build 0.1 Rev.1 §46).

3. A credential that looks like production fails startup in a development
   environment (Build 0.1 Rev.1 §70). Safety belongs in configuration, not in
   remembering.

`trading_enabled` defaults to false — Kill Switch 0.1 (Build 0.1 Rev.1 §57) —
and the asset allowlist defaults to BTC only, matching Rev.2's scope.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Annotated, Final

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

from libs.schemas.enums import ExecutionEnvironment

BUILD_STAGE: Final = "0.1"

PERMITTED_ENVIRONMENTS: Final[frozenset[ExecutionEnvironment]] = frozenset(
    {ExecutionEnvironment.DEVELOPMENT, ExecutionEnvironment.TESTNET}
)
"""Environments Build 0.1 may run in.

Widening this set is a deliberate, reviewed change gated on the Phase 6 and
Phase 7 acceptance gates passing on implemented systems — not a configuration
edit.
"""

VENUE_ENDPOINTS: Final[dict[ExecutionEnvironment, str | None]] = {
    ExecutionEnvironment.DEVELOPMENT: None,
    ExecutionEnvironment.TESTNET: "https://api.hyperliquid-testnet.xyz",
    ExecutionEnvironment.PAPER: None,
    ExecutionEnvironment.SHADOW: None,
    ExecutionEnvironment.LIMITED_LIVE: "https://api.hyperliquid.xyz",
    ExecutionEnvironment.PRODUCTION: "https://api.hyperliquid.xyz",
}
"""Endpoint per environment. Not user-configurable, by design.

DEVELOPMENT, PAPER and SHADOW map to None: they submit no venue orders at all.
The mainnet entries exist so the mapping is complete and reviewable in one
place, and are unreachable while PERMITTED_ENVIRONMENTS excludes them.
"""

PRIVATE_KEY_HEX_LENGTH: Final = 64
"""An Ethereum private key is 32 bytes, i.e. 64 hex characters."""

SUPPORTED_ASSETS: Final[frozenset[str]] = frozenset({"BTC", "ETH", "SOL", "BNB"})
"""Assets the long-term architecture supports.

The allowlist below is what may actually be traded, and Rev.2 narrows it to BTC.
The Execution Engine rejects anything outside the allowlist regardless of what
the strategy layer proposes (Phase 10 §25).
"""


class ConfigurationError(RuntimeError):
    """Configuration is unsafe or invalid. Startup must not continue."""


class Settings(BaseSettings):
    """Validated runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="STW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
    )

    execution_environment: ExecutionEnvironment = ExecutionEnvironment.DEVELOPMENT

    trading_enabled: bool = Field(
        default=False,
        description="Kill Switch 0.1. While false, no new exposure may be created.",
    )
    # NoDecode stops pydantic-settings from JSON-decoding the environment
    # value before validation, so the validator below can accept both the JSON
    # form and a plain comma-separated list. Without it, `STW_ASSET_ALLOWLIST=BTC`
    # raises a parse error instead of reaching validation.
    asset_allowlist: Annotated[tuple[str, ...], NoDecode] = Field(default=("BTC",))
    max_order_notional: Decimal = Field(default=Decimal(100), gt=0)
    data_staleness_limit_seconds: float = Field(default=5.0, gt=0)
    intent_ttl_seconds: float = Field(default=10.0, gt=0)

    testnet_api_wallet_address: str = ""
    testnet_api_wallet_private_key: str = ""

    # Store connection settings. Credentials live here rather than as defaults
    # in the client modules: Phase 10 §10 prohibits hard-coded secrets, and a
    # default credential in library code is how a development value ends up
    # reachable in production. The local Docker Compose values are in
    # .env.example, which is the right place for them.
    postgres_dsn: str = "postgresql://stw:stw@localhost:5432/stw"
    clickhouse_url: str = "http://localhost:8123"
    clickhouse_user: str = "stw"
    clickhouse_password: str = ""
    clickhouse_database: str = "stw"
    redis_url: str = "redis://localhost:6379/0"
    object_store_endpoint: str = "http://localhost:9000"
    object_store_bucket: str = "stw-raw"
    object_store_access_key: str = ""
    object_store_secret_key: str = ""

    log_level: str = "INFO"

    @field_validator("asset_allowlist", mode="before")
    @classmethod
    def _coerce_allowlist(cls, value: object) -> object:
        """Accept a JSON array or a comma-separated list, case-insensitively.

        Both `["BTC","ETH"]` and `BTC, eth` are accepted: the first is what a
        deployment tool is likely to emit, the second what a person types.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"asset_allowlist is not valid JSON: {exc}") from exc
            if not isinstance(decoded, list):
                raise ValueError("asset_allowlist JSON must be an array")
            return tuple(str(part).strip().upper() for part in decoded)
        return tuple(part.strip().upper() for part in text.split(",") if part.strip())

    @field_validator("asset_allowlist", mode="after")
    @classmethod
    def _check_allowlist(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("asset_allowlist must not be empty")
        unknown = sorted(set(value) - SUPPORTED_ASSETS)
        if unknown:
            raise ValueError(
                f"unsupported asset(s) {', '.join(unknown)}; "
                f"supported: {', '.join(sorted(SUPPORTED_ASSETS))}"
            )
        return value

    @field_validator("log_level", mode="after")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        permitted = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in permitted:
            raise ValueError(f"log_level must be one of {', '.join(sorted(permitted))}")
        return upper

    @model_validator(mode="after")
    def _check_environment_is_permitted(self) -> Settings:
        if self.execution_environment not in PERMITTED_ENVIRONMENTS:
            permitted = ", ".join(sorted(env.value for env in PERMITTED_ENVIRONMENTS))
            raise ValueError(
                f"execution_environment {self.execution_environment.value} is not permitted "
                f"at Build {BUILD_STAGE}. Permitted: {permitted}. Real capital is prohibited "
                f"and mainnet execution is hard-blocked until the Phase 6 and Phase 7 "
                f"acceptance gates pass on implemented systems."
            )
        return self

    @model_validator(mode="after")
    def _check_no_production_credential_in_development(self) -> Settings:
        """Refuse to start when a mainnet-looking credential is configured.

        The testnet fields are the only credential inputs that exist, so a
        mainnet key can only arrive by being pasted into one of them. An
        Ethereum private key is 32 bytes; anything of that shape in a
        development environment is treated as a real credential in the wrong
        place, because the cost of being wrong in the other direction is
        unbounded.
        """
        key = self.testnet_api_wallet_private_key.removeprefix("0x")
        if not key:
            return self
        if self.execution_environment is ExecutionEnvironment.DEVELOPMENT:
            raise ValueError(
                "a signing credential is configured while execution_environment is "
                "DEVELOPMENT. Development must hold no signing credential at all; set "
                "execution_environment=TESTNET to use a dedicated testnet API wallet."
            )
        if len(key) != PRIVATE_KEY_HEX_LENGTH or not all(
            c in "0123456789abcdefABCDEF" for c in key
        ):
            raise ValueError(
                "testnet_api_wallet_private_key is not a 32-byte hex key; refusing to "
                "start rather than attempt to sign with a malformed credential"
            )
        return self

    @property
    def venue_endpoint(self) -> str | None:
        """Endpoint for the configured environment, or None if it submits no orders."""
        return VENUE_ENDPOINTS[self.execution_environment]

    @property
    def may_submit_orders(self) -> bool:
        """Whether order submission is permitted at all right now.

        Requires an environment with an endpoint, a credential to sign with, and
        the kill switch released. Every one of the three is necessary; this
        property is the single place that conjunction is expressed.
        """
        return (
            self.venue_endpoint is not None
            and bool(self.testnet_api_wallet_private_key)
            and self.trading_enabled
        )

    def describe(self) -> dict[str, object]:
        """Safe-to-log summary. Never includes credential material."""
        return {
            "build_stage": BUILD_STAGE,
            "execution_environment": self.execution_environment.value,
            "venue_endpoint": self.venue_endpoint,
            "trading_enabled": self.trading_enabled,
            "may_submit_orders": self.may_submit_orders,
            "asset_allowlist": list(self.asset_allowlist),
            "max_order_notional": str(self.max_order_notional),
            "data_staleness_limit_seconds": self.data_staleness_limit_seconds,
            "intent_ttl_seconds": self.intent_ttl_seconds,
            "credential_configured": bool(self.testnet_api_wallet_private_key),
        }


def load_settings(**overrides: object) -> Settings:
    """Load and validate settings, or raise `ConfigurationError`.

    Wraps pydantic's `ValidationError` so that callers catch one exception type
    and so that a failure reads as a refusal to start rather than a stack trace.
    """
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except SettingsError as exc:
        # pydantic-settings raises this (not ValidationError) when a value
        # cannot even be parsed into the field's type. Catching only
        # ValidationError would let such a failure escape as an unhandled
        # error, which reads as a crash rather than a refusal to start.
        raise ConfigurationError(f"refusing to start: {exc}") from exc
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'config'}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigurationError(f"refusing to start: {problems}") from exc
