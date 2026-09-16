"""Signing an L1 action for Hyperliquid.

The venue authenticates an order by an EIP-712 signature over a hash of the
action, and the hash is taken over a **MessagePack** encoding of it rather than
over the JSON that travels on the wire. That detail decides the whole module:
MessagePack preserves the order the fields were inserted in, the venue rebuilds
the same bytes from its own typed structs, and a field written in a different
position produces a different hash and therefore a signature the venue
attributes to a different signer. So the builders here are not free to tidy
their field order, and say so where it matters.

Two things this deliberately does not do:

**No private key is ever logged, returned or stored here.** The key enters as
an argument, is used once, and the function returns only r, s and v. Phase 10
§10 prohibits a credential in library code, and the surrounding settings refuse
to hold one at all outside TESTNET.

**No network.** Signing is pure, so it can be tested exhaustively without a
venue, which matters for the one part of this system where a silent mistake is
not visible until money moves.

Reference: the scheme is Hyperliquid's published L1 action signing, the same
one their Python SDK implements.
"""

from __future__ import annotations

from typing import Any, Final

import msgpack
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils.crypto import keccak

# Constant for every L1 action, on testnet and mainnet alike. It is not the
# chain the venue settles on; it is part of the agreed message, and changing it
# only produces a signature nobody accepts.
AGENT_CHAIN_ID: Final = 1337
ZERO_ADDRESS: Final = "0x0000000000000000000000000000000000000000"

# Testnet and mainnet are distinguished here and nowhere else in the signature.
# A signature made for one is worthless on the other, which is a safety
# property worth stating: a testnet key cannot accidentally authorise a
# mainnet action even if every other field were identical.
MAINNET_SOURCE: Final = "a"
TESTNET_SOURCE: Final = "b"

EIP712_TYPES: Final[dict[str, list[dict[str, str]]]] = {
    "Agent": [
        {"name": "source", "type": "string"},
        {"name": "connectionId", "type": "bytes32"},
    ],
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
}


def action_hash(
    action: dict[str, Any],
    *,
    nonce: int,
    vault_address: str | None = None,
) -> bytes:
    """Hash an action exactly as the venue will hash it.

    The trailing bytes are a length-free encoding, so each part has to be
    written whether or not it carries anything: a single zero byte stands for
    "no vault", and omitting it rather than writing it shortens the preimage
    and changes the hash.

    The venue also accepts an optional expiry after the vault byte. This
    project does not send one, so it is not written - and writing it as absent
    is not the same thing, which is why there is no parameter for it here
    rather than a parameter defaulting to None.
    """
    data = msgpack.packb(action, use_bin_type=True)
    if data is None:  # pragma: no cover - packb returns bytes for a dict
        raise ValueError("action did not encode")
    data += nonce.to_bytes(8, "big")
    if vault_address is None:
        data += b"\x00"
    else:
        data += b"\x01" + bytes.fromhex(vault_address.removeprefix("0x"))
    return keccak(data)


def typed_data(connection_id: bytes, *, is_mainnet: bool) -> dict[str, Any]:
    """The EIP-712 message the signature is taken over.

    Called the "phantom agent" because no such agent exists on chain. The
    structure exists so that a wallet signing prompt shows something
    intelligible, and so that the signature commits to one network.
    """
    return {
        "domain": {
            "chainId": AGENT_CHAIN_ID,
            "name": "Exchange",
            "verifyingContract": ZERO_ADDRESS,
            "version": "1",
        },
        "types": EIP712_TYPES,
        "primaryType": "Agent",
        "message": {
            "source": MAINNET_SOURCE if is_mainnet else TESTNET_SOURCE,
            "connectionId": connection_id,
        },
    }


def sign_l1_action(
    action: dict[str, Any],
    *,
    private_key: str,
    nonce: int,
    is_mainnet: bool,
    vault_address: str | None = None,
) -> dict[str, Any]:
    """Sign one action, returning the r/s/v the venue expects.

    `is_mainnet` is required rather than defaulted. A default would decide the
    most consequential field in this module by omission, and Build 0.1 permits
    only TESTNET regardless — a caller that has to pass it is a caller that had
    to think about it.
    """
    digest = action_hash(action, nonce=nonce, vault_address=vault_address)
    encoded = encode_typed_data(full_message=typed_data(digest, is_mainnet=is_mainnet))
    signed = Account.sign_message(encoded, private_key=private_key)
    return {"r": hex(signed.r), "s": hex(signed.s), "v": signed.v}


def signer_address(private_key: str) -> str:
    """The address a key signs as, for checking configuration against reality."""
    return str(Account.from_key(private_key).address)
