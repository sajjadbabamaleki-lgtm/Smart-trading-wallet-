-- Market events.
--
-- The analytical event store (ADR-002). Column choices that matter:
--
-- Decimal, not Float. A float cannot represent a venue tick exactly, and
-- rounding drift in stored market data is unrecoverable once written. Decimal64
-- with 8 decimal places covers BTC prices and the quantities traded on
-- Hyperliquid with room to spare.
--
-- DateTime64(9) — nanoseconds. Build 0.1 Rev.1 §18: high-frequency events must
-- keep sub-second precision, and reducing everything to seconds would destroy
-- the timing information that a fast-decaying signal is measured with
-- (TBIE v1.1 §17).
--
-- Both venue time and our receipt time are stored, per ADR-007. Nullable venue
-- fields, because a source that does not supply one must leave it empty rather
-- than have a value invented.
--
-- ORDER BY (asset, event_type, local_receive_time) matches the dominant
-- research query — one asset, one event type, a time range — and gives good
-- compression because neighbouring rows are similar. The partition is monthly:
-- daily partitions on a multi-billion-row table produce too many parts.
--
-- The time column in the sorting key is *our receipt time*, not the venue's,
-- and that is a correctness decision rather than a concession to ClickHouse
-- refusing a nullable sorting key (which it does, and which is how this was
-- found).
--
-- Point-in-time correctness is defined by when information was available to
-- us: at decision time T only what we had received by T may be used. That
-- makes a PIT-safe scan a local_receive_time range, so ordering by anything
-- else would leave the one query the research layer must run as the
-- unindexed one. The partition key already uses local_receive_time; the
-- sorting key now agrees with it instead of cutting across it.
--
-- It also resolves a contradiction. exchange_time is nullable on purpose —
-- absent means the venue supplied nothing, and inventing a value is
-- prohibited. Putting it in the sorting key asks the engine to give those
-- unknowns a position in the ordering, which is inventing one.
--
-- Venue-time analysis is not lost: exchange_time remains a column and stays
-- queryable. It is a full scan within the matched partitions rather than an
-- indexed lookup, which is the right cost to pay on the query that is not the
-- point-in-time one.

CREATE TABLE IF NOT EXISTS market_events (
    event_id          String,
    schema_version    UInt16,
    source            LowCardinality(String),
    venue             LowCardinality(String),
    asset             LowCardinality(String),
    instrument        LowCardinality(String),
    event_type        LowCardinality(String),

    -- Venue-supplied timing. Nullable: absent means unavailable, not zero.
    exchange_time     Nullable(DateTime64(9, 'UTC')),
    consensus_time    Nullable(DateTime64(9, 'UTC')),
    -- Our own timing, always present (ADR-007).
    local_receive_time            DateTime64(9, 'UTC'),
    local_receive_monotonic_ns    UInt64,
    persist_time      DateTime64(9, 'UTC') DEFAULT now64(9),

    sequence          Nullable(UInt64),
    price             Nullable(Decimal64(8)),
    quantity          Nullable(Decimal64(8)),
    side              LowCardinality(Nullable(String)),
    bid_price         Nullable(Decimal64(8)),
    bid_quantity      Nullable(Decimal64(8)),
    ask_price         Nullable(Decimal64(8)),
    ask_quantity      Nullable(Decimal64(8)),
    funding_rate      Nullable(Decimal64(10)),
    open_interest     Nullable(Decimal64(8)),

    raw_reference     String,
    quality_status    LowCardinality(String),
    pit_status        LowCardinality(String),

    -- Derived on write so that latency analysis does not require recomputing it
    -- over billions of rows. Signed: negative means our clock ran behind the
    -- venue's, which is a condition to monitor rather than to clamp
    -- (ADR-007, Phase 6 §62).
    source_to_receive_ms Nullable(Int64) MATERIALIZED
        if(exchange_time IS NULL AND consensus_time IS NULL,
           NULL,
           dateDiff('millisecond', coalesce(consensus_time, exchange_time), local_receive_time))
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(local_receive_time)
ORDER BY (asset, event_type, local_receive_time, event_id)
SETTINGS index_granularity = 8192;
