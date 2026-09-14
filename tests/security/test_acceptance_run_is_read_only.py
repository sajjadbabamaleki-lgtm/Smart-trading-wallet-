"""The acceptance run must stay incapable of moving capital.

The M1/M2 acceptance connects to the real venue — by default to *mainnet*
market data, because the testnet book is too thin to say anything about what
the real venue sends (ADR-009). That is safe only because the run holds no
credential and cannot reach an execution endpoint, and "only because" is
exactly the kind of claim that needs a test rather than a comment.

These read the script's own exported configuration. The runtime half of the
same property is asserted by the script's `assert_execution_guard` step, which
refuses to proceed if `libs/config/settings.py` disagrees; this is the static
half, and it fails at development time instead of mid-run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from libs.config.settings import PERMITTED_ENVIRONMENTS, VENUE_ENDPOINTS
from libs.schemas.enums import ExecutionEnvironment

pytestmark = pytest.mark.security

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "infrastructure" / "scripts" / "accept_m1_m2.sh"


def exported() -> dict[str, str]:
    """Every `export STW_...="value"` the script sets."""
    pattern = re.compile(r'^export (STW_[A-Z_]+)="([^"]*)"', re.MULTILINE)
    return dict(pattern.findall(SCRIPT.read_text()))


def test_execution_environment_cannot_reach_capital() -> None:
    environment = ExecutionEnvironment(exported()["STW_EXECUTION_ENVIRONMENT"])
    assert environment in PERMITTED_ENVIRONMENTS
    assert not environment.reaches_real_capital
    assert VENUE_ENDPOINTS[environment] is None, (
        "the acceptance run must have no execution endpoint at all"
    )


def test_trading_stays_disabled() -> None:
    assert exported()["STW_TRADING_ENABLED"] == "false"


def test_no_credential_is_supplied() -> None:
    """Not merely empty — absent.

    `libs/config/settings.py` refuses to start when a credential is configured
    in a DEVELOPMENT environment, so exporting one at all would break the run.
    Asserting absence keeps the reason visible.
    """
    keys = exported()
    assert "STW_TESTNET_API_WALLET_PRIVATE_KEY" not in keys
    assert "STW_TESTNET_API_WALLET_ADDRESS" not in keys


def test_asset_allowlist_stays_btc_only() -> None:
    assert exported()["STW_ASSET_ALLOWLIST"] == "BTC"


def test_the_script_asserts_the_guard_before_connecting() -> None:
    """Ordering, not presence.

    The guard is only worth anything if it runs before the socket opens. The
    call order in the script body is the property; a guard asserted after the
    recording would prove nothing.
    """
    body = SCRIPT.read_text()
    tail = body[body.rindex("trap finish EXIT") :]
    assert tail.index("assert_execution_guard") < tail.index("live_verification")


def test_no_mainnet_execution_endpoint_appears_in_the_script() -> None:
    """The mainnet *market data* host is expected here; the execution one is not.

    They differ only by path on the same domain, so this checks the endpoint
    string that `VENUE_ENDPOINTS` maps real-capital environments to.
    """
    body = SCRIPT.read_text()
    for environment in ExecutionEnvironment:
        if not environment.reaches_real_capital:
            continue
        endpoint = VENUE_ENDPOINTS[environment]
        assert endpoint is not None
        assert f'STW_VENUE_ENDPOINT="{endpoint}"' not in body
        assert "STW_VENUE_ENDPOINT" not in body, (
            "the venue endpoint is derived from the environment, never configured"
        )
