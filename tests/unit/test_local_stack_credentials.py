"""The local stack's credentials, stated in three places, must agree.

`docker-compose.yml` configures the servers, `.env.example` configures the
application, and `accept_m1_m2.sh` exports its own set for the acceptance run.
Two of the three agreeing is not enough, and that is not hypothetical: the
acceptance run worked while `services.research.calibrate_cli` failed with
`AUTHENTICATION_FAILED`, because the script exported a ClickHouse password and
the settings default was an empty string.

Compose is the authority here — it is what the servers are actually started
with — so the other two are checked against it.

These credentials are local development values and are deliberately visible.
The stack holds no real capital, no mainnet credential and no user data, and
production configuration comes from a secrets manager rather than from any of
these files. What is being protected is agreement, not secrecy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "infrastructure" / "docker" / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ACCEPT_SCRIPT = REPO_ROOT / "infrastructure" / "scripts" / "accept_m1_m2.sh"


def compose_value(key: str) -> str:
    """Read one `KEY: value` from the compose file's environment blocks."""
    match = re.search(rf"^\s+{key}:\s*(\S+)\s*$", COMPOSE.read_text(), re.MULTILINE)
    assert match is not None, f"{key} is not set in {COMPOSE.name}"
    return match.group(1)


def env_example_value(key: str) -> str:
    match = re.search(rf"^{key}=(.*)$", ENV_EXAMPLE.read_text(), re.MULTILINE)
    assert match is not None, f"{key} is not set in .env.example"
    return match.group(1).strip()


def exported_value(key: str) -> str:
    match = re.search(rf'^export {key}="([^"]*)"', ACCEPT_SCRIPT.read_text(), re.MULTILINE)
    assert match is not None, f"{key} is not exported by {ACCEPT_SCRIPT.name}"
    return match.group(1)


@pytest.mark.parametrize(
    ("compose_key", "stw_key"),
    [
        ("CLICKHOUSE_USER", "STW_CLICKHOUSE_USER"),
        ("CLICKHOUSE_PASSWORD", "STW_CLICKHOUSE_PASSWORD"),
        ("CLICKHOUSE_DB", "STW_CLICKHOUSE_DATABASE"),
        ("MINIO_ROOT_USER", "STW_OBJECT_STORE_ACCESS_KEY"),
        ("MINIO_ROOT_PASSWORD", "STW_OBJECT_STORE_SECRET_KEY"),
    ],
)
def test_env_example_matches_what_the_servers_are_started_with(
    compose_key: str, stw_key: str
) -> None:
    assert env_example_value(stw_key) == compose_value(compose_key), (
        f".env.example sets {stw_key} to something the compose file does not start "
        f"{compose_key} with. The application will authenticate against a server "
        f"configured differently, and the error it gets will name the driver rather "
        f"than this mismatch."
    )


@pytest.mark.parametrize(
    ("compose_key", "stw_key"),
    [
        ("CLICKHOUSE_USER", "STW_CLICKHOUSE_USER"),
        ("CLICKHOUSE_PASSWORD", "STW_CLICKHOUSE_PASSWORD"),
        ("CLICKHOUSE_DB", "STW_CLICKHOUSE_DATABASE"),
        ("MINIO_ROOT_USER", "STW_OBJECT_STORE_ACCESS_KEY"),
        ("MINIO_ROOT_PASSWORD", "STW_OBJECT_STORE_SECRET_KEY"),
    ],
)
def test_the_acceptance_run_uses_the_same_credentials(compose_key: str, stw_key: str) -> None:
    """Otherwise acceptance passes against a stack nothing else can reach.

    Which is exactly what happened: the acceptance run was green while the
    research CLI could not authenticate at all.
    """
    assert exported_value(stw_key) == compose_value(compose_key)


def test_the_acceptance_run_and_env_example_do_not_disagree() -> None:
    """Every STW_ key the script exports and the example also sets must match."""
    exported = dict(
        re.findall(r'^export (STW_[A-Z_]+)="([^"]*)"', ACCEPT_SCRIPT.read_text(), re.MULTILINE)
    )
    example = dict(re.findall(r"^(STW_[A-Z_]+)=(.*)$", ENV_EXAMPLE.read_text(), re.MULTILINE))
    # A value the script takes from a shell variable is chosen per run — the
    # market-data environment comes from --market-data — so it is not a fixed
    # setting that could drift from the example.
    disagreements = {
        key: (value, example[key].strip())
        for key, value in exported.items()
        if key in example and not value.startswith("$") and example[key].strip() != value
    }
    assert not disagreements, (
        f"the acceptance script and .env.example disagree: {disagreements}. "
        f"A developer running a CLI by hand gets different behaviour from the "
        f"acceptance run, and only one of them is verified."
    )
