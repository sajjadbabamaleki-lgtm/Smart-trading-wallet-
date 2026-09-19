-- Historical candles.
--
-- `market_events` holds what our own recorder saw, which begins the day the
-- recorder was switched on. A trader that reasons about a trend, a level, or
-- how an asset behaved through the last two cycles needs history that predates
-- us, and the only honest source for that is the venue's own candle archive.
-- So this is a second, separate table rather than more rows in the first.
--
-- Keeping them separate is a point-in-time decision, not tidiness. Every row
-- in `market_events` carries the moment *we* received it, and research there
-- selects on that. A candle downloaded today describes a week in 2025: it has
-- no receipt time that means anything, and writing one would make the PIT
-- guarantee on that table a lie. Here the only time that exists is the
-- venue's, and it is named as such.
--
-- ReplacingMergeTree, keyed on `fetched_at`. A backfill is re-run — after a
-- crash, to extend the range, to fill a hole — and the same candle arrives
-- again. Without replacement the table would slowly accumulate duplicates of
-- the same hour and every average computed over it would be wrong by an amount
-- nobody could see. Deduplication happens at merge time, so reads must say
-- FINAL; `candles.py` does.
--
-- Decimal64(8), not Float, for the same reason as `market_events`: a float
-- cannot hold a venue tick exactly and the drift is unrecoverable once stored.
--
-- Only closed candles are ever written. The candle covering the current hour is
-- still forming, and its high, low and close will change. A backtest that reads
-- one is reading a number that did not exist at the moment it claims to act on,
-- which is lookahead in its purest form. `interval_seconds` is stored so that
-- "is this candle closed" can be answered from the row itself rather than from
-- a lookup table somebody later disagrees with.

CREATE TABLE IF NOT EXISTS candles (
    venue             LowCardinality(String),
    asset             LowCardinality(String),
    interval          LowCardinality(String),
    interval_seconds  UInt32,

    -- The venue's own timing, and the only timing a candle has.
    open_time         DateTime64(3, 'UTC'),
    close_time        DateTime64(3, 'UTC'),

    open              Decimal64(8),
    high              Decimal64(8),
    low               Decimal64(8),
    close             Decimal64(8),
    volume            Decimal64(8),
    trades            UInt64,

    -- When we downloaded it. Not a receipt time in the PIT sense — a candle
    -- from last year was not available to us last year — but the version marker
    -- ReplacingMergeTree uses, and the audit trail for a re-fetch.
    fetched_at        DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(fetched_at)
PARTITION BY toYYYYMM(open_time)
ORDER BY (venue, asset, interval, open_time)
SETTINGS index_granularity = 8192;
