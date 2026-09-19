"""Turning recorded rows into the quote stream a backtest consumes.

The recorder stores each event type as its own row: a BBO carries the touch and
its sizes, a TRADE carries a price, a quantity and the aggressor's side. A
backtest needs them interleaved, because the question it asks of every quote is
*what has happened since the last one*.

So trades are folded forward into the next quote as signed flow, and that
direction matters. Folding them backwards — attributing a trade to the quote
that preceded it — would let a strategy see, at the moment of a quote,
aggression that had not happened yet. It is the smallest possible lookahead and
it would be invisible in the output.

Rows arrive already ordered by receipt time, and that order is checked rather
than trusted: the whole point of receipt-time ordering is that it is the only
sequence the system could actually have observed, and a single row out of place
silently breaks it.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from services.research.backtest import Quote


class StreamError(ValueError):
    """The rows cannot be turned into a quote stream."""


def _decimal(value: object) -> Decimal | None:
    return value if isinstance(value, Decimal) else None


def _signed_quantity(row: dict[str, Any]) -> Decimal | None:
    """A trade's quantity, signed by the aggressor.

    Positive is aggressive buying. A trade with no side cannot be signed, and
    is dropped rather than counted as zero — an unsigned trade is missing
    information, not a balanced one.
    """
    quantity = _decimal(row.get("quantity"))
    side = row.get("side")
    if quantity is None or quantity <= 0 or not isinstance(side, str):
        return None
    aggressor = side.strip().upper()
    if aggressor in {"B", "BUY"}:
        return quantity
    if aggressor in {"A", "S", "SELL"}:
        return -quantity
    return None


def quotes_from_rows(rows: Sequence[dict[str, Any]]) -> Iterator[Quote]:
    """Yield one quote per two-sided BBO row, carrying the flow since the last.

    L2_SNAPSHOT rows are skipped rather than treated as quotes. They describe
    the same book at a slower cadence, and mixing the two would put two
    different views of one moment into the series as if they were two moments.
    """
    pending_flow = Decimal(0)
    saw_trade = False
    previous: datetime | None = None

    for row in rows:
        event_type = str(row.get("event_type", "")).upper()
        received = row.get("local_receive_time")
        if not isinstance(received, datetime):
            continue
        if previous is not None and received < previous:
            raise StreamError(
                f"rows are not in receipt order: {received.isoformat()} follows "
                f"{previous.isoformat()}. Receipt order is the only sequence this "
                f"system could have observed, so it cannot be repaired here"
            )
        previous = received

        if event_type == "TRADE":
            signed = _signed_quantity(row)
            if signed is not None:
                pending_flow += signed
                saw_trade = True
            continue

        if event_type != "BBO":
            continue

        bid, ask = _decimal(row.get("bid_price")), _decimal(row.get("ask_price"))
        if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
            # A one-sided or crossed book has no mid to act on. Skipping it
            # loses a moment; inventing one puts a price in a cost measurement
            # that the market never printed.
            continue

        yield Quote(
            moment=received,
            bid=bid,
            ask=ask,
            bid_size=_decimal(row.get("bid_quantity")),
            ask_size=_decimal(row.get("ask_quantity")),
            # None, not zero, when no trade has been seen at all: "the feed
            # reported no flow" and "no trades happened" are different claims.
            flow=pending_flow if saw_trade else None,
        )
        pending_flow = Decimal(0)
        saw_trade = False
