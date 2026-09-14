"""Parsing raw Hyperliquid WebSocket frames.

This layer does one thing: turn a JSON frame into a typed, validated envelope,
or refuse it. It performs no normalization and reaches no store, so it is pure
and exhaustively testable from fixtures.

Two principles shape it.

**Tolerant about shape, strict about meaning.** Unknown fields are ignored
rather than rejected, because a venue adding a field must not stop the
recorder; but a field we rely on that is missing or unparseable is an error,
because silently substituting a default would write a plausible wrong number
into the archive.

**Numbers stay exact.** Every price and size is parsed as `Decimal` from its
string form. Hyperliquid sends decimal strings, and the official SDK's own type
definitions disagree with the wire format on at least one field (`sz` is typed
`int` where the API sends a string), so the parser accepts both spellings and
converts through `str` — never through `float`, which would introduce error
that cannot be removed later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from libs.schemas.enums import Side

CHANNEL_TRADES: Final = "trades"
CHANNEL_L2_BOOK: Final = "l2Book"
CHANNEL_BBO: Final = "bbo"
CHANNEL_ASSET_CONTEXT: Final = "activeAssetCtx"
CHANNEL_SUBSCRIPTION_ACK: Final = "subscriptionResponse"
CHANNEL_PONG: Final = "pong"
CHANNEL_ERROR: Final = "error"

DATA_CHANNELS: Final[frozenset[str]] = frozenset(
    {CHANNEL_TRADES, CHANNEL_L2_BOOK, CHANNEL_BBO, CHANNEL_ASSET_CONTEXT}
)
"""Channels that carry market data, as opposed to control frames."""

# Hyperliquid encodes the aggressor's side as "B" (bid/buy) or "A" (ask/sell).
# This mapping is the one place that convention is expressed. It is taken from
# the venue's SDK type definitions (`Side = Literal["A"] | Literal["B"]`) and
# must be confirmed against live data: an inverted taker side would flip the
# sign of every order-flow and markout feature computed downstream, while
# looking entirely plausible.
SIDE_CODES: Final[dict[str, Side]] = {"B": Side.BUY, "A": Side.SELL}

BOOK_SIDES: Final = 2
"""A book payload carries exactly [bids, asks]."""


class MessageParseError(ValueError):
    """A frame cannot be parsed into a known message. The frame is not used.

    Carries the raw text so the caller can archive it: an unparseable frame is
    evidence about the venue or about our parser, and discarding it loses the
    only copy.
    """

    def __init__(self, reason: str, *, raw: str | None = None) -> None:
        super().__init__(reason)
        self.raw = raw


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """One trade from the `trades` channel."""

    coin: str
    side: Side
    price: Decimal
    quantity: Decimal
    venue_time_ms: int
    tx_hash: str | None = None
    trade_id: int | None = None
    # The two wallets party to the trade, when the feed supplies them. This is
    # the field that makes trader-level research possible at all (ADR-006); it
    # is absent from the SDK's type definition, so it is optional here and its
    # presence is a question for live verification rather than an assumption.
    users: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BookLevel:
    """One price level."""

    price: Decimal
    quantity: Decimal
    order_count: int | None = None


@dataclass(frozen=True, slots=True)
class L2BookRecord:
    """A book snapshot from the `l2Book` channel."""

    coin: str
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    venue_time_ms: int

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None


@dataclass(frozen=True, slots=True)
class BboRecord:
    """Best bid and offer from the `bbo` channel.

    Either side may be absent — a one-sided book is unusual but representable,
    and the venue models it as a null rather than omitting the field.
    """

    coin: str
    bid: BookLevel | None
    ask: BookLevel | None
    venue_time_ms: int


@dataclass(frozen=True, slots=True)
class AssetContextRecord:
    """Derivatives state from the `activeAssetCtx` channel."""

    coin: str
    funding: Decimal | None
    open_interest: Decimal | None
    mark_price: Decimal | None
    oracle_price: Decimal | None
    mid_price: Decimal | None
    premium: Decimal | None
    day_notional_volume: Decimal | None


@dataclass(frozen=True, slots=True)
class ControlRecord:
    """A non-data frame: subscription acknowledgement, pong, or venue error."""

    channel: str
    payload: Any


@dataclass(frozen=True, slots=True)
class HyperliquidMessage:
    """A parsed frame.

    `records` holds zero or more data records; a `trades` frame carries a list,
    so one frame can produce several events. Control frames carry a single
    `ControlRecord` and are not persisted as market data.
    """

    channel: str
    records: tuple[TradeRecord | L2BookRecord | BboRecord | AssetContextRecord | ControlRecord, ...]
    raw: str

    @property
    def is_data(self) -> bool:
        return self.channel in DATA_CHANNELS


def _decimal(value: Any, field: str) -> Decimal:
    """Parse a required numeric field exactly.

    Accepts the string form the API sends and the int the SDK's types claim,
    converting through `str` so no value ever passes through a float.
    """
    if value is None:
        raise MessageParseError(f"{field} is missing")
    if isinstance(value, bool):
        raise MessageParseError(f"{field} is a boolean, expected a number")
    if isinstance(value, float):
        raise MessageParseError(
            f"{field} arrived as a float ({value!r}); refusing to store a value "
            f"that may already have lost precision"
        )
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MessageParseError(f"{field} is not a number: {value!r}") from exc


def _optional_decimal(value: Any, field: str) -> Decimal | None:
    """Parse an optional numeric field. Absent stays absent."""
    if value is None or value == "":
        return None
    return _decimal(value, field)


def _int(value: Any, field: str) -> int:
    if value is None:
        raise MessageParseError(f"{field} is missing")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise MessageParseError(f"{field} is not an integer: {value!r}")
    try:
        return int(value)
    except ValueError as exc:
        raise MessageParseError(f"{field} is not an integer: {value!r}") from exc


def _side(value: Any) -> Side:
    if not isinstance(value, str) or value not in SIDE_CODES:
        raise MessageParseError(
            f"side must be one of {', '.join(sorted(SIDE_CODES))}, got {value!r}"
        )
    return SIDE_CODES[value]


def _level(entry: Any, field: str) -> BookLevel:
    if not isinstance(entry, dict):
        raise MessageParseError(f"{field} is not an object: {entry!r}")
    count = entry.get("n")
    return BookLevel(
        price=_decimal(entry.get("px"), f"{field}.px"),
        quantity=_decimal(entry.get("sz"), f"{field}.sz"),
        order_count=None if count is None else _int(count, f"{field}.n"),
    )


def _parse_trade(entry: Any) -> TradeRecord:
    if not isinstance(entry, dict):
        raise MessageParseError(f"trade is not an object: {entry!r}")
    users = entry.get("users")
    return TradeRecord(
        coin=_require_str(entry.get("coin"), "trade.coin"),
        side=_side(entry.get("side")),
        price=_decimal(entry.get("px"), "trade.px"),
        quantity=_decimal(entry.get("sz"), "trade.sz"),
        venue_time_ms=_int(entry.get("time"), "trade.time"),
        tx_hash=entry.get("hash") if isinstance(entry.get("hash"), str) else None,
        trade_id=None if entry.get("tid") is None else _int(entry.get("tid"), "trade.tid"),
        users=tuple(str(user) for user in users) if isinstance(users, list) else (),
    )


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MessageParseError(f"{field} must be a non-empty string, got {value!r}")
    return value


def _parse_l2_book(data: Any) -> L2BookRecord:
    if not isinstance(data, dict):
        raise MessageParseError(f"l2Book data is not an object: {data!r}")
    levels = data.get("levels")
    if not isinstance(levels, list) or len(levels) != BOOK_SIDES:
        raise MessageParseError(
            f"l2Book levels must be a two-element array of [bids, asks], got {levels!r}"
        )
    bid_levels, ask_levels = levels
    if not isinstance(bid_levels, list) or not isinstance(ask_levels, list):
        raise MessageParseError("l2Book levels must each be an array")
    return L2BookRecord(
        coin=_require_str(data.get("coin"), "l2Book.coin"),
        bids=tuple(_level(entry, "bid") for entry in bid_levels),
        asks=tuple(_level(entry, "ask") for entry in ask_levels),
        venue_time_ms=_int(data.get("time"), "l2Book.time"),
    )


def _parse_bbo(data: Any) -> BboRecord:
    if not isinstance(data, dict):
        raise MessageParseError(f"bbo data is not an object: {data!r}")
    pair = data.get("bbo")
    if not isinstance(pair, list) or len(pair) != BOOK_SIDES:
        raise MessageParseError(f"bbo must be a two-element array of [bid, ask], got {pair!r}")
    bid, ask = pair
    return BboRecord(
        coin=_require_str(data.get("coin"), "bbo.coin"),
        bid=None if bid is None else _level(bid, "bbo.bid"),
        ask=None if ask is None else _level(ask, "bbo.ask"),
        venue_time_ms=_int(data.get("time"), "bbo.time"),
    )


def _parse_asset_context(data: Any) -> AssetContextRecord:
    if not isinstance(data, dict):
        raise MessageParseError(f"activeAssetCtx data is not an object: {data!r}")
    context = data.get("ctx")
    if not isinstance(context, dict):
        raise MessageParseError(f"activeAssetCtx.ctx is not an object: {context!r}")
    return AssetContextRecord(
        coin=_require_str(data.get("coin"), "activeAssetCtx.coin"),
        funding=_optional_decimal(context.get("funding"), "ctx.funding"),
        open_interest=_optional_decimal(context.get("openInterest"), "ctx.openInterest"),
        mark_price=_optional_decimal(context.get("markPx"), "ctx.markPx"),
        oracle_price=_optional_decimal(context.get("oraclePx"), "ctx.oraclePx"),
        mid_price=_optional_decimal(context.get("midPx"), "ctx.midPx"),
        premium=_optional_decimal(context.get("premium"), "ctx.premium"),
        day_notional_volume=_optional_decimal(context.get("dayNtlVlm"), "ctx.dayNtlVlm"),
    )


def parse_message(raw: str) -> HyperliquidMessage:
    """Parse one WebSocket frame.

    Raises `MessageParseError` for malformed JSON, a missing channel, or a
    payload whose required fields cannot be read. The caller archives the raw
    frame either way — an unparseable frame is still evidence.
    """
    try:
        frame = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MessageParseError(f"not valid JSON: {exc}", raw=raw) from exc

    if not isinstance(frame, dict):
        raise MessageParseError(f"frame is not an object: {type(frame).__name__}", raw=raw)

    channel = frame.get("channel")
    if not isinstance(channel, str) or not channel:
        raise MessageParseError(f"frame has no channel: {frame!r}", raw=raw)

    data = frame.get("data")

    try:
        if channel == CHANNEL_TRADES:
            if not isinstance(data, list):
                # Raised inside the try so the handler below can attach the raw
                # frame; extracting it to a helper would hide that coupling.
                raise MessageParseError(  # noqa: TRY301
                    f"trades data is not an array: {data!r}"
                )
            records: tuple[Any, ...] = tuple(_parse_trade(entry) for entry in data)
        elif channel == CHANNEL_L2_BOOK:
            records = (_parse_l2_book(data),)
        elif channel == CHANNEL_BBO:
            records = (_parse_bbo(data),)
        elif channel == CHANNEL_ASSET_CONTEXT:
            records = (_parse_asset_context(data),)
        else:
            # Control frames and channels we do not subscribe to are preserved
            # without interpretation, so an unexpected channel is recorded
            # rather than dropped.
            records = (ControlRecord(channel=channel, payload=data),)
    except MessageParseError as exc:
        # Re-raised so the raw frame travels with the error: the caller archives
        # it, and an unparseable frame is the only evidence of what arrived.
        raise MessageParseError(str(exc), raw=raw) from exc

    return HyperliquidMessage(channel=channel, records=records, raw=raw)
