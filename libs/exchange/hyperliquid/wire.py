"""Turning our order model into the exact fields Hyperliquid accepts.

Separated from the adapter because every function here is pure, and this is
where a quiet mistake costs the most: a price with one digit too many is
rejected, a size with one digit too few is a different order than the one that
was authorised, and neither is visible by reading the calling code.

Three venue rules shape all of it.

**Numbers travel as strings, without trailing zeros.** They are hashed as part
of the signed action, so "0.0010" and "0.001" are different messages. Decimal
is used throughout rather than float for the same reason the rest of this
project uses it: a binary fraction cannot represent a price exactly, and an
order is not a place to discover that.

**Prices are rounded twice.** At most five significant figures, and at most
`6 - szDecimals` decimal places for a perpetual. Both apply; the tighter one
wins. Integer prices are exempt from the significant-figure rule, which is the
venue's own carve-out and not an approximation of it.

**Sizes are rounded to the asset's `szDecimals`** and to nothing else.

Rounding direction is deliberate and conservative: a buy rounds its limit price
down and a sell rounds it up, so rounding can only ever make our price less
aggressive than the one authorised, never more. Size rounds down for the same
reason — a rounding rule that could increase exposure is a rounding rule that
will, eventually.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Any, Final

from eth_utils.crypto import keccak

from libs.exchange.models import OrderRequest, OrderType, TimeInForce
from libs.schemas.enums import Side

MAX_SIGNIFICANT_FIGURES: Final = 5
PERPETUAL_DECIMAL_BUDGET: Final = 6

TIF_WIRE: Final[dict[TimeInForce, str]] = {
    TimeInForce.GTC: "Gtc",
    TimeInForce.IOC: "Ioc",
    TimeInForce.ALO: "Alo",
}


def to_wire(value: Decimal) -> str:
    """Render a decimal the way the venue reads it back.

    Format "f" rather than str(): `str(Decimal("1E-5"))` is "1E-5", which the
    venue does not parse as a price.
    """
    text = format(value.normalize(), "f")
    return "0" if text in {"-0", "-0.0"} else text


def round_price(price: Decimal, *, sz_decimals: int, side: Side) -> Decimal:
    """Apply both of the venue's price rules, away from aggression.

    An exact integer is returned unchanged: the significant-figure limit does
    not apply to it, and forcing 108000 to five figures would move the price.
    """
    rounding = ROUND_DOWN if side is Side.BUY else ROUND_UP
    places = PERPETUAL_DECIMAL_BUDGET - sz_decimals

    if price == price.to_integral_value():
        return price.quantize(Decimal(1))

    exponent = price.adjusted()  # position of the leading digit
    significant_places = MAX_SIGNIFICANT_FIGURES - 1 - exponent
    # The tighter of the two rules decides, so take the smaller allowance.
    allowed = min(places, significant_places)
    if allowed < 0:
        # Fewer digits than the integer part: round to whole units.
        return price.quantize(Decimal(1), rounding=rounding)
    return price.quantize(Decimal(1).scaleb(-allowed), rounding=rounding)


def round_size(quantity: Decimal, *, sz_decimals: int) -> Decimal:
    """Round a size to the asset's precision, downward, never up."""
    return quantity.quantize(Decimal(1).scaleb(-sz_decimals), rounding=ROUND_DOWN)


def cloid_for(client_order_id: str) -> str:
    """The venue's 16-byte client order id, derived from ours.

    Derived rather than generated, and derived by a pure function, because
    idempotency depends on it: a retry after a timeout has to present the id
    the venue may already have seen. A fresh id on retry is how one intent
    becomes two positions (Build 0.1 Rev.1 §53).

    A UUID maps straight onto the 16 bytes. Anything else is hashed into them,
    which keeps the mapping deterministic for ids this project does not choose
    the shape of.
    """
    try:
        return "0x" + uuid.UUID(client_order_id).hex
    except ValueError:
        return "0x" + keccak(text=client_order_id)[:16].hex()


def order_action(
    request: OrderRequest,
    *,
    asset_index: int,
    sz_decimals: int,
    limit_price: Decimal,
) -> dict[str, Any]:
    """Build the signed action for one order.

    **Field order is part of the message.** The action is hashed as MessagePack,
    which preserves insertion order, and the venue rebuilds those bytes from its
    own structs. Re-ordering these keys to read more naturally would produce a
    valid-looking signature that authenticates as a different signer.

    `limit_price` is passed in rather than read off the request because a
    MARKET order has none: Hyperliquid has no market order type, so the caller
    prices an immediate-or-cancel order off the book and states the slippage it
    accepted.
    """
    tif = TimeInForce.IOC if request.order_type is OrderType.MARKET else request.time_in_force
    return {
        "type": "order",
        "orders": [
            {
                "a": asset_index,
                "b": request.side is Side.BUY,
                "p": to_wire(round_price(limit_price, sz_decimals=sz_decimals, side=request.side)),
                "s": to_wire(round_size(request.quantity, sz_decimals=sz_decimals)),
                "r": request.reduce_only,
                "t": {"limit": {"tif": TIF_WIRE[tif]}},
                "c": cloid_for(request.client_order_id),
            }
        ],
        "grouping": "na",
    }


def cancel_action(*, asset_index: int, client_order_id: str) -> dict[str, Any]:
    """Cancel by our own id, so a cancel needs no venue id to have been seen.

    Cancelling by venue order id would require having received the ack, which
    is exactly what is missing in the case a cancel matters most: an order
    submitted into a timeout.
    """
    return {
        "type": "cancelByCloid",
        "cancels": [{"asset": asset_index, "cloid": cloid_for(client_order_id)}],
    }


def market_limit_price(
    *, reference: Decimal, side: Side, slippage: Decimal, sz_decimals: int
) -> Decimal:
    """The limit price an immediate-or-cancel order uses to stand in for a market order.

    Crossing by `slippage` is what makes it fill now; the limit is what stops it
    filling at any price at all, which is the property a market order gives up
    and this project is not willing to.
    """
    factor = Decimal(1) + slippage if side is Side.BUY else Decimal(1) - slippage
    return round_price(reference * factor, sz_decimals=sz_decimals, side=side)
