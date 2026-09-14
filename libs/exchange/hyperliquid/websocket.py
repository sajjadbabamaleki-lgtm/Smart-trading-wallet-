"""Live Hyperliquid WebSocket source.

The one component of the recorder that cannot be tested without the venue. Its
job is deliberately narrow — connect, subscribe, yield frames with receipt
timestamps, reconnect — so that everything interesting about the recorder lives
in code that runs against fixtures instead.

Reconnect follows Build 0.1 Rev.1 §29:

    disconnect detected -> record timestamp -> reconnect -> resubscribe
    -> receive snapshot -> identify missing interval -> backfill where possible
    -> register unresolved gap -> healthy

This class handles the first four and reports the disconnect interval; the
recorder owns gap registration, because that decision belongs with the
component that knows what the streams were expected to deliver.

**Not yet exercised against the live venue.** The message shapes come from the
venue's SDK type definitions, and running this against testnet is a required
step in closing M2.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime

from libs.domain.clock import Clock
from libs.domain.timestamps import EventTimestamps
from libs.exchange.hyperliquid.subscriptions import (
    RECORDED_CHANNELS,
    subscription_request,
)
from libs.observability.logging import get_logger
from services.market_data.source import IncomingFrame

logger = get_logger(__name__)


@dataclass
class ReconnectPolicy:
    """Backoff between reconnect attempts.

    Exponential with a cap and jitter. The cap keeps a long outage from
    stretching the interval to uselessness; the jitter keeps several recorders
    from retrying in lockstep against a venue that has just come back.
    """

    initial_seconds: float = 1.0
    maximum_seconds: float = 30.0
    multiplier: float = 2.0
    jitter_fraction: float = 0.2

    def delay_for(self, attempt: int) -> float:
        """Delay before attempt `attempt` (1-based)."""
        if attempt < 1:
            raise ValueError("attempt is 1-based")
        raw = self.initial_seconds * (self.multiplier ** (attempt - 1))
        capped = min(raw, self.maximum_seconds)
        # Deterministic jitter derived from the attempt number rather than a
        # random source, so a failure-injection test can assert on the delay.
        offset = ((attempt * 2654435761) % 1000) / 1000 - 0.5
        return max(0.0, capped * (1 + offset * self.jitter_fraction))


@dataclass
class HyperliquidWebSocketSource:
    """Streams frames from a Hyperliquid WebSocket endpoint."""

    url: str
    assets: tuple[str, ...]
    clock: Clock
    channels: tuple[str, ...] = RECORDED_CHANNELS
    policy: ReconnectPolicy = field(default_factory=ReconnectPolicy)
    ping_interval_seconds: float = 20.0
    max_attempts: int | None = None
    """Reconnect attempts before giving up. None means keep trying — which is
    correct for a long-running recorder, and is overridden in tests."""

    disconnected_at: datetime | None = field(default=None, init=False)
    attempts: int = field(default=0, init=False)
    successful_connections: int = field(default=0, init=False)
    """How many times the socket opened and subscribed successfully.

    Zero means we never reached the venue. Without this, a caller cannot tell
    "connected but the venue sent nothing" from "never connected at all" —
    the retry loop swallows the failure by design, and an acceptance report
    that conflated the two would claim a connection it never had.
    """

    last_error: str | None = field(default=None, init=False)
    """The most recent connection failure, for the evidence record."""

    subscriptions_sent: int = field(default=0, init=False)

    @property
    def name(self) -> str:
        return "hyperliquid_ws"

    async def frames(self) -> AsyncIterator[IncomingFrame]:
        """Yield frames, reconnecting as needed.

        The timestamps are taken immediately on receipt, before any parsing, so
        the measured latency is of the venue and the network rather than of our
        own decoding (ADR-007).
        """
        # Lazy import: see the note in libs/storage/clickhouse.py.
        import websockets  # noqa: PLC0415

        attempt = 0
        while True:
            attempt += 1
            self.attempts = attempt
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=self.ping_interval_seconds,
                    ping_timeout=self.ping_interval_seconds,
                    max_size=None,  # book snapshots can be large
                ) as socket:
                    await self._subscribe(socket)
                    self.successful_connections += 1
                    if self.disconnected_at is not None:
                        logger.info(
                            "reconnected",
                            extra={
                                "attempt": attempt,
                                "outage_seconds": (
                                    self.clock.now() - self.disconnected_at
                                ).total_seconds(),
                            },
                        )
                        self.disconnected_at = None
                    attempt = 0

                    async for payload in socket:
                        received_at = self.clock.now()
                        monotonic = self.clock.monotonic_ns()
                        text = (
                            payload
                            if isinstance(payload, str)
                            else payload.decode("utf-8", errors="replace")
                        )
                        yield IncomingFrame(
                            payload=text,
                            receipt=EventTimestamps(
                                local_receive_time=received_at,
                                local_receive_monotonic_ns=monotonic,
                            ),
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.disconnected_at = self.disconnected_at or self.clock.now()
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "websocket_disconnected",
                    extra={
                        "attempt": attempt,
                        "error": f"{type(exc).__name__}: {exc}",
                        "url": self.url,
                    },
                )
                if self.max_attempts is not None and attempt >= self.max_attempts:
                    logger.exception(
                        "reconnect_attempts_exhausted",
                        extra={"attempts": attempt, "url": self.url},
                    )
                    return
                await asyncio.sleep(self.policy.delay_for(attempt))

    async def _subscribe(self, socket: object) -> None:
        """Send one subscribe request per (channel, asset).

        Sent individually rather than batched because the venue acknowledges
        each subscription separately, and a partial failure must be
        attributable to the specific stream that failed.
        """
        for asset in self.assets:
            for channel in self.channels:
                request = subscription_request(channel, asset)
                await socket.send(json.dumps(request))  # type: ignore[attr-defined]
                self.subscriptions_sent += 1
                logger.info("subscribed", extra={"channel": channel, "asset": asset})
