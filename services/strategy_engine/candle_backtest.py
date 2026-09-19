"""Backtesting on candles: decide at the close, fill at the next open.

The tick backtester in `services/research/backtest.py` fills an intent at the
first quote after a millisecond latency, which is the right model for a
strategy that reacts to quotes. It is the wrong model here. A rule that reads a
completed candle knows nothing until that candle closes, and the first price it
can actually transact at is the next candle's open.

**That one sentence is the whole point of this module.** Filling at the close
of the candle you decided on is the commonest lookahead in candle backtesting
and it is nearly invisible: the code looks right, the equity curve looks
plausible, and the strategy is trading on a price that was only known after the
decision. So the pairing of a decision to its fill happens in one function,
`execution_pairs`, which is tested, and the engine cannot reach a candle that
function did not hand it.

**Costs are charged on every position change.** Entering, exiting and
reversing. A reversal is two fills, not one, and treating it as one understates
the cost of a rule that flips often by exactly half.

**Funding is not charged, and is reported instead.** Hyperliquid settles
funding hourly, so a position held for days pays it many times, and at this
horizon it is a real cost rather than a rounding error. This project has not
downloaded funding-rate history, so charging a guessed rate would put an
invented number inside the result. Position-hours are counted and reported so
the exposure is visible, and `fundingHistory` from the venue is the honest fix.

**Equity is marked to market every candle.** Not only at exits — a drawdown
that happened inside an open position is a drawdown that happened, and Phase 1
§1 puts capital preservation above return. A maximum drawdown computed from
closed trades alone can understate the real one by a lot.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from libs.exchange.hyperliquid.candles import Candle
from services.research.costs import BPS, CostModel
from services.strategy_engine.decisions import Decision, Rule
from services.strategy_engine.features import FeatureConfig, FeatureSet, feature_series


def execution_pairs(
    candles: Sequence[Candle], config: FeatureConfig | None = None
) -> Iterator[tuple[FeatureSet, Candle]]:
    """Pair each chart reading with the candle a decision on it can fill in.

    The reading at candle *i* becomes actionable when candle *i* closes, and
    the earliest price available after that is candle *i + 1*'s open. So the
    last reading in a series has no pair and is dropped: a decision with
    nowhere to execute is not a trade, and carrying it as one would let the
    final candle of every backtest be traded on hindsight.

    Isolated here because this is the lookahead-sensitive join, and because a
    function that yields pairs can be tested while an inline loop cannot.
    """
    resolved = config or FeatureConfig()
    readings = list(feature_series(candles, resolved))
    first = resolved.warmup - 1
    for offset, reading in enumerate(readings):
        execution_index = first + offset + 1
        if execution_index >= len(candles):
            return
        yield reading, candles[execution_index]


@dataclass(frozen=True, slots=True)
class CandleTrade:
    """One completed position, from the fill that opened it to the fill that closed it."""

    side: Decision
    opened_at: datetime
    closed_at: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    fees: Decimal

    @property
    def gross_pnl(self) -> Decimal:
        return (self.exit_price - self.entry_price) * self.quantity * self.side.sign

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.fees

    @property
    def notional(self) -> Decimal:
        return self.entry_price * self.quantity

    @property
    def net_bps(self) -> Decimal:
        if self.notional <= 0:
            return Decimal(0)
        return self.net_pnl / self.notional * BPS

    @property
    def held(self) -> timedelta:
        return self.closed_at - self.opened_at


@dataclass(frozen=True, slots=True)
class CandleBacktestResult:
    """What a run produced, and what it is not allowed to hide.

    Gross and net are both carried, per Rev.2 §25. So is the drawdown, because
    Phase 1 §1 ranks capital preservation above return and a report of return
    alone cannot be read against that objective. So is exposure, because a rule
    that is in the market a tenth of the time and one that is always in it are
    not comparable on return.
    """

    rule: str
    asset: str
    interval: str
    trades: tuple[CandleTrade, ...]
    equity_curve: tuple[tuple[datetime, Decimal], ...]
    starting_equity: Decimal
    candles_seen: int
    candles_in_position: int
    position_hours: Decimal

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
    def return_pct(self) -> Decimal:
        if self.starting_equity <= 0:
            return Decimal(0)
        return self.net_pnl / self.starting_equity * 100

    @property
    def wins(self) -> int:
        return sum(1 for trade in self.trades if trade.net_pnl > 0)

    @property
    def win_rate(self) -> Decimal | None:
        """None with no trades. A win rate over nothing is not zero percent."""
        if not self.trades:
            return None
        return Decimal(self.wins) / Decimal(len(self.trades)) * 100

    @property
    def exposure_pct(self) -> Decimal:
        if not self.candles_seen:
            return Decimal(0)
        return Decimal(self.candles_in_position) / Decimal(self.candles_seen) * 100

    @property
    def max_drawdown_pct(self) -> Decimal:
        """The worst peak-to-trough fall in marked-to-market equity.

        Computed over the full curve rather than over closed trades, because a
        loss that was recovered before the exit was still a loss the account
        lived through — and it is what a position limit or a margin call would
        have reacted to.
        """
        peak = self.starting_equity
        worst = Decimal(0)
        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                fall = (peak - equity) / peak * 100
                worst = max(worst, fall)
        return worst

    @property
    def costs_exceeded_edge(self) -> bool | None:
        """The §25 finding: profitable before costs, unprofitable after."""
        if not self.trades:
            return None
        return self.gross_pnl > 0 and self.net_pnl <= 0

    def summary(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "asset": self.asset,
            "interval": self.interval,
            "trades": len(self.trades),
            "wins": self.wins,
            "win_rate_pct": None if self.win_rate is None else str(self.win_rate),
            "gross_pnl": str(self.gross_pnl),
            "fees": str(self.fees),
            "net_pnl": str(self.net_pnl),
            "return_pct": str(self.return_pct),
            "max_drawdown_pct": str(self.max_drawdown_pct),
            "exposure_pct": str(self.exposure_pct),
            "position_hours": str(self.position_hours),
            "costs_exceeded_edge": self.costs_exceeded_edge,
        }


@dataclass
class _OpenPosition:
    side: Decision
    opened_at: datetime
    entry_price: Decimal
    quantity: Decimal
    fees_paid: Decimal


@dataclass
class CandleBacktest:
    """Replays chart readings past a rule and trades what it asks for.

    `notional` is fixed per position and does not compound. A compounding run
    on a rising market reports a number dominated by the market's direction
    rather than the rule's decisions, and the comparison against buy-and-hold
    is what this is for. Fixed size keeps every trade's contribution the same
    weight, which is also what makes the shuffled control a fair one.
    """

    rule: Rule
    costs: CostModel = field(default_factory=CostModel)
    notional: Decimal = Decimal(1000)
    starting_equity: Decimal = Decimal(10000)

    def run(
        self, candles: Sequence[Candle], config: FeatureConfig | None = None
    ) -> CandleBacktestResult:
        pairs = list(execution_pairs(candles, config))
        if not pairs:
            raise ValueError(
                "not enough candles to produce a single decision with somewhere to "
                "execute it; download more history"
            )

        trades: list[CandleTrade] = []
        curve: list[tuple[datetime, Decimal]] = []
        position: _OpenPosition | None = None
        realised = Decimal(0)
        in_position = 0
        position_hours = Decimal(0)
        asset = candles[0].asset
        interval = candles[0].interval
        hours_per_candle = Decimal(candles[0].interval_seconds) / Decimal(3600)

        for reading, fill in pairs:
            target = self.rule.decide(reading)

            if position is not None and target is not position.side:
                trades.append(self._close(position, fill))
                realised += trades[-1].net_pnl
                position = None

            if position is None and target is not Decision.FLAT:
                position = self._open(target, fill)

            # Marked to market at this candle's close, on the position that is
            # open *after* the fill — which is the position actually held over
            # the rest of the candle.
            unrealised = Decimal(0)
            if position is not None:
                moved = (fill.close - position.entry_price) * position.side.sign
                unrealised = moved * position.quantity - position.fees_paid
                in_position += 1
                position_hours += hours_per_candle
            curve.append((fill.close_time, self.starting_equity + realised + unrealised))

        if position is not None:
            # An open position at the end of the data is closed at the last
            # price available — the final candle's close, not its open, since
            # the position was held through that candle. Leaving it open would
            # report a rule's unrealised paper gain as though it had been
            # taken.
            last = pairs[-1][1]
            trades.append(self._close_at(position, price=last.close, moment=last.close_time))

        return CandleBacktestResult(
            rule=self.rule.name,
            asset=asset,
            interval=interval,
            trades=tuple(trades),
            equity_curve=tuple(curve),
            starting_equity=self.starting_equity,
            candles_seen=len(pairs),
            candles_in_position=in_position,
            position_hours=position_hours,
        )

    def _fee(self, notional: Decimal) -> Decimal:
        """One side's cost: the fee plus the half-spread crossed to get filled.

        Both, because a fill at the candle's open is a market order. The tick
        backtester charges the fee only, since it fills at the touch and the
        spread is already in that price; here the open is a mid-like reference
        and crossing has to be added.
        """
        return notional * self.costs.one_way_bps / BPS

    def _open(self, side: Decision, fill: Candle) -> _OpenPosition:
        quantity = self.notional / fill.open
        return _OpenPosition(
            side=side,
            opened_at=fill.open_time,
            entry_price=fill.open,
            quantity=quantity,
            fees_paid=self._fee(self.notional),
        )

    def _close(self, position: _OpenPosition, fill: Candle) -> CandleTrade:
        """Close on a rule's instruction, at the next open it can transact at."""
        return self._close_at(position, price=fill.open, moment=fill.open_time)

    def _close_at(
        self, position: _OpenPosition, *, price: Decimal, moment: datetime
    ) -> CandleTrade:
        return CandleTrade(
            side=position.side,
            opened_at=position.opened_at,
            closed_at=moment,
            entry_price=position.entry_price,
            exit_price=price,
            quantity=position.quantity,
            fees=position.fees_paid + self._fee(price * position.quantity),
        )
