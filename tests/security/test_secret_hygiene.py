"""Secret hygiene: redaction, safe summaries, and repository contents."""

from __future__ import annotations

import io
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from libs.config import load_settings
from libs.observability.logging import configure_logging, get_logger
from libs.schemas.enums import ExecutionEnvironment
from libs.security.redaction import redact

TESTNET_KEY = "0x" + "ab" * 32
REPO_ROOT = Path(__file__).resolve().parents[2]


class TestRedaction:
    @pytest.mark.parametrize(
        "key",
        [
            "private_key",
            "privateKey",
            "STW_TESTNET_API_WALLET_PRIVATE_KEY",
            "api_secret",
            "password",
            "passphrase",
            "seed_phrase",
            "mnemonic",
            "auth_token",
            "apiKey",
            "credential",
            "Authorization",
            "signature",
            "cookie",
        ],
    )
    def test_sensitive_keys_are_redacted(self, key: str) -> None:
        assert redact({key: "sensitive"})[key] == "***REDACTED***"

    def test_ordinary_keys_pass_through(self) -> None:
        payload = {"asset": "BTC", "quantity": "0.01", "correlation_id": "cor_1"}
        assert redact(payload) == payload

    def test_nested_structures_are_redacted(self) -> None:
        payload = {
            "order": {"asset": "BTC", "signature": "deadbeef"},
            "wallets": [{"address": "0xabc", "private_key": TESTNET_KEY}],
        }
        result = redact(payload)
        assert result["order"]["signature"] == "***REDACTED***"
        assert result["wallets"][0]["private_key"] == "***REDACTED***"
        assert result["wallets"][0]["address"] == "0xabc"

    def test_deep_nesting_is_bounded(self) -> None:
        """A pathological structure must not hang a logging call."""
        payload: dict[str, Any] = {"level": 0}
        node = payload
        for depth in range(1, 40):
            node["child"] = {"level": depth}
            node = node["child"]
        redact(payload)  # completes rather than recursing without bound

    def test_tuple_and_set_types_survive_redaction(self) -> None:
        assert redact(("BTC", "ETH")) == ("BTC", "ETH")
        assert set(redact({"BTC", "ETH"})) == {"BTC", "ETH"}


class TestSettingsSummary:
    def test_describe_never_includes_credential_material(self) -> None:
        settings = load_settings(
            execution_environment=ExecutionEnvironment.TESTNET,
            testnet_api_wallet_private_key=TESTNET_KEY,
        )
        rendered = json.dumps(settings.describe())
        assert TESTNET_KEY not in rendered
        assert "ab" * 32 not in rendered

    def test_describe_reports_presence_without_the_value(self) -> None:
        settings = load_settings(
            execution_environment=ExecutionEnvironment.TESTNET,
            testnet_api_wallet_private_key=TESTNET_KEY,
        )
        assert settings.describe()["credential_configured"] is True

    def test_describe_surfaces_the_safety_state(self) -> None:
        described = load_settings().describe()
        assert described["execution_environment"] == "DEVELOPMENT"
        assert described["trading_enabled"] is False
        assert described["may_submit_orders"] is False
        assert described["build_stage"] == "0.1"


class TestLoggingRedaction:
    def test_structured_fields_are_emitted_as_json(self) -> None:
        stream = io.StringIO()
        configure_logging("INFO", stream=stream)
        get_logger("test").info(
            "order_rejected",
            extra={"asset": "BTC", "reason": "RISK_SIZE_EXCEEDED", "correlation_id": "cor_1"},
        )
        record = json.loads(stream.getvalue().strip())
        assert record["message"] == "order_rejected"
        assert record["asset"] == "BTC"
        assert record["reason"] == "RISK_SIZE_EXCEEDED"
        assert record["level"] == "INFO"

    def test_a_secret_handed_to_a_logging_call_does_not_reach_the_log(self) -> None:
        """Redaction is automatic, not dependent on the call site remembering."""
        stream = io.StringIO()
        configure_logging("INFO", stream=stream)
        get_logger("test").info(
            "wallet_loaded", extra={"private_key": TESTNET_KEY, "address": "0xabc"}
        )
        output = stream.getvalue()
        assert TESTNET_KEY not in output
        assert "***REDACTED***" in output
        assert "0xabc" in output

    def test_configure_logging_replaces_existing_handlers(self) -> None:
        """A stray plain-text handler must not emit an unredacted duplicate."""
        root = logging.getLogger()
        root.addHandler(logging.StreamHandler(io.StringIO()))
        stream = io.StringIO()
        configure_logging("INFO", stream=stream)
        assert len(root.handlers) == 1

    def test_exception_details_are_captured(self) -> None:
        stream = io.StringIO()
        configure_logging("INFO", stream=stream)

        def fail() -> None:
            raise ValueError("boom")

        try:
            fail()
        except ValueError:
            get_logger("test").exception("handler_failed")
        record = json.loads(stream.getvalue().strip())
        assert "ValueError: boom" in record["exception"]


class TestRepositoryHygiene:
    """Phase 10 §73: no committed secrets, from day one."""

    def test_no_dotenv_file_is_committed(self) -> None:
        git = shutil.which("git")
        assert git is not None, "git is required to check what is tracked"
        tracked = subprocess.run(  # noqa: S603 - resolved absolute path, fixed arguments
            [git, "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
        offenders = [
            path
            for path in tracked
            if Path(path).name.startswith(".env") and Path(path).name != ".env.example"
        ]
        assert offenders == [], f"committed environment files: {offenders}"

    def test_example_env_carries_no_credential_value(self) -> None:
        content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        for line in content.splitlines():
            if "PRIVATE_KEY" in line or "WALLET_ADDRESS" in line:
                assert line.split("=", 1)[1].strip() == "", f"populated: {line}"

    def test_no_hex_private_key_appears_in_source(self) -> None:
        """A 32-byte hex literal in source is treated as a leaked credential."""
        pattern = re.compile(r"(?:0x)?[0-9a-fA-F]{64}")
        for path in (REPO_ROOT / "libs").rglob("*.py"):
            assert not pattern.search(path.read_text(encoding="utf-8")), path

    def test_gitignore_excludes_secrets_and_data(self) -> None:
        content = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        for entry in (".env", "*.pem", "*.key", "data/", "raw/"):
            assert entry in content, f"missing from .gitignore: {entry}"
