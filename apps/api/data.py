"""What the app's screens read.

Shaped by Phase 9 rather than by what is convenient to render:

* §23 the operating mode is always present, so no screen has to guess whether
  the system can place trades.
* §76 wallet balance, trading equity, available margin and capital at risk are
  four separate numbers and are never merged into one.
* §51/§65 the health of the things trading depends on is part of the state.

Prices come from the recorder's own ClickHouse rows. Nothing here is generated
for display: a store that cannot be reached says so rather than returning a
plausible number, and a figure that needs a trading account that does not exist
is null with the reason attached.
"""

from __future__ import annotations

from typing import Any

from libs.config import Settings
from libs.observability.logging import get_logger
from libs.storage import clickhouse as ch

logger = get_logger("app")


def operating_mode(settings: Settings) -> dict[str, Any]:
    """Which of the three modes of §22 the build is actually in.

    Derived from the same conjunction the executor obeys, so the banner cannot
    disagree with what the system would really do. Autopilot never appears
    here: §25 makes it a separate grant with nine preconditions, and no such
    grant exists yet.
    """
    if not settings.may_submit_orders:
        if settings.venue_endpoint is None:
            reason = "This environment submits no orders"
        elif not settings.testnet_api_wallet_private_key:
            reason = "No signing credential is configured"
        else:
            reason = "Kill switch 0.1 is engaged"
        return {"name": "research", "label": "RESEARCH ONLY", "reason": reason}
    return {
        "name": "copilot",
        "label": "COPILOT",
        "reason": "Every order needs your approval. Autopilot is a separate grant.",
    }


def account(settings: Settings) -> dict[str, Any]:  # noqa: ARG001
    """§76: the four money figures, kept apart.

    None of them exist before a trading account is authorized, and none of them
    is the wallet balance. Returning zero here would read as a funded account
    holding nothing.
    """
    return {
        "trading_equity": None,
        "available_margin": None,
        "capital_at_risk": None,
        "todays_pnl": None,
        "reason": "No trading account is authorized yet",
    }


def health(settings: Settings, market_available: bool) -> dict[str, Any]:
    """§51: what trading depends on, and whether it is actually up."""
    return {
        "market_data": "ok" if market_available else "unavailable",
        "kill_switch": "released" if settings.trading_enabled else "engaged",
        "credential": bool(settings.testnet_api_wallet_private_key),
        "venue": "unknown",
    }


def market(settings: Settings) -> dict[str, Any]:
    """Latest BTC quote and 24h change, from what the recorder captured."""
    try:
        with ch.connect_from_settings(settings) as client:
            latest = client.query(
                "SELECT bid_price, ask_price, local_receive_time FROM market_events "
                "WHERE asset = 'BTC' AND bid_price IS NOT NULL AND ask_price IS NOT NULL "
                "ORDER BY local_receive_time DESC LIMIT 1"
            ).result_rows
            if not latest:
                return {"available": False, "reason": "No price data yet"}

            bid, ask, moment = latest[0]
            mid = (float(bid) + float(ask)) / 2

            earlier = client.query(
                "SELECT bid_price, ask_price FROM market_events "
                "WHERE asset = 'BTC' AND bid_price IS NOT NULL AND ask_price IS NOT NULL "
                "AND local_receive_time <= now() - INTERVAL 24 HOUR "
                "ORDER BY local_receive_time DESC LIMIT 1"
            ).result_rows
            # No 24h-old quote means the recorder has not been running that
            # long. A change figure would then be against an arbitrary
            # starting point, so none is returned.
            change = None
            if earlier:
                before = (float(earlier[0][0]) + float(earlier[0][1])) / 2
                if before:
                    change = (mid - before) / before * 100

            return {
                "available": True,
                "symbol": "BTC-PERP",
                "mid": mid,
                "bid": float(bid),
                "ask": float(ask),
                "change_24h_pct": change,
                "as_of": moment.isoformat(),
            }
    except Exception:
        # The screen gets a short sentence; the driver's traceback goes to the
        # log. Putting a connection error where a price belongs is unreadable
        # on a phone and tells the user nothing they can act on.
        logger.exception("market_data_unavailable")
        return {"available": False, "reason": "Market data unavailable"}


def app_state(settings: Settings) -> dict[str, Any]:
    """Everything the screens need, in one read."""
    quote = market(settings)
    return {
        "mode": operating_mode(settings),
        # No wallet adapter exists, so no wallet can be connected. This is the
        # ordinary pre-connection state every wallet app has, not a placeholder.
        "wallet": {
            "connected": False,
            "address": None,
            "provider": None,
            "balance_usd": None,
            "balances": [],
        },
        "authorization": {
            "granted": False,
            "scope": None,
            "expires": None,
        },
        "account": account(settings),
        "positions": [],
        "network": settings.execution_environment.value,
        "trading_enabled": settings.trading_enabled,
        "can_submit_orders": settings.may_submit_orders,
        "assets": list(settings.asset_allowlist),
        # §73: limits are stated as the concepts they are, not as a slider.
        "limits": {
            "max_order_notional": float(settings.max_order_notional),
            "data_staleness_limit_seconds": settings.data_staleness_limit_seconds,
        },
        "health": health(settings, quote["available"]),
        "market": quote,
    }
