-- Migration ledger.
--
-- Records which migrations have been applied, with the checksum of the file as
-- applied. A migration whose file changes after being applied is a silent
-- schema divergence between environments, so the runner refuses to proceed
-- when a recorded checksum no longer matches (see libs/storage/migrations.py).
--
-- This table is itself migration 001, so it must be creatable by a runner that
-- cannot yet read it. Hence IF NOT EXISTS and no dependency on prior state.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version      TEXT        PRIMARY KEY,
    name         TEXT        NOT NULL,
    checksum     TEXT        NOT NULL,
    applied_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_ms  INTEGER     NOT NULL
);

COMMENT ON TABLE schema_migrations IS
    'Applied migrations with the checksum of each file as applied.';
