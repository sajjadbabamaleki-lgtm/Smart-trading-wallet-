-- Data gap registry.
--
-- Build 0.1 Rev.1 §30 and Phase 3 §20: missing data must never silently
-- disappear. A recorder that quietly loses twenty minutes of market data is
-- worse than one that reports a twenty-minute gap, because a backtest over the
-- silent version produces a confident wrong answer (Phase 3 §29).
--
-- Rows are written by the recorder on detection and updated as backfill is
-- attempted, so unlike audit_events this table is mutable by design.

CREATE TABLE IF NOT EXISTS data_gaps (
    gap_id           UUID        PRIMARY KEY,
    source           TEXT        NOT NULL,
    venue            TEXT        NOT NULL,
    asset            TEXT        NOT NULL,
    event_type       TEXT        NOT NULL,
    gap_start        TIMESTAMPTZ NOT NULL,
    -- NULL while a gap is still open: the stream has not resumed, so the end
    -- is genuinely unknown. Recording a guess would understate the gap.
    gap_end          TIMESTAMPTZ,
    detected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    detection_reason TEXT        NOT NULL,
    expected_sequence BIGINT,
    actual_sequence   BIGINT,
    backfill_status  TEXT        NOT NULL DEFAULT 'PENDING',
    backfill_attempts INTEGER    NOT NULL DEFAULT 0,
    resolution       TEXT,
    quality_impact   TEXT        NOT NULL DEFAULT 'UNKNOWN',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT data_gaps_backfill_status_known
        CHECK (backfill_status IN ('PENDING', 'IN_PROGRESS', 'RECOVERED', 'PARTIAL', 'UNRECOVERABLE')),
    CONSTRAINT data_gaps_quality_impact_known
        CHECK (quality_impact IN ('UNKNOWN', 'NONE', 'MINOR', 'MATERIAL', 'INVALIDATING')),
    CONSTRAINT data_gaps_ordered
        CHECK (gap_end IS NULL OR gap_end >= gap_start),
    -- A gap cannot be recovered while its extent is unknown.
    CONSTRAINT data_gaps_recovered_gaps_are_closed
        CHECK (backfill_status <> 'RECOVERED' OR gap_end IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS data_gaps_open_idx
    ON data_gaps (asset, event_type, gap_start)
    WHERE backfill_status IN ('PENDING', 'IN_PROGRESS');

CREATE INDEX IF NOT EXISTS data_gaps_window_idx
    ON data_gaps (asset, gap_start, gap_end);

COMMENT ON TABLE data_gaps IS
    'Detected gaps in recorded data. A research dataset overlapping an '
    'unrecovered gap must declare it rather than interpolate across it.';
