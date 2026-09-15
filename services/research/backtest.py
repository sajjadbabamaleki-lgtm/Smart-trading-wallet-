"""Event-driven backtesting (M6).

The Baseline Strategy Gate (Rev.2 §26) opens with point-in-time correctness and
lookahead checks, and this engine's whole design is those two lines. Everything
else it does is bookkeeping.

**A strategy cannot see the future, structurally.** It receives one event at a
time through `on_event` and may return an intent. It is never handed the series,
never told what comes next, and holds only the state it accumulated itself.
Lookahead is not discouraged here, it is unavailable — which matters because
lookahead is the defect that makes a backtest profitable and a live system
broken, and code review does not reliably catch it.

**A decision is filled later, at a price the market actually printed.** An
intent formed at T executes at the first quote at or after T + latency, at the
touch. This is where the ~322 ms arrival floor stops being a caveat and starts
costing money: the engine never fills at the price the strategy saw, because
nobody ever does.

That also answers the question `measure.py` deliberately refused. Adverse drift
is not a constant to look up — it is the difference between the decision price
and the fill price, and it exists only for a specific strategy on a specific
day. Here it is simply measured.

**Spread is paid once.** Fills are at the touch, so crossing is already in the
fill price; charging `CostModel.half_spread_bps` on top would double it and
overstate costs by roughly a factor of two. Only the fee is applied separately,
and `CostModel.fee_only_bps` exists to make that explicit at the call site.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from services.research.costs import BPS, CostModel


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


@dataclass(frozen=True, slots=True)
class Quote:
    """A two-sided quote, as the engine consumes them."""

    moment: datetime
    bid: Decimal
    ask: Decimal

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2

    def touch(self, side: Side) -> Decimal:
        """The price a crossing order of this side pays.

        A buy lifts the ask and a sell hits the bid. Filling at mid is the
        commonest way a backtest invents an edge it does not have: half the
        spread, on every side of every trade.
        """
        return self.ask if side is Side.BUY else self.bid


@dataclass(frozen=True, slots=True)
class Intent:
    """A strategy's request to trade. It is a request, not a fill."""

    side: Side
    quantity: Decimal
    reason: str = ""

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("intent quantity must be positive")


class Strategy(Protocol):
    """What the engine requires of a strategy.

    Deliberately narrow. One event in, at most one intent out, and no way to
    ask the engine anything — a strategy that cannot reach the future cannot
    accidentally use it.
    """

    name: str

    def on_event(self, quote: Quote) -> Intent | None:
        """React to one quote. Called in order, exactly once per quote."""
        ...


@dataclass(frozen=True, slots=True)
class Fill:
    """One executed side of a trade."""

    decided_at: datetime
    filled_at: datetime
    side: Side
    quantity: Decimal
    decision_price: Decimal
    fill_price: Decimal
    fee: Decimal
    reason: str = ""

    @property
    def latency(self) -> timedelta:
        return self.filled_at - self.decided_at

    @property
    def slippage_bps(self) -> Decimal:
        """How far the fill was from what the strategy saw, in its own favour or not.

        Positive means the fill was worse than the decision price. This is the
        measured adverse drift for this trade — not a model input, an outcome.
        """
        if self.decision_price <= 0:
            return Decimal(0)
        moved = (self.fill_price - self.decision_price) * self.side.sign
        return moved / self.decision_price * BPS

    @property
    def notional(self) -> Decimal:
        return self.fill_price * self.quantity


@dataclass(frozen=True, slots=True)
class Trade:
    """A completed round trip."""

    entry: Fill
    exit: Fill

    @property
    def gross_pnl(self) -> Decimal:
        """Before fees. Includes the spread, because fills are at the touch."""
        moved = self.exit.fill_price - self.entry.fill_price
        return moved * self.entry.quantity * self.entry.side.sign

    @property
    def fees(self) -> Decimal:
        return self.entry.fee + self.exit.fee

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.fees

    @property
    def net_bps(self) -> Decimal:
        """Net return on the entry notional, in basis points."""
        if self.entry.notional <= 0:
            return Decimal(0)
        return self.net_pnl / self.entry.notional * BPS

    @property
    def held(self) -> timedelta:
        return self.exit.filled_at - self.entry.filled_at


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """What a run produced, and what it is allowed to claim.

    Gross and net are both carried and never collapsed. Rev.2 §25: a strategy
    profitable before costs and unprofitable after has demonstrated no edge, and
    the only way to see that is to keep both numbers visible.
    """

    strategy: str
    trades: tuple[Trade, ...]
    quotes_seen: int
    intents_formed: int
    intents_unfilled: int
    latency: timedelta

    @property
    def gross_pnl(self) -> Decimal:
        return sum((trade.gross_pnl for trade in self.trades), Decimal(0))

    @property
    def fees(self) -> Decimal:
        return sum((trade.fees for trade in self.trades), Decimal(0))

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.fees

    @property
    def wins(self) -> int:
        return sum(1 for trade in self.trades if trade.net_pnl > 0)

    @property
    def mean_adverse_drift_bps(self) -> Decimal | None:
        """Average measured slippage on entries, in basis points.

        The answer `measure.py` refused to guess. None with no trades, because
        an average over nothing is not zero.
        """
        if not self.trades:
            return None
        total = sum((trade.entry.slippage_bps for trade in self.trades), Decimal(0))
        return total / len(self.trades)

    @property
    def costs_exceeded_edge(self) -> bool | None:
        """Whether the strategy made money before costs and lost it after.

        The specific finding §25 names. None when there were no trades — a
        strategy that never traded has not demonstrated this or its opposite.
        """
        if not self.trades:
            return None
        return self.gross_pnl > 0 and self.net_pnl <= 0

    def summary(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "quotes_seen": self.quotes_seen,
            "intents_formed": self.intents_formed,
            "intents_unfilled": self.intents_unfilled,
            "trades": len(self.trades),
            "wins": self.wins,
            "gross_pnl": str(self.gross_pnl),
            "fees": str(self.fees),
            "net_pnl": str(self.net_pnl),
            "costs_exceeded_edge": self.costs_exceeded_edge,
            "mean_adverse_drift_bps": (
                None if self.mean_adverse_drift_bps is None else str(self.mean_adverse_drift_bps)
            ),
            "latency_ms": self.latency.total_seconds() * 1000,
        }


@dataclass
class _Pending:
    """An intent waiting for the market to reach its execution time."""

    intent: Intent
    decided_at: datetime
    decision_price: Decimal
    execute_at: datetime


@dataclass
class BacktestEngine:
    """Replays quotes past a strategy and executes what it asks for.

    `latency` is the whole decision-to-fill path, not just data arrival. The
    default is the measured arrival floor alone, which is the most optimistic
    figure defensible from this project's own evidence: it counts the venue's
    publication delay and nothing of decoding, features, inference, the risk
    check, or transmission. A realistic end-to-end figure is larger, and a run
    that uses the default should say so.
    """

    strategy: Strategy
    costs: CostModel = field(default_factory=CostModel)
    latency: timedelta = timedelta(milliseconds=322)

    def run(self, quotes: Iterable[Quote]) -> BacktestResult:
        ordered = list(quotes)
        self._check_ordered(ordered)

        pending: list[_Pending] = []
        open_fill: Fill | None = None
        trades: list[Trade] = []
        intents = 0

        for quote in ordered:
            # Execute first, then decide. A decision made on this quote cannot
            # fill on the same quote — the latency has not elapsed — and doing
            # it in the other order would let one arrive instantly.
            still_pending: list[_Pending] = []
            for waiting in pending:
                if quote.moment < waiting.execute_at:
                    still_pending.append(waiting)
                    continue
                fill = self._fill(waiting, quote)
                if open_fill is None:
                    open_fill = fill
                elif open_fill.side is not fill.side:
                    trades.append(Trade(entry=open_fill, exit=fill))
                    open_fill = None
                else:
                    # Same side again: this engine holds one position at a time,
                    # so the request is dropped rather than silently doubling
                    # exposure. A strategy that wants scaling needs an engine
                    # that models it, not one that quietly obliges.
                    continue
            pending = still_pending

            intent = self.strategy.on_event(quote)
            if intent is not None:
                intents += 1
                pending.append(
                    _Pending(
                        intent=intent,
                        decided_at=quote.moment,
                        decision_price=quote.touch(intent.side),
                        execute_at=quote.moment + self.latency,
                    )
                )

        return BacktestResult(
            strategy=self.strategy.name,
            trades=tuple(trades),
            quotes_seen=len(ordered),
            # An intent still waiting when the data ran out never became a
            # trade. Counted, because a strategy whose intents mostly expire
            # unfilled is not the strategy its trade list describes.
            intents_formed=intents,
            intents_unfilled=len(pending) + (1 if open_fill is not None else 0),
            latency=self.latency,
        )

    def _fill(self, waiting: _Pending, quote: Quote) -> Fill:
        """Execute one pending intent against the quote that reached its time."""
        price = quote.touch(waiting.intent.side)
        notional = price * waiting.intent.quantity
        return Fill(
            decided_at=waiting.decided_at,
            filled_at=quote.moment,
            side=waiting.intent.side,
            quantity=waiting.intent.quantity,
            decision_price=waiting.decision_price,
            fill_price=price,
            # Only the fee. The spread is already in `price`, because the fill
            # is at the touch; charging half_spread_bps here as well would
            # count crossing twice.
            fee=notional * self.costs.fee_only_bps / BPS,
            reason=waiting.intent.reason,
        )

    @staticmethod
    def _check_ordered(quotes: Sequence[Quote]) -> None:
        """Refuse an out-of-order series rather than silently backtesting it.

        Time going backwards in the input is how a backtest ends up filling
        before it decided. The recorder's own output is ordered; a hand-built
        series may not be, and the failure is silent unless it is checked.
        """
        for earlier, later in itertools.pairwise(quotes):
            if later.moment < earlier.moment:
                raise ValueError(
                    f"quotes are not in time order: {later.moment.isoformat()} follows "
                    f"{earlier.moment.isoformat()}. A backtest over unordered data can "
                    f"fill before it decided."
                )
