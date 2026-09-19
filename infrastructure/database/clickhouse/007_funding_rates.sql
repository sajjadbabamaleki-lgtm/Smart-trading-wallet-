-- Funding rates.
--
-- The first input in this project that is not a transformation of price. Every
-- indicator in `indicators.py` is computed from the same public candle series,
-- so anyone who wants one has it and it is already in the price. A funding
-- rate is what the long and short sides are paying each other to hold their
-- positions: it describes positioning rather than pattern, and it exists only
-- because somebody committed capital.
--
-- A third table rather than columns on `candles`, for the reason `candles` is
-- separate from `market_events`: the grain differs. Funding settles on the
-- venue's own schedule — eight-hourly historically, four- or one-hourly for
-- some symbols since 2023 — which does not divide a candle interval, and
-- joining it onto candle rows would either duplicate payments or drop them.
-- Kept at its own grain and queried point-in-time, which is what
-- `FundingHistory.percentile_at` does.
--
-- Decimal64(10), not Decimal64(8) as prices use. A funding rate is a small
-- fraction — 0.0001 is a typical settlement — and it is multiplied by a large
-- notional, so precision lost here reappears as money.
--
-- `mark_price` is nullable because the venue does not always supply it and an
-- invented price is worse than a missing one.
--
-- ReplacingMergeTree on `fetched_at`: a backfill gets re-run and the same
-- settlement arrives again. Reads say FINAL.
--
-- Deliberately absent: open interest. Binance retains about thirty days of it,
-- so it cannot be tested over the six years this table covers, and a column
-- that looks like the others while silently holding a month is the kind of
-- quiet defect this schema's comments exist to prevent. It has to be collected
-- forward, in its own table, when that is worth doing.

CREATE TABLE IF NOT EXISTS funding_rates (
    venue         LowCardinality(String),
    asset         LowCardinality(String),

    -- The venue's settlement time, and the only time a funding payment has.
    funding_time  DateTime64(3, 'UTC'),

    rate          Decimal64(10),
    mark_price    Nullable(Decimal64(8)),

    fetched_at    DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(fetched_at)
PARTITION BY toYYYYMM(funding_time)
ORDER BY (venue, asset, funding_time)
SETTINGS index_granularity = 8192;
