-- The Crypto Fear & Greed Index.
--
-- The first input in this project that is not derived from the price series --
-- or rather, half of it is: the published components are volatility (25%),
-- momentum and volume (25%), social media (15%), dominance (10%) and search
-- trends (10%). The social and search half is the part worth testing, and
-- saying so here is cheaper than rediscovering momentum under another name.
--
-- Free, no key, and eight years deep, which makes it the only sentiment input
-- this project can test against history rather than collect forward.
--
-- Both keep the source's claimed time and our own receipt time, per ADR-007,
-- and every point-in-time query selects on ours. That rule matters more here
-- than for market data. A candle's timestamp is unambiguous; a news item has a
-- publication time the outlet claims, a moment it appeared on the feed, and a
-- moment we fetched it, and those can differ by hours. A backtest that trusted
-- the outlet's claim would be reading the news before it was news.
--
-- ClickHouse rather than PostgreSQL because both are append-only historical
-- records read in ranges (ADR-002), not transactional state.

CREATE TABLE IF NOT EXISTS sentiment_index (
    source          LowCardinality(String),
    -- The timestamp the source published. Not when a decision may use it: the
    -- index describes a window ending somewhere inside its own day and the API
    -- does not say where, so the reader applies a one-day lag. Stored as
    -- published so a later correction to that assumption does not require
    -- re-downloading eight years.
    published_at    DateTime64(3, 'UTC'),
    value           Decimal64(4),
    classification  LowCardinality(String),
    fetched_at      DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(fetched_at)
PARTITION BY toYYYYMM(published_at)
ORDER BY (source, published_at)
SETTINGS index_granularity = 8192;

