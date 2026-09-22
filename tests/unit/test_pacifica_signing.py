"""Pacifica request signing, pinned against the official SDK's output."""

from __future__ import annotations

import json

import pytest
from solders.keypair import Keypair
from solders.signature import Signature

from libs.exchange.pacifica.signing import (
    Signer,
    SigningError,
    canonical_message,
    check_account,
    load_keypair,
)

MAIN = Keypair.from_seed(bytes(range(32)))
AGENT = Keypair.from_seed(bytes(range(32, 64)))

PAYLOAD = {
    "symbol": "SOL",
    "reduce_only": False,
    "amount": "1.5",
    "side": "bid",
    "slippage_percent": "0.5",
    "client_order_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "take_profit": {"stop_price": "170"},
    "stop_loss": {"stop_price": "140"},
}

# Produced by `common.utils.sign_message` from pacifica-fi/python-sdk with the
# same key, header and payload. Ed25519 is deterministic, so any drift in key
# ordering, separators or encoding changes these bytes.
SDK_MESSAGE = (
    '{"data":{"amount":"1.5","client_order_id":"f47ac10b-58cc-4372-a567-0e02b2c3d479",'
    '"reduce_only":false,"side":"bid","slippage_percent":"0.5",'
    '"stop_loss":{"stop_price":"140"},"symbol":"SOL","take_profit":{"stop_price":"170"}},'
    '"expiry_window":5000,"timestamp":1716200000000,"type":"create_market_order"}'
)
SDK_SIGNATURE = (
    "4j8qc8uCrUBMgwbHQ7fX6nsYrrg5tqKhSHUMG9WjA6VukTojTgTtCuDGqQDei5Lr8MSXFk91Vq9ZwPR95gizCFLZ"
)


def test_canonical_message_matches_the_official_sdk() -> None:
    message = canonical_message(
        "create_market_order", PAYLOAD, timestamp_ms=1716200000000, expiry_window_ms=5000
    )
    assert message == SDK_MESSAGE


def test_signature_matches_the_official_sdk() -> None:
    signer = Signer(account=str(MAIN.pubkey()), keypair=MAIN)
    body = signer.sign("create_market_order", PAYLOAD, timestamp_ms=1716200000000)
    assert body["signature"] == SDK_SIGNATURE
    assert "agent_wallet" not in body


def test_agent_key_signs_for_the_main_account() -> None:
    account = str(MAIN.pubkey())
    signer = Signer(account=account, keypair=AGENT)
    body = signer.sign("create_market_order", PAYLOAD, timestamp_ms=1716200000000)

    assert signer.is_agent
    assert body["account"] == account
    assert body["agent_wallet"] == str(AGENT.pubkey())
    message = canonical_message(
        "create_market_order", PAYLOAD, timestamp_ms=1716200000000, expiry_window_ms=5000
    )
    signature = Signature.from_string(body["signature"])
    assert signature.verify(AGENT.pubkey(), message.encode())
    assert not signature.verify(MAIN.pubkey(), message.encode())


def test_body_flattens_the_payload_beside_the_auth_fields() -> None:
    signer = Signer(account=str(MAIN.pubkey()), keypair=MAIN)
    body = signer.sign("cancel_all_orders", {"symbol": "SOL"}, timestamp_ms=1)
    assert body["symbol"] == "SOL"
    assert body["timestamp"] == 1
    assert body["expiry_window"] == 5000
    assert "data" not in body
    assert "type" not in body


def test_nested_lists_keep_their_order() -> None:
    message = canonical_message(
        "x", {"b": [{"z": 1, "a": 2}, 3]}, timestamp_ms=0, expiry_window_ms=1
    )
    assert json.loads(message)["data"]["b"] == [{"a": 2, "z": 1}, 3]
    assert '{"a":2,"z":1}' in message


class TestKeyLoading:
    def test_base58_secret(self) -> None:
        assert load_keypair(str(AGENT)).pubkey() == AGENT.pubkey()

    def test_byte_array_secret(self) -> None:
        exported = json.dumps(list(bytes(AGENT)))
        assert load_keypair(exported).pubkey() == AGENT.pubkey()

    @pytest.mark.parametrize("secret", ["", "   ", "not-a-key", "[1,2,3]"])
    def test_invalid_secret_is_refused(self, secret: str) -> None:
        with pytest.raises(SigningError):
            load_keypair(secret)

    def test_error_never_contains_the_secret(self) -> None:
        secret = str(AGENT)[:-4] + "0OIl"  # invalid base58 characters
        with pytest.raises(SigningError) as excinfo:
            load_keypair(secret)
        assert secret not in str(excinfo.value)

    def test_account_address_is_validated(self) -> None:
        assert check_account(f" {MAIN.pubkey()} ") == str(MAIN.pubkey())
        with pytest.raises(SigningError):
            check_account("0xabc")
