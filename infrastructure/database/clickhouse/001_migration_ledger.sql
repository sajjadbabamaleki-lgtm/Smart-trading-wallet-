-- Migration ledger (ClickHouse).
--
-- Same purpose as the PostgreSQL ledger: record what has been applied and
-- detect a migration file that changed after application.
--
-- ReplacingMergeTree rather than a plain table because ClickHouse has no
-- primary-key uniqueness constraint. Reads use FINAL so a re-application shows
-- one row per version rather than two.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version      String,
    name         String,
    checksum     String,
    applied_at   DateTime64(3, 'UTC') DEFAULT now64(3),
    duration_ms  UInt32
)
ENGINE = ReplacingMergeTree(applied_at)
ORDER BY version;
