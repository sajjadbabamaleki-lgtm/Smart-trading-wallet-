"""The capital-control boundary.

Build 0.1 Rev.2 §17 moves this ahead of any strategy work, and lists the
controls it must carry: a BTC-only allowlist, testnet-only execution, a maximum
order size, intent expiration, trading enable/disable, a data freshness
requirement, duplicate-order protection, and the kill switch. They are here,
each as one predicate, because a control that is spread across three call sites
is a control nobody can audit.

Two rules shape how they are applied:

* Invariant 1 — the engine may approve, reduce, or reject, and the proposer
  cannot overturn the answer. Size is therefore reduced rather than refused
  when the only fault is that it is too large.
* Invariant 7 — when critical state is unknown, the answer is no new risk. A
  missing price is a rejection, not a reason to proceed with an old one.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from libs.config import Settings
from libs.domain.clock import Clock, SystemClock
from libs.schemas.enums import Side
from services.risk_engine.intents import ExecutionIntent, IntentLedger
from services.risk_engine.models import (
    RejectionCode,
    RiskDecision,
    RiskOutcome,
    TradeProposal,
)

# Below this the venue would reject the order anyway, and a reduction that
# lands here is a reduction to nothing.
MINIMUM_NOTIONAL_USD = Decimal(1)


class MarketSnapshot:
    """The price the decision is made against, and when it was observed.

    A snapshot is not a quote from the recorder's table: it is what the caller
    believes the market is right now, timestamped, so freshness can be judged
    against the same limit the rest of the system uses.
    """

    __slots__ = ("bid", "observed_at")

    def __init__(self, *, bid: Decimal, observed_at: datetime) -> None:
        if bid <= 0:
            raise ValueError("bid must be positive")
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        self.bid = bid
        self.observed_at = observed_at

    def age_seconds(self, now: datetime) -> float:
        return (now - self.observed_at).total_seconds()


class RiskEngine:
    """Evaluates proposals and issues the intents that permit execution."""

    __slots__ = ("_clock", "_ledger", "_recent", "_settings")

    def __init__(
        self,
        settings: Settings,
        *,
        ledger: IntentLedger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._settings = settings
        self._ledger = ledger if ledger is not None else IntentLedger()
        self._clock = clock if clock is not None else SystemClock()
        # fingerprint -> when it was last approved, for duplicate protection
        self._recent: dict[str, datetime] = {}

    @property
    def ledger(self) -> IntentLedger:
        return self._ledger

    def evaluate(self, proposal: TradeProposal, *, market: MarketSnapshot | None) -> RiskDecision:
        now = self._clock.now()
        reasons: list[RejectionCode] = []

        reasons.extend(self._gate_reasons(proposal, market, now))
        if reasons:
            return self._reject(proposal, reasons, now)

        approved, size_reasons = self._sized(proposal)
        if approved is None:
            return self._reject(proposal, size_reasons, now)

        ttl = timedelta(seconds=self._settings.intent_ttl_seconds)
        intent = self._ledger.record(
            ExecutionIntent(
                correlation_id=proposal.correlation_id,
                environment=self._settings.execution_environment,
                asset=proposal.asset,
                side=proposal.side,
                notional_usd=approved,
                stop_price=proposal.stop_price,
                take_profit_price=proposal.take_profit_price,
                issued_at=now,
                expires_at=now + ttl,
            )
        )
        self._recent[proposal.fingerprint] = now
        return RiskDecision(
            outcome=(
                RiskOutcome.APPROVED if approved == proposal.notional_usd else RiskOutcome.REDUCED
            ),
            correlation_id=proposal.correlation_id,
            requested_notional_usd=proposal.notional_usd,
            approved_notional_usd=approved,
            reasons=tuple(size_reasons),
            decided_at=now,
            intent_id=intent.intent_id,
        )

    # ------------------------------------------------------------------ gates

    def _gate_reasons(
        self, proposal: TradeProposal, market: MarketSnapshot | None, now: datetime
    ) -> list[RejectionCode]:
        """Every reason this proposal cannot proceed at all.

        All of them are collected rather than returned at the first failure: an
        audit trail that says only "asset not allowed" hides that the kill
        switch was also engaged, and the second fact matters when someone asks
        later what the system would have done.
        """
        reasons: list[RejectionCode] = []

        if proposal.asset not in self._settings.asset_allowlist:
            reasons.append(RejectionCode.ASSET_NOT_ALLOWED)
        if self._settings.venue_endpoint is None:
            reasons.append(RejectionCode.ENVIRONMENT_FORBIDS_EXECUTION)
        if not self._settings.trading_enabled:
            reasons.append(RejectionCode.KILL_SWITCH_ENGAGED)
        if not self._settings.testnet_api_wallet_private_key:
            reasons.append(RejectionCode.NO_SIGNING_CREDENTIAL)

        if market is None:
            reasons.append(RejectionCode.MARKET_DATA_MISSING)
        elif market.age_seconds(now) > self._settings.data_staleness_limit_seconds:
            reasons.append(RejectionCode.MARKET_DATA_STALE)
        else:
            reasons.extend(self._exit_reasons(proposal, market))

        if self._is_duplicate(proposal, now):
            reasons.append(RejectionCode.DUPLICATE_PROPOSAL)
        return reasons

    def _exit_reasons(self, proposal: TradeProposal, market: MarketSnapshot) -> list[RejectionCode]:
        """A stop on the wrong side of the market is not a stop.

        Invariant 6 asks for defined downside. A long whose stop sits above the
        price has no downside defined at all — it would trigger immediately, or
        be silently ignored, depending on the venue.
        """
        reasons: list[RejectionCode] = []
        long = proposal.side is Side.BUY
        if (long and proposal.stop_price >= market.bid) or (
            not long and proposal.stop_price <= market.bid
        ):
            reasons.append(RejectionCode.STOP_ON_WRONG_SIDE)
        target = proposal.take_profit_price
        if target is not None and (
            (long and target <= market.bid) or (not long and target >= market.bid)
        ):
            reasons.append(RejectionCode.TAKE_PROFIT_ON_WRONG_SIDE)
        return reasons

    def _is_duplicate(self, proposal: TradeProposal, now: datetime) -> bool:
        """The same trade, again, while the first intent could still be live.

        The window is the intent TTL: until the earlier intent expires it may
        still be executed, so a second identical order would double the
        position rather than replace it (Rev.2 §17).
        """
        last = self._recent.get(proposal.fingerprint)
        if last is None:
            return False
        return (now - last).total_seconds() <= self._settings.intent_ttl_seconds

    def _sized(self, proposal: TradeProposal) -> tuple[Decimal | None, list[RejectionCode]]:
        """Cut the size to the ceiling, or refuse if nothing is left to cut to."""
        limit = self._settings.max_order_notional
        if proposal.notional_usd < MINIMUM_NOTIONAL_USD:
            return None, [RejectionCode.SIZE_BELOW_MINIMUM]
        if proposal.notional_usd <= limit:
            return proposal.notional_usd, []
        if limit < MINIMUM_NOTIONAL_USD:
            return None, [RejectionCode.SIZE_BELOW_MINIMUM]
        return limit, [RejectionCode.SIZE_ABOVE_LIMIT]

    def _reject(
        self, proposal: TradeProposal, reasons: list[RejectionCode], now: datetime
    ) -> RiskDecision:
        return RiskDecision(
            outcome=RiskOutcome.REJECTED,
            correlation_id=proposal.correlation_id,
            requested_notional_usd=proposal.notional_usd,
            approved_notional_usd=Decimal(0),
            reasons=tuple(reasons),
            decided_at=now,
        )
