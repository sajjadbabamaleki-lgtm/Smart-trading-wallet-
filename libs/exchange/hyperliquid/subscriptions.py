"""Subscription requests.

Build 0.1 Rev.1 §24 names the channels the recorder captures first: trades,
L2 book, BBO and asset context. User-scoped channels (order updates, user
fills, fundings) come with execution testing at M6-M8, not now.

Rev.2 narrows the asset universe to BTC. The recorder takes its assets from
`settings.asset_allowlist`, so the allowlist is enforced in one place rather
than duplicated here.
"""

from __future__ import annotations

from typing import Any, Final

RECORDED_CHANNELS: Final[tuple[str, ...]] = ("trades", "l2Book", "bbo", "activeAssetCtx")
"""Channels the M2 recorder subscribes to, per Build 0.1 Rev.1 §24."""

TESTNET_WS_URL: Final = "wss://api.hyperliquid-testnet.xyz/ws"
MAINNET_WS_URL: Final = "wss://api.hyperliquid.xyz/ws"
"""WebSocket endpoints.

Both are listed so the mapping is reviewable in one place. Which one is
reachable is decided by `libs.config.settings`, where only DEVELOPMENT and
TESTNET pass validation — this module never chooses.
"""


def subscription_request(channel: str, coin: str) -> dict[str, Any]:
    """Build one subscribe request.

    `activeAssetCtx` carries funding, open interest, mark price and oracle price
    — the derivatives state Phase 2 §4.3 treats as a core input rather than an
    extra, since price movement without derivatives context is an incomplete
    picture of the market.
    """
    if channel not in RECORDED_CHANNELS:
        raise ValueError(
            f"unknown channel {channel!r}; expected one of {', '.join(RECORDED_CHANNELS)}"
        )
    if not coin:
        raise ValueError("coin must not be empty")
    return {"method": "subscribe", "subscription": {"type": channel, "coin": coin}}


def unsubscribe_request(channel: str, coin: str) -> dict[str, Any]:
    """Build one unsubscribe request."""
    request = subscription_request(channel, coin)
    return {"method": "unsubscribe", "subscription": request["subscription"]}
