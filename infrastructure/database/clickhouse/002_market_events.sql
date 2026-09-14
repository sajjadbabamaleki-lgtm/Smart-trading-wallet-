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
-- ORDER BY (asset, event_type, exchange_time) matches the dominant research
-- query — one asset, one event type, a time range — and gives good compression
-- because neighbouring rows are similar. The partition is monthly: daily
-- partitions on a multi-billion-row table produce too many parts.

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
ORDER BY (asset, event_type, exchange_time, event_id)
SETTINGS index_granularity = 8192;
