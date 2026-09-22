"""Request signing for Pacifica.

Every Pacifica POST is authorised by an Ed25519 signature over a canonical JSON
message. The scheme is reproduced from the official SDK
(`pacifica-fi/python-sdk`, `common/utils.py`):

1. The header is `{"type", "timestamp", "expiry_window"}`; the operation's
   payload goes under `"data"`.
2. Keys are sorted recursively and the result is serialised as compact JSON —
   `separators=(",", ":")`. A single space changes the bytes and the venue
   rejects the signature.
3. The UTF-8 bytes are signed and the signature is sent base58-encoded.

The request body is *not* the signed message: it is the payload flattened
alongside `account`, `signature`, `timestamp`, `expiry_window` and, when an
agent key signs, `agent_wallet`.

An agent key (Pacifica calls it an "API agent key" or "agent wallet") is bound
to the main wallet once, from the Pacifica app while connected with Phantom.
The bot then signs with the agent key and names the main wallet as `account`,
so the Phantom private key never reaches this process.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from solders.keypair import Keypair
from solders.pubkey import Pubkey

DEFAULT_EXPIRY_WINDOW_MS: Final = 5_000
"""How long a signature stays valid. Short, so a captured request cannot be
replayed later; the official examples use the same value."""


class SigningError(ValueError):
    """A key or account could not be used for signing."""


def sort_keys(value: Any) -> Any:
    """Sort dictionary keys at every depth, preserving list order."""
    if isinstance(value, dict):
        return {key: sort_keys(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [sort_keys(item) for item in value]
    return value


def canonical_message(
    operation: str, payload: dict[str, Any], *, timestamp_ms: int, expiry_window_ms: int
) -> str:
    """The exact string whose UTF-8 bytes are signed."""
    message = {
        "type": operation,
        "timestamp": timestamp_ms,
        "expiry_window": expiry_window_ms,
        "data": payload,
    }
    return json.dumps(sort_keys(message), separators=(",", ":"))


def load_keypair(secret: str) -> Keypair:
    """Load a Solana keypair from its base58 secret, as Phantom and Pacifica export it.

    Accepts the 64-byte base58 form and the JSON byte-array form
    (`[12,34,...]`) that some wallets export.
    """
    text = secret.strip()
    if not text:
        raise SigningError("no private key configured")
    raw: object = None
    if text.startswith("["):
        try:
            raw = json.loads(text)
        except ValueError as exc:
            raise SigningError("a byte-array key must be a JSON list of numbers") from exc
        if not isinstance(raw, list) or len(raw) != 64:  # noqa: PLR2004
            raise SigningError("a byte-array key must contain exactly 64 numbers")
    try:
        if isinstance(raw, list):
            return Keypair.from_bytes(bytes(raw))
        return Keypair.from_base58_string(text)
    except Exception as exc:  # solders raises its own untyped errors
        # The key material itself is never included in the message.
        raise SigningError(
            f"private key is not a valid Solana keypair ({type(exc).__name__})"
        ) from exc


def check_account(address: str) -> str:
    """Validate a Solana public address (the Phantom wallet address)."""
    text = address.strip()
    try:
        Pubkey.from_string(text)
    except Exception as exc:  # solders raises its own untyped errors
        raise SigningError(f"not a valid Solana address: {text!r}") from exc
    return text


@dataclass(frozen=True)
class Signer:
    """Signs requests for one Pacifica account.

    `account` is the main wallet's public address. When `keypair` belongs to a
    different public key, it is treated as that account's agent key and every
    request carries `agent_wallet`.
    """

    account: str
    keypair: Keypair
    expiry_window_ms: int = DEFAULT_EXPIRY_WINDOW_MS

    @property
    def signing_key(self) -> str:
        return str(self.keypair.pubkey())

    @property
    def is_agent(self) -> bool:
        return self.signing_key != self.account

    def sign(self, operation: str, payload: dict[str, Any], *, timestamp_ms: int) -> dict[str, Any]:
        """Build the request body for one operation."""
        message = canonical_message(
            operation,
            payload,
            timestamp_ms=timestamp_ms,
            expiry_window_ms=self.expiry_window_ms,
        )
        signature = self.keypair.sign_message(message.encode("utf-8"))
        body: dict[str, Any] = {
            "account": self.account,
            "signature": str(signature),
            "timestamp": timestamp_ms,
            "expiry_window": self.expiry_window_ms,
        }
        if self.is_agent:
            body["agent_wallet"] = self.signing_key
        body.update(payload)
        return body
