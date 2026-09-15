"""What the app's screens read.

Prices come from the recorder's own ClickHouse rows — the last two-sided quote
it captured. Nothing here is generated for display, and a store that cannot be
reached says so rather than returning a plausible number.
"""

from __future__ import annotations

from typing import Any

from libs.config import Settings
from libs.observability.logging import get_logger
from libs.storage import clickhouse as ch

logger = get_logger("app")


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
    """Everything the four screens need, in one read."""
    return {
        # No wallet adapter exists, so no wallet can be connected. This is the
        # ordinary pre-connection state every wallet app has, not a placeholder.
        "wallet": {
            "connected": False,
            "address": None,
            "balances": [],
        },
        "network": settings.execution_environment.value,
        "trading_enabled": settings.trading_enabled,
        "can_submit_orders": settings.may_submit_orders,
        "assets": list(settings.asset_allowlist),
        "max_order_notional": float(settings.max_order_notional),
        "market": market(settings),
    }
