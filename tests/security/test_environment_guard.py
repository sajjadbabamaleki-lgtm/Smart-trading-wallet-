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
from libs.config.settings import MARKET_DATA_ENDPOINTS, Settings
from libs.schemas.enums import ExecutionEnvironment, MarketDataEnvironment
from services.market_data.cli import websocket_url

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


class TestMarketDataIsSeparateFromExecution:
    """ADR-009: reading public market data must not open a capital path.

    These are the tests that make the split safe rather than merely convenient.
    Splitting the settings let the recorder reach mainnet *market data*; if it
    also let anything reach mainnet *execution*, the split would have traded a
    real safety property for a research convenience.
    """

    def test_mainnet_market_data_does_not_enable_execution(self) -> None:
        settings = load_settings(market_data_environment=MarketDataEnvironment.MAINNET_PUBLIC)
        assert settings.market_data_endpoint == "wss://api.hyperliquid.xyz/ws"
        assert settings.venue_endpoint is None
        assert settings.may_submit_orders is False
        assert settings.market_data_is_read_only

    def test_mainnet_market_data_does_not_relax_the_execution_guard(self) -> None:
        """The two settings are independent; widening one must not widen the other."""
        with pytest.raises(ConfigurationError, match="not permitted"):
            load_settings(
                market_data_environment=MarketDataEnvironment.MAINNET_PUBLIC,
                execution_environment=ExecutionEnvironment.PRODUCTION,
            )

    def test_market_data_defaults_to_testnet(self) -> None:
        """Reaching mainnet data is an explicit choice, never a default."""
        assert load_settings().market_data_environment is MarketDataEnvironment.TESTNET

    def test_every_market_data_environment_has_an_endpoint(self) -> None:
        assert set(MARKET_DATA_ENDPOINTS) == set(MarketDataEnvironment)
        for endpoint in MARKET_DATA_ENDPOINTS.values():
            assert endpoint.startswith("wss://")

    def test_the_market_data_endpoint_is_not_configurable(self) -> None:
        """Derived, for the same reason the execution endpoint is."""
        settings = load_settings()
        assert "market_data_endpoint" not in type(settings).model_fields
        with pytest.raises(ConfigurationError):
            load_settings(market_data_endpoint="wss://somewhere.else/ws")

    def test_an_unknown_market_data_environment_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STW_MARKET_DATA_ENVIRONMENT", "MAINNET_WRITABLE")
        with pytest.raises(ConfigurationError):
            load_settings()

    def test_the_read_only_invariant_is_not_a_constant(self) -> None:
        """It must fail if the execution guard is ever widened.

        Asserted by constructing a settings object whose execution environment
        reaches capital. That cannot be reached through `load_settings` while
        PERMITTED_ENVIRONMENTS excludes it, which is the point — the invariant
        is checked against the underlying state rather than the validator.
        """
        reachable = Settings.model_construct(
            execution_environment=ExecutionEnvironment.PRODUCTION,
            market_data_environment=MarketDataEnvironment.MAINNET_PUBLIC,
            trading_enabled=True,
            testnet_api_wallet_private_key=TESTNET_KEY,
        )
        assert not reachable.market_data_is_read_only

    def test_the_safe_summary_reports_both_environments(self) -> None:
        described = load_settings(
            market_data_environment=MarketDataEnvironment.MAINNET_PUBLIC
        ).describe()
        assert described["market_data_environment"] == "MAINNET_PUBLIC"
        assert described["execution_environment"] == "DEVELOPMENT"
        assert described["market_data_is_read_only"] is True
        assert described["may_submit_orders"] is False

    def test_public_read_only_is_asserted_on_the_enum(self) -> None:
        assert MarketDataEnvironment.MAINNET_PUBLIC.is_public_read_only


class TestRecorderAndTradingShareAnEnvFile:
    """The configuration that stopped the recorder for thirty-nine hours.

    A testnet key and a released kill switch were put in `.env` so that an
    order could be placed by hand. The recorder reads the same file, correctly
    concluded that it could now reach capital, and refused to start. systemd
    retried, exhausted its start limit, and stopped trying.

    Both halves are asserted here: that the guard really does close on a
    trading-enabled testnet build, and that the configuration the systemd unit
    pins re-opens it without the guard being weakened.
    """

    def trading_build(self, **overrides: object) -> Settings:
        base: dict[str, object] = {
            "execution_environment": ExecutionEnvironment.TESTNET,
            "trading_enabled": True,
            "testnet_api_wallet_private_key": TESTNET_KEY,
            "market_data_environment": MarketDataEnvironment.MAINNET_PUBLIC,
        }
        base.update(overrides)
        return load_settings(**base)

    def test_a_build_that_can_trade_cannot_also_record(self) -> None:
        settings = self.trading_build()
        assert settings.may_submit_orders
        assert not settings.market_data_is_read_only

    def test_the_recorder_refuses_and_says_what_to_change(self) -> None:
        """An unactionable refusal is how a stopped recorder stays stopped."""
        with pytest.raises(ConfigurationError) as refusal:
            websocket_url(self.trading_build())
        message = str(refusal.value)
        assert "STW_EXECUTION_ENVIRONMENT=DEVELOPMENT" in message
        assert "STW_TRADING_ENABLED=false" in message

    def test_the_configuration_the_service_pins_records_again(self) -> None:
        """What the systemd unit sets, expressed as settings rather than as a file."""
        settings = self.trading_build(
            execution_environment=ExecutionEnvironment.DEVELOPMENT,
            trading_enabled=False,
            testnet_api_wallet_private_key="",
        )
        assert settings.market_data_is_read_only
        assert not settings.may_submit_orders
        # Still reading mainnet market data: the fix pins execution, not the feed.
        assert settings.market_data_environment is MarketDataEnvironment.MAINNET_PUBLIC
        assert websocket_url(settings) == settings.market_data_endpoint
