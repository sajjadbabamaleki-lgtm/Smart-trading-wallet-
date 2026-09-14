"""Environment and capital-safety guards.

These are not style checks. Each test corresponds to a stated safety control,
and a failure here means the repository can reach real money at a build stage
where that is prohibited.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.config import (
    PERMITTED_ENVIRONMENTS,
    VENUE_ENDPOINTS,
    ConfigurationError,
    load_settings,
)
from libs.schemas.enums import ExecutionEnvironment

TESTNET_KEY = "0x" + "ab" * 32


class TestMainnetIsHardBlocked:
    """Build 0.1 Rev.2 §42: real capital prohibited, mainnet hard-blocked."""

    @pytest.mark.parametrize(
        "environment",
        [
            ExecutionEnvironment.PAPER,
            ExecutionEnvironment.SHADOW,
            ExecutionEnvironment.LIMITED_LIVE,
            ExecutionEnvironment.PRODUCTION,
        ],
    )
    def test_environments_beyond_testnet_refuse_to_start(
        self, environment: ExecutionEnvironment
    ) -> None:
        with pytest.raises(ConfigurationError, match="not permitted"):
            load_settings(execution_environment=environment)

    def test_only_development_and_testnet_are_permitted(self) -> None:
        assert set(PERMITTED_ENVIRONMENTS) == {
            ExecutionEnvironment.DEVELOPMENT,
            ExecutionEnvironment.TESTNET,
        }

    def test_refusal_explains_why_rather_than_just_failing(self) -> None:
        with pytest.raises(ConfigurationError) as exc:
            load_settings(execution_environment=ExecutionEnvironment.PRODUCTION)
        message = str(exc.value)
        assert "hard-blocked" in message
        assert "acceptance gates" in message

    def test_environment_from_the_process_environment_is_also_guarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The guard cannot be bypassed by setting an environment variable."""
        monkeypatch.setenv("STW_EXECUTION_ENVIRONMENT", "PRODUCTION")
        with pytest.raises(ConfigurationError, match="not permitted"):
            load_settings()

    def test_unknown_environment_name_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STW_EXECUTION_ENVIRONMENT", "MAINNET")
        with pytest.raises(ConfigurationError):
            load_settings()


class TestEndpointIsDerivedNotConfigured:
    """Build 0.1 Rev.1 §46: changing one URL must not enable real trading."""

    def test_endpoint_is_not_a_settable_field(self) -> None:
        settings = load_settings(execution_environment=ExecutionEnvironment.TESTNET)
        assert "venue_endpoint" not in type(settings).model_fields

    def test_attempting_to_configure_an_endpoint_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            load_settings(venue_endpoint="https://api.hyperliquid.xyz")

    def test_testnet_environment_yields_the_testnet_endpoint(self) -> None:
        settings = load_settings(execution_environment=ExecutionEnvironment.TESTNET)
        assert settings.venue_endpoint == "https://api.hyperliquid-testnet.xyz"
        assert "testnet" in settings.venue_endpoint

    def test_development_submits_no_orders_anywhere(self) -> None:
        settings = load_settings(execution_environment=ExecutionEnvironment.DEVELOPMENT)
        assert settings.venue_endpoint is None
        assert settings.may_submit_orders is False

    def test_no_permitted_environment_maps_to_mainnet(self) -> None:
        for environment in PERMITTED_ENVIRONMENTS:
            endpoint = VENUE_ENDPOINTS[environment]
            assert endpoint is None or "testnet" in endpoint

    def test_every_environment_has_an_explicit_endpoint_decision(self) -> None:
        """A new environment cannot be added without deciding where it points."""
        assert set(VENUE_ENDPOINTS) == set(ExecutionEnvironment)


class TestKillSwitchDefault:
    """Build 0.1 Rev.1 §57: no new exposure while trading is disabled."""

    def test_trading_is_disabled_by_default(self) -> None:
        assert load_settings().trading_enabled is False

    def test_orders_are_blocked_while_the_kill_switch_is_engaged(self) -> None:
        settings = load_settings(
            execution_environment=ExecutionEnvironment.TESTNET,
            testnet_api_wallet_private_key=TESTNET_KEY,
            trading_enabled=False,
        )
        assert settings.may_submit_orders is False

    def test_submission_needs_environment_credential_and_switch_together(self) -> None:
        settings = load_settings(
            execution_environment=ExecutionEnvironment.TESTNET,
            testnet_api_wallet_private_key=TESTNET_KEY,
            trading_enabled=True,
        )
        assert settings.may_submit_orders is True

    def test_a_released_switch_without_a_credential_still_submits_nothing(self) -> None:
        settings = load_settings(
            execution_environment=ExecutionEnvironment.TESTNET, trading_enabled=True
        )
        assert settings.may_submit_orders is False


class TestCredentialGuard:
    """Build 0.1 Rev.1 §70: build safety into configuration, not into memory."""

    def test_development_must_hold_no_signing_credential(self) -> None:
        with pytest.raises(ConfigurationError, match="DEVELOPMENT"):
            load_settings(
                execution_environment=ExecutionEnvironment.DEVELOPMENT,
                testnet_api_wallet_private_key=TESTNET_KEY,
            )

    def test_malformed_credential_refuses_to_start(self) -> None:
        """Better to refuse than to attempt signing with a malformed key."""
        with pytest.raises(ConfigurationError, match="32-byte hex"):
            load_settings(
                execution_environment=ExecutionEnvironment.TESTNET,
                testnet_api_wallet_private_key="not-a-key",
            )

    def test_truncated_credential_refuses_to_start(self) -> None:
        with pytest.raises(ConfigurationError, match="32-byte hex"):
            load_settings(
                execution_environment=ExecutionEnvironment.TESTNET,
                testnet_api_wallet_private_key="0x" + "ab" * 16,
            )

    def test_wellformed_testnet_credential_is_accepted_with_or_without_prefix(self) -> None:
        for key in (TESTNET_KEY, "ab" * 32):
            settings = load_settings(
                execution_environment=ExecutionEnvironment.TESTNET,
                testnet_api_wallet_private_key=key,
            )
            assert settings.testnet_api_wallet_private_key == key

    def test_no_credential_is_the_normal_state(self) -> None:
        settings = load_settings(execution_environment=ExecutionEnvironment.TESTNET)
        assert settings.testnet_api_wallet_private_key == ""


class TestAssetAllowlist:
    """Phase 10 §25: unsupported assets cannot execute, whatever the AI says."""

    def test_defaults_to_btc_only(self) -> None:
        assert load_settings().asset_allowlist == ("BTC",)

    def test_unsupported_asset_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="unsupported asset"):
            load_settings(asset_allowlist=("BTC", "DOGE"))

    def test_empty_allowlist_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="must not be empty"):
            load_settings(asset_allowlist=())

    def test_comma_separated_value_is_parsed_and_normalised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STW_ASSET_ALLOWLIST", "btc, eth")
        assert load_settings().asset_allowlist == ("BTC", "ETH")

    def test_single_bare_value_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The value a person is most likely to type must not be a parse error."""
        monkeypatch.setenv("STW_ASSET_ALLOWLIST", "BTC")
        assert load_settings().asset_allowlist == ("BTC",)

    def test_json_array_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STW_ASSET_ALLOWLIST", '["BTC", "sol"]')
        assert load_settings().asset_allowlist == ("BTC", "SOL")

    def test_malformed_json_is_refused_as_a_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A parse failure must read as a refusal to start, not a crash."""
        monkeypatch.setenv("STW_ASSET_ALLOWLIST", '["BTC",')
        with pytest.raises(ConfigurationError):
            load_settings()

    def test_unsupported_asset_from_the_environment_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STW_ASSET_ALLOWLIST", "BTC,DOGE")
        with pytest.raises(ConfigurationError, match="unsupported asset"):
            load_settings()


class TestBoundsAreValidated:
    def test_non_positive_order_notional_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            load_settings(max_order_notional=Decimal(0))

    def test_non_positive_staleness_limit_is_refused(self) -> None:
        """A zero staleness limit would make every decision use stale data."""
        with pytest.raises(ConfigurationError):
            load_settings(data_staleness_limit_seconds=0)

    def test_non_positive_intent_ttl_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            load_settings(intent_ttl_seconds=-1)

    def test_unknown_setting_is_refused(self) -> None:
        """A typo in a safety setting must fail loudly, not be ignored."""
        with pytest.raises(ConfigurationError):
            load_settings(tradng_enabled=True)

    def test_invalid_log_level_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            load_settings(log_level="CHATTY")


class TestSettingsAreImmutable:
    def test_settings_cannot_be_mutated_after_validation(self) -> None:
        settings = load_settings()
        with pytest.raises(Exception, match=r"frozen"):
            settings.trading_enabled = True  # type: ignore[misc]
