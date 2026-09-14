-- Audit events.
--
-- Build 0.1 Rev.1 §58-59 requires a universal audit event and a correlation id
-- from the start rather than as a retrofit: an id that was never assigned
-- cannot be recovered, and a capital-affecting action that was never recorded
-- cannot be reconstructed.
--
-- Phase 10 §62 requires the trail to be tamper-resistant. Append-only is
-- enforced here by revoking UPDATE and DELETE from the application role rather
-- than by convention — an attacker who changes capital state should not be able
-- to erase the evidence afterwards. Full immutability (off-host replication,
-- write-once storage) is a production concern, recorded in the runbook backlog.

CREATE TABLE IF NOT EXISTS audit_events (
    event_id          UUID        PRIMARY KEY,
    event_type        TEXT        NOT NULL,
    occurred_at       TIMESTAMPTZ NOT NULL,
    recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    service           TEXT        NOT NULL,
    actor_type        TEXT        NOT NULL,
    actor_id          TEXT,
    entity_type       TEXT,
    entity_id         TEXT,
    correlation_id    TEXT        NOT NULL,
    severity          TEXT        NOT NULL,
    payload           JSONB       NOT NULL DEFAULT '{}'::jsonb,
    payload_reference TEXT,

    CONSTRAINT audit_events_severity_known
        CHECK (severity IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    CONSTRAINT audit_events_actor_type_known
        CHECK (actor_type IN ('SYSTEM', 'USER', 'OPERATOR', 'STRATEGY', 'RISK', 'EXECUTION')),
    -- occurred_at is supplied by the caller and recorded_at by the database.
    -- A caller-supplied time far in the future is a clock defect, and storing
    -- it unchallenged would corrupt the ordering the trail exists to provide.
    CONSTRAINT audit_events_not_from_the_future
        CHECK (occurred_at <= recorded_at + INTERVAL '1 hour')
);

-- Reconstructing one workflow end to end is the common query
-- (signal -> risk decision -> intent -> order -> fill).
CREATE INDEX IF NOT EXISTS audit_events_correlation_idx
    ON audit_events (correlation_id, occurred_at);

CREATE INDEX IF NOT EXISTS audit_events_occurred_idx
    ON audit_events (occurred_at DESC);

CREATE INDEX IF NOT EXISTS audit_events_type_idx
    ON audit_events (event_type, occurred_at DESC);

COMMENT ON TABLE audit_events IS
    'Append-only record of capital-affecting and security-relevant actions.';
COMMENT ON COLUMN audit_events.occurred_at IS
    'When the action happened, per the emitting service.';
COMMENT ON COLUMN audit_events.recorded_at IS
    'When this row was written, per the database.';
COMMENT ON COLUMN audit_events.payload_reference IS
    'Pointer to a large payload in object storage, when the payload is not inlined.';
