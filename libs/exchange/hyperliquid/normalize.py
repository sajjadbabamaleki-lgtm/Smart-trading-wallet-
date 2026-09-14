"""Hyperliquid payloads to canonical events.

The boundary where venue vocabulary ends. Above this function nothing knows
that Hyperliquid calls an asset a "coin", encodes the taker side as "A"/"B", or
sends millisecond timestamps.

Normalization is a pure function of `(parsed message, receipt timestamps)`, so
the same input always produces the same output. That is what lets a replay be
deterministic (Build 0.1 Rev.2 §22) and what lets a normalization defect be
corrected by re-deriving from the preserved raw frame rather than by
re-collecting the data (Rev.2 §20).

Every produced event carries both the venue's timestamp and our own receipt
time (ADR-007), because only the second is ours to measure and only the
difference between them says whether a fast-decaying signal was reachable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from libs.domain.ids import new_event_id
from libs.domain.timestamps import EventTimestamps
from libs.exchange.hyperliquid.messages import (
    AssetContextRecord,
    BboRecord,
    ControlRecord,
    HyperliquidMessage,
    L2BookRecord,
    TradeRecord,
)
from libs.schemas.enums import DataQualityStatus, MarketEventType, PitStatus, TraderEventType
from libs.schemas.market_event import MarketEvent
from libs.schemas.trader_event import TraderEvent

VENUE = "hyperliquid"
SOURCE = "hyperliquid_ws"

MAX_PLAUSIBLE_VENUE_MS: Final = 4_102_444_800_000
"""Year 2100 in milliseconds.

A venue timestamp beyond this is a unit error - seconds or microseconds
mistaken for milliseconds - rather than a real time."""


class NormalizationError(ValueError):
    """A parsed record cannot be expressed as a canonical event."""


def _instrument(coin: str) -> str:
    """Canonical instrument name.

    Hyperliquid identifies a perpetual by the bare coin; the platform names the
    instrument explicitly so a future spot or dated market is not confused with
    it.
    """
    return f"{coin}-PERP"


def _venue_time(milliseconds: int) -> datetime:
    """Convert a venue millisecond timestamp to UTC.

    A non-positive or absurdly large value is refused rather than converted: a
    timestamp of 0 would silently place the event at the Unix epoch, which
    corrupts every time-ordered query it participates in.
    """
    if milliseconds <= 0:
        raise NormalizationError(f"venue timestamp must be positive, got {milliseconds}")
    if milliseconds > MAX_PLAUSIBLE_VENUE_MS:
        raise NormalizationError(
            f"venue timestamp {milliseconds} is beyond year 2100; likely a unit error"
        )
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def _stamps(record_time_ms: int, receipt: EventTimestamps) -> EventTimestamps:
    """Combine the venue's timestamp with our receipt timestamps."""
    return receipt.model_copy(update={"exchange_time": _venue_time(record_time_ms)})


def _trade_events(
    record: TradeRecord, receipt: EventTimestamps
) -> tuple[tuple[MarketEvent, ...], tuple[TraderEvent, ...]]:
    """A trade becomes one market event and, when identified, trader events.

    The market event is the anonymous fact: a trade happened at this price and
    size, with this aggressor side. The trader events are the identified facts:
    these wallets were party to it.

    Both are emitted because they answer different questions and have different
    point-in-time properties. The market event is what an anonymous baseline
    model sees; the trader events are what TBIE would need, and are recorded now
    only because they cannot be reconstructed later (ADR-006). Neither depends
    on the other.
    """
    stamps = _stamps(record.venue_time_ms, receipt)
    market = MarketEvent(
        event_id=new_event_id(),
        source=SOURCE,
        venue=VENUE,
        asset=record.coin,
        instrument=_instrument(record.coin),
        event_type=MarketEventType.TRADE,
        timestamps=stamps,
        # `tid` identifies; it does not order. Hyperliquid documents it as a
        # 50-bit hash of the buyer's and seller's order ids, so consecutive
        # trades carry unrelated values and the venue publishes no sequence
        # number on this channel at all.
        venue_event_id=None if record.trade_id is None else str(record.trade_id),
        sequence=None,
        price=record.price,
        quantity=record.quantity,
        side=record.side,
        raw_reference=record.tx_hash,
        quality_status=DataQualityStatus.UNKNOWN,
        pit_status=PitStatus.PIT_SAFE,
    )

    # The venue reports the two parties without saying which took and which
    # made. Guessing would be worse than leaving it unstated: an inverted
    # aggressor attribution would flip the sign of every markout computed from
    # it. Each party is recorded with the trade's own aggressor side, and
    # resolving maker from taker is deferred to the research layer, where the
    # question can be answered against the book rather than assumed here.
    traders = tuple(
        TraderEvent(
            event_id=new_event_id(),
            source=SOURCE,
            venue=VENUE,
            asset=record.coin,
            instrument=_instrument(record.coin),
            event_type=TraderEventType.FILL,
            timestamps=stamps,
            wallet=wallet,
            counterparty=next((other for other in record.users if other != wallet), None),
            side=record.side,
            price=record.price,
            quantity=record.quantity,
            notional=record.price * record.quantity,
            order_id=None,
            client_order_id=None,
            raw_reference=record.tx_hash,
            quality_status=DataQualityStatus.UNKNOWN,
            pit_status=PitStatus.PIT_SAFE,
        )
        for wallet in record.users
    )
    return (market,), traders


def _bbo_event(record: BboRecord, receipt: EventTimestamps) -> MarketEvent:
    if record.bid is None and record.ask is None:
        raise NormalizationError("bbo carries neither a bid nor an ask")
    return MarketEvent(
        event_id=new_event_id(),
        source=SOURCE,
        venue=VENUE,
        asset=record.coin,
        instrument=_instrument(record.coin),
        event_type=MarketEventType.BBO,
        timestamps=_stamps(record.venue_time_ms, receipt),
        bid_price=None if record.bid is None else record.bid.price,
        bid_quantity=None if record.bid is None else record.bid.quantity,
        ask_price=None if record.ask is None else record.ask.price,
        ask_quantity=None if record.ask is None else record.ask.quantity,
        quality_status=DataQualityStatus.UNKNOWN,
        pit_status=PitStatus.PIT_SAFE,
    )


def _l2_event(record: L2BookRecord, receipt: EventTimestamps) -> MarketEvent:
    """A book snapshot becomes one event carrying its top of book.

    Only the best bid and ask are promoted into typed columns. The full depth
    stays in the preserved raw frame: storing every level as a normalized row
    would multiply the table's size by the level count for data no M2 consumer
    reads, and Phase 3 §32 is explicit that event-level book history is the one
    dataset whose volume must not be treated like the others. Depth is
    reconstructed from the raw archive when a microstructure experiment needs
    it — which is exactly what preserving raw frames is for.
    """
    best_bid = record.best_bid
    best_ask = record.best_ask
    if best_bid is None and best_ask is None:
        raise NormalizationError("l2Book snapshot has no levels on either side")
    return MarketEvent(
        event_id=new_event_id(),
        source=SOURCE,
        venue=VENUE,
        asset=record.coin,
        instrument=_instrument(record.coin),
        event_type=MarketEventType.L2_SNAPSHOT,
        timestamps=_stamps(record.venue_time_ms, receipt),
        bid_price=None if best_bid is None else best_bid.price,
        bid_quantity=None if best_bid is None else best_bid.quantity,
        ask_price=None if best_ask is None else best_ask.price,
        ask_quantity=None if best_ask is None else best_ask.quantity,
        quality_status=DataQualityStatus.UNKNOWN,
        pit_status=PitStatus.PIT_SAFE,
    )


def _asset_context_events(
    record: AssetContextRecord, receipt: EventTimestamps
) -> tuple[MarketEvent, ...]:
    """Asset context becomes one event per populated derivatives variable.

    Funding, open interest, mark price and oracle price are separate facts with
    separate update cadences, so each is its own event rather than one wide row
    where most columns are null. That keeps a query for funding history from
    scanning mark-price updates.

    `activeAssetCtx` carries no timestamp of its own, so these events have only
    our receipt time. That asymmetry is recorded rather than papered over: the
    absent venue time stays absent (Build 0.1 Rev.1 §32).
    """
    fields: tuple[tuple[MarketEventType, str, Decimal | None], ...] = (
        (MarketEventType.FUNDING, "funding_rate", record.funding),
        (MarketEventType.OPEN_INTEREST, "open_interest", record.open_interest),
        (MarketEventType.MARK_PRICE, "price", record.mark_price),
        (MarketEventType.ORACLE_PRICE, "price", record.oracle_price),
    )
    events: list[MarketEvent] = []
    for event_type, field, value in fields:
        if value is None:
            continue
        events.append(
            MarketEvent(
                event_id=new_event_id(),
                source=SOURCE,
                venue=VENUE,
                asset=record.coin,
                instrument=_instrument(record.coin),
                event_type=event_type,
                timestamps=receipt,
                quality_status=DataQualityStatus.UNKNOWN,
                pit_status=PitStatus.PIT_SAFE,
                **{field: value},
            )
        )
    return tuple(events)


def normalize(
    message: HyperliquidMessage, receipt: EventTimestamps
) -> tuple[tuple[MarketEvent, ...], tuple[TraderEvent, ...]]:
    """Normalize one parsed frame into canonical events.

    Returns market events and trader events separately, since they are stored
    apart and have different access patterns. A control frame yields neither.
    """
    market: list[MarketEvent] = []
    traders: list[TraderEvent] = []

    for record in message.records:
        if isinstance(record, ControlRecord):
            continue
        if isinstance(record, TradeRecord):
            trade_market, trade_traders = _trade_events(record, receipt)
            market.extend(trade_market)
            traders.extend(trade_traders)
        elif isinstance(record, BboRecord):
            market.append(_bbo_event(record, receipt))
        elif isinstance(record, L2BookRecord):
            market.append(_l2_event(record, receipt))
        elif isinstance(record, AssetContextRecord):
            market.extend(_asset_context_events(record, receipt))
        else:  # pragma: no cover - exhaustive over the record union
            raise NormalizationError(f"unhandled record type {type(record).__name__}")

    return tuple(market), tuple(traders)
