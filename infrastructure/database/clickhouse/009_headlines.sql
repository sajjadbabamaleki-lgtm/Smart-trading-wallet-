-- News headlines, from the outlets' own RSS feeds.
--
-- Free and with no archive: a feed carries its last few dozen items, so a
-- headline signal has to be collected for weeks before it can be judged at all.
-- The alternative was a paid historical news archive; the honest trade is to
-- start collecting today.
--
-- Both times are kept, per ADR-007, and every point-in-time query selects on
-- ours. That rule matters more here than for market data: an outlet claims a
-- publication time, the item appears on the feed at some later moment, and we
-- fetch it later still. A backtest that trusted the outlet's claim would be
-- reading the news before it was news.
--
-- `item_id` is the link hashed, and it is the deduplication key. Feeds reuse
-- `guid` inconsistently and some omit it, while the link is present in every
-- item the reader accepts and does not change when an outlet edits a headline
-- -- so an edited story deduplicates against its original rather than
-- arriving as news a second time.
--
-- `published_at` is nullable on purpose. A feed that omits or mangles the time
-- has told us something about itself, and substituting the fetch time would
-- erase exactly the distinction these columns exist to keep.
--
-- `claimed_lag_seconds` is materialised rather than computed at read time: a
-- feed that routinely publishes items hours after their stated time is a feed
-- whose stated times cannot be trusted, and this is the column that shows it
-- without scanning the text.
--
-- No sentiment column, no score, no classification. Interpreting a headline is
-- a separate job, and a collection bug that looked like a judgement error
-- would be very hard to find.

CREATE TABLE IF NOT EXISTS headlines (
    item_id       String,
    source        LowCardinality(String),
    title         String,
    link          String,
    published_at  Nullable(DateTime64(3, 'UTC')),
    -- Ours, always present, and the only time a point-in-time query may use.
    fetched_at    DateTime64(3, 'UTC'),

    claimed_lag_seconds Nullable(Int64) MATERIALIZED
        if(published_at IS NULL, NULL, dateDiff('second', published_at, fetched_at))
)
ENGINE = ReplacingMergeTree(fetched_at)
PARTITION BY toYYYYMM(fetched_at)
ORDER BY (item_id)
SETTINGS index_granularity = 8192;

-- Reading by arrival is the dominant query — "what did we know between these
-- two moments" — and the sorting key is item_id because deduplication is what
-- the table is mostly doing. This index makes the range scan cheap without
-- reordering the table around the less important of the two.
ALTER TABLE headlines
    ADD INDEX IF NOT EXISTS headlines_by_arrival fetched_at TYPE minmax GRANULARITY 4;
