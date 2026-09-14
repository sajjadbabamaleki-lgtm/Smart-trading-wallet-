-- Raw message log.
--
-- Build 0.1 Rev.2 §20 and Phase 3 §17: the original source message is
-- preserved before normalization, and a normalization defect must never
-- destroy the original evidence. This table is what a normalized row's
-- raw_reference points at, and what a corrected normalizer re-derives from.
--
-- Effectively immutable: append only, never updated. Object storage holds the
-- durable archive (Phase 2 §8.1); this table is the queryable index into it,
-- so a specific message can be found without scanning archive files.
--
-- ZSTD on the payload because raw exchange JSON is highly repetitive — the
-- column dominates the table's size otherwise.

CREATE TABLE IF NOT EXISTS raw_messages (
    raw_id            String,
    source            LowCardinality(String),
    venue             LowCardinality(String),
    channel           LowCardinality(String),
    local_receive_time            DateTime64(9, 'UTC'),
    local_receive_monotonic_ns    UInt64,
    payload           String CODEC(ZSTD(3)),
    payload_bytes     UInt32,
    -- Content hash, so an identical message redelivered after a reconnect can
    -- be recognised rather than counted twice (Build 0.1 Rev.1 §31).
    payload_sha256    FixedString(64),
    -- Where the durable copy lives in object storage.
    archive_uri       String
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(local_receive_time)
ORDER BY (source, channel, local_receive_time, raw_id)
SETTINGS index_granularity = 8192;
