"""The first strategy: a baseline, built to be falsified.

This exists to be measured, not to be believed. Its purpose is to produce the
first honest number for "does anything clear the cost on this venue", and a
baseline that cannot fail is useless for that.

**Why these two signals and not something cleverer.** Depth imbalance and
signed order flow are the two best-supported short-horizon effects in the
microstructure literature, and this project's own research audit records that
the anonymous benchmark a sophisticated signal must beat *already contains
both*. Starting anywhere else would mean competing against a straw man: a
price-only baseline is easy to beat and proves nothing about whether the
harder ideas are worth building.

**Why the horizon is seconds.** Measured on this venue: a maker round trip
costs 3.41 bps, and BTC's mid needs roughly seven seconds to move that far
once. Below that the cost is larger than the move; far above it the signals
these use have decayed. Seconds to a minute is the window the measurements
leave open, and it is where this looks.

**Why the parameters are arguments and not constants.** A threshold chosen by
trying values until the backtest passes is the overfitting this project's own
gate exists to catch (Rev.2 §26). They are passed in, the defaults are round
numbers rather than tuned ones, and a run that reports a profit at one setting
has demonstrated nothing until walk-forward says the setting survives out of
sample.

**What it deliberately does not do.** It holds one position at a time, exits on
a timer rather than on a second signal, and never sizes by conviction. Each of
those is a decision that could be researched; making them all at once, in a
first baseline, would produce a result nobody could attribute.

The null hypothesis is that this loses money net of cost. That is the expected
result, it is a valid outcome, and nothing here is built to avoid it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from services.research.backtest import Intent, Quote, Side

# Round numbers on purpose. Each is a hypothesis this run exists to test, not a
# setting that was tuned until the answer was pleasant.
DEFAULT_IMBALANCE_THRESHOLD = Decimal("0.30")
DEFAULT_FLOW_WINDOW = timedelta(seconds=10)
DEFAULT_HOLD = timedelta(seconds=30)
DEFAULT_QUANTITY = Decimal("0.001")


@dataclass
class FlowWindow:
    """Signed taker quantity over a trailing window.

    Kept as a deque of (moment, signed quantity) rather than a decayed scalar
    so the window has an exact edge. An exponential decay would be smoother and
    would make "the last ten seconds" mean something slightly different at every
    call, which is not a property a cost-sensitive measurement should have.
    """

    window: timedelta = DEFAULT_FLOW_WINDOW
    _events: deque[tuple[datetime, Decimal]] = field(default_factory=deque, init=False)
    _total: Decimal = field(default=Decimal(0), init=False)

    def observe(self, moment: datetime, signed_quantity: Decimal) -> None:
        self._events.append((moment, signed_quantity))
        self._total += signed_quantity
        self._expire(moment)

    def value(self, moment: datetime) -> Decimal:
        self._expire(moment)
        return self._total

    def _expire(self, moment: datetime) -> None:
        cutoff = moment - self.window
        while self._events and self._events[0][0] < cutoff:
            _, quantity = self._events.popleft()
            self._total -= quantity


@dataclass
class BaselineStrategy:
    """Buy when the book and the flow agree, hold, exit on a timer.

    Agreement is the point. Either signal alone fires constantly — depth
    imbalance at the touch of a BTC book swings past any fixed threshold many
    times a minute — and a strategy that trades on every swing pays the round
    trip every time. Requiring both to point the same way is the cheapest
    available filter, and it is a testable claim rather than a safeguard: if
    agreement adds nothing, the two-signal version will not beat the one-signal
    version, and that is a result.
    """

    name: str = "baseline-imbalance-flow"
    threshold: Decimal = DEFAULT_IMBALANCE_THRESHOLD
    hold: timedelta = DEFAULT_HOLD
    quantity: Decimal = DEFAULT_QUANTITY
    flow_window: timedelta = DEFAULT_FLOW_WINDOW

    flow: FlowWindow = field(init=False)
    _entered_at: datetime | None = field(default=None, init=False)
    _position: Side | None = field(default=None, init=False)
    signals_seen: int = field(default=0, init=False)
    agreements: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if not Decimal(0) < self.threshold <= Decimal(1):
            raise ValueError("threshold must be in (0, 1]")
        if self.hold <= timedelta(0):
            raise ValueError("hold must be positive")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        self.flow = FlowWindow(window=self.flow_window)

    def on_event(self, quote: Quote) -> Intent | None:
        """React to one quote, and never to anything else.

        The engine calls this once per quote in order and answers no questions,
        so everything below is a function of quotes already seen. There is no
        path here that can reach a later price.
        """
        if quote.flow is not None:
            self.flow.observe(quote.moment, quote.flow)

        if self._position is not None:
            return self._maybe_exit(quote)

        imbalance = quote.book_imbalance
        if imbalance is None:
            # No depth, no signal. A missing book is not a balanced one.
            return None

        self.signals_seen += 1
        flow = self.flow.value(quote.moment)

        wants = self._direction(imbalance, flow)
        if wants is None:
            return None

        self.agreements += 1
        self._position = wants
        self._entered_at = quote.moment
        return Intent(
            side=wants,
            quantity=self.quantity,
            reason=f"imbalance {imbalance:.3f}, flow {flow}",
        )

    def _direction(self, imbalance: Decimal, flow: Decimal) -> Side | None:
        """Both signals, or neither.

        Flow is required to be non-zero rather than merely non-negative: a
        window with no trades in it agrees with nothing, and treating silence
        as confirmation is how a filter stops filtering.
        """
        if imbalance >= self.threshold and flow > 0:
            return Side.BUY
        if imbalance <= -self.threshold and flow < 0:
            return Side.SELL
        return None

    def _maybe_exit(self, quote: Quote) -> Intent | None:
        """Close on the timer, and only on the timer.

        Exiting on a fresh signal would make entry and exit two different
        experiments sharing one result, and there would be no way afterwards to
        say which of them worked.
        """
        if self._entered_at is None:  # pragma: no cover - set together with _position
            return None
        if quote.moment - self._entered_at < self.hold:
            return None

        closing = Side.SELL if self._position is Side.BUY else Side.BUY
        self._position = None
        self._entered_at = None
        return Intent(side=closing, quantity=self.quantity, reason="hold elapsed")


@dataclass
class BookOnlyStrategy(BaselineStrategy):
    """The same strategy with the flow filter removed.

    Its entire purpose is to be the thing the two-signal version is compared
    against. If requiring agreement adds nothing, this will do as well or
    better, and the honest conclusion is that the filter was decoration.
    """

    name: str = "baseline-imbalance-only"

    def _direction(self, imbalance: Decimal, flow: Decimal) -> Side | None:  # noqa: ARG002
        # `flow` is ignored deliberately, and the signature is kept so this is
        # the same experiment with one term removed rather than a different one.
        if imbalance >= self.threshold:
            return Side.BUY
        if imbalance <= -self.threshold:
            return Side.SELL
        return None


@dataclass
class AlwaysFlatStrategy:
    """Trades nothing, ever.

    The control. A backtest harness that reports a profit for this has a defect,
    and one that reports a loss for it is charging costs it should not. Running
    it is cheap and it has caught this class of error in other systems.
    """

    name: str = "control-flat"

    def on_event(self, quote: Quote) -> Intent | None:  # noqa: ARG002 - the point
        return None
