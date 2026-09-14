-- Trader events.
--
-- Exists so the M2 recorder has somewhere to put identity-linked fields it
-- receives. Per ADR-006 this is preserving optionality, not endorsing the
-- trader-behaviour hypothesis: bounded API history and a monthly archive with
-- no completeness guarantee mean information discarded now may be
-- unreconstructable later, while a nullable column costs almost nothing.
--
-- ORDER BY leads with wallet, because every TBIE query is per-wallet over time
-- — skill estimation, markout, turnover. That differs from market_events on
-- purpose: the access pattern differs.

CREATE TABLE IF NOT EXISTS trader_events (
    event_id          String,
    schema_version    UInt16,
    source            LowCardinality(String),
    venue             LowCardinality(String),
    asset             LowCardinality(String),
    instrument        LowCardinality(String),
    event_type        LowCardinality(String),

    exchange_time     Nullable(DateTime64(9, 'UTC')),
    consensus_time    Nullable(DateTime64(9, 'UTC')),
    local_receive_time            DateTime64(9, 'UTC'),
    local_receive_monotonic_ns    UInt64,
    persist_time      DateTime64(9, 'UTC') DEFAULT now64(9),

    -- A pseudonymous behavioural identifier, never a verified human trader.
    -- One person may run many wallets and a wallet may change hands, so wallet
    -- counts are not people counts (TBIE v1.1 §54).
    wallet            String,
    counterparty      String,
    side              LowCardinality(Nullable(String)),
    price             Nullable(Decimal64(8)),
    quantity          Nullable(Decimal64(8)),
    notional          Nullable(Decimal64(8)),

    order_id          String,
    client_order_id   String,
    -- Set for a visible TWAP slice. Kept because TWAP and liquidation flow are
    -- excluded from skill scoring — a TWAP slice reflects a schedule, not a
    -- view on the next few seconds (TBIE v1.1 §7).
    twap_id           String,
    start_position    Nullable(Decimal64(8)),
    end_position      Nullable(Decimal64(8)),

    raw_reference     String,
    quality_status    LowCardinality(String),
    pit_status        LowCardinality(String),

    -- Materialized so scoring queries filter on it directly rather than
    -- repeating the rule and risking two definitions of "excluded".
    excluded_from_skill_scoring UInt8 MATERIALIZED
        if(twap_id != '' OR event_type = 'LIQUIDATION', 1, 0)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(local_receive_time)
ORDER BY (wallet, asset, exchange_time, event_id)
SETTINGS index_granularity = 8192;
