"""Hyperliquid venue integration.

Everything venue-specific lives here, behind the `ExchangeAdapter` contract and
the canonical schemas (ADR-005). Nothing above this package should know a
Hyperliquid field name.

**The message shapes here are taken from Hyperliquid's official Python SDK type
definitions, not from a live connection.** They must be verified against the
real testnet feed before M2 can be considered passed — see
`docs/evidence/build-0.1/README.md`. The SDK definitions are also demonstrably
incomplete: `Trade` there omits `tid` and `users`, and types `sz` as an integer
where the API sends a decimal string. The parsing layer is therefore written to
be tolerant of both, and to ignore unknown fields rather than fail on them.
"""

from libs.exchange.hyperliquid.messages import (
    HyperliquidMessage,
    MessageParseError,
    parse_message,
)
from libs.exchange.hyperliquid.normalize import (
    NormalizationError,
    normalize,
)
from libs.exchange.hyperliquid.subscriptions import (
    RECORDED_CHANNELS,
    subscription_request,
)

__all__ = [
    "RECORDED_CHANNELS",
    "HyperliquidMessage",
    "MessageParseError",
    "NormalizationError",
    "normalize",
    "parse_message",
    "subscription_request",
]
