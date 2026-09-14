"""Redaction of sensitive values before they reach a log or a report.

Phase 10 §11 prohibits secrets from entering logs, traces, analytics, crash
reports or CI output, and requires redaction to be automatic. Automatic is the
operative word: a rule that depends on each call site remembering to redact is
a rule that fails on the first hurried change.

Phase 10 §61 draws the line this module implements — auditability does not
justify logging secrets. A log should carry enough to reconstruct what happened
without carrying the material needed to repeat it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

SENSITIVE_KEY_MARKERS: Final[tuple[str, ...]] = (
    "private_key",
    "privatekey",
    "secret",
    "password",
    "passphrase",
    "seed",
    "mnemonic",
    "token",
    "api_key",
    "apikey",
    "credential",
    "authorization",
    "signature",
    "cookie",
)
"""Substrings that mark a key as sensitive.

Matched case-insensitively against the whole key, so `STW_TESTNET_API_WALLET_
PRIVATE_KEY` and `privateKey` both match. The list errs towards over-matching:
a redacted non-secret costs a debugging round, a leaked secret costs a
credential rotation and an incident.
"""

_PLACEHOLDER: Final = "***REDACTED***"
_MAX_DEPTH: Final = 12


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_KEY_MARKERS)


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Return `value` with sensitive entries replaced.

    Recurses through mappings and sequences. Values are matched by *key*, not by
    content: guessing whether a bare string is a secret produces both false
    positives and false negatives, whereas the key that carries it is known.

    Nesting deeper than `_MAX_DEPTH` is replaced wholesale rather than
    traversed, so a cyclic or pathological structure cannot hang a logging call.
    """
    if _depth > _MAX_DEPTH:
        return _PLACEHOLDER

    if isinstance(value, Mapping):
        return {
            key: _PLACEHOLDER if _is_sensitive(str(key)) else redact(item, _depth=_depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        redacted = [redact(item, _depth=_depth + 1) for item in value]
        return type(value)(redacted) if isinstance(value, (list, tuple)) else redacted
    return value


def redact_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Redact a mapping, returning a plain dict suitable for logging."""
    result = redact(dict(mapping))
    assert isinstance(result, dict)  # noqa: S101 - narrowing for the type checker
    return result
