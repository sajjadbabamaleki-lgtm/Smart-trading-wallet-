-- Dataset manifests.
--
-- Build 0.1 Rev.1 §38-39 and Rev.2 §23: research without dataset identity is
-- prohibited. "This strategy made 43%" is unacceptable without the exact
-- experiment identity (Phase 4 §43), and that starts with being able to say
-- precisely which data was used.
--
-- The checksum is what makes a result reproducible: given a dataset_id, the
-- research system must be able to establish that the bytes have not changed.

CREATE TABLE IF NOT EXISTS dataset_manifests (
    dataset_id       TEXT        PRIMARY KEY,
    source           TEXT        NOT NULL,
    venue            TEXT,
    assets           TEXT[]      NOT NULL,
    data_types       TEXT[]      NOT NULL,
    range_start      TIMESTAMPTZ NOT NULL,
    range_end        TIMESTAMPTZ NOT NULL,
    row_count        BIGINT,
    acquired_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_version   TEXT,
    schema_version   INTEGER     NOT NULL,
    feature_version  TEXT,
    quality_status   TEXT        NOT NULL,
    quality_summary  JSONB       NOT NULL DEFAULT '{}'::jsonb,
    pit_status       TEXT        NOT NULL,
    checksum         TEXT        NOT NULL,
    storage_uri      TEXT        NOT NULL,
    -- Gaps overlapping the range, recorded so a consumer cannot be unaware of
    -- them. An empty array means none were found, not that none were looked for
    -- — the quality_status carries that distinction.
    known_gap_ids    UUID[]      NOT NULL DEFAULT '{}',

    CONSTRAINT dataset_manifests_quality_known
        CHECK (quality_status IN ('VALID', 'WARNING', 'INVALID', 'UNKNOWN')),
    CONSTRAINT dataset_manifests_pit_known
        CHECK (pit_status IN ('PIT_SAFE', 'PIT_APPROXIMATE', 'NON_PIT')),
    CONSTRAINT dataset_manifests_range_ordered
        CHECK (range_end >= range_start),
    CONSTRAINT dataset_manifests_assets_not_empty
        CHECK (cardinality(assets) > 0)
);

CREATE INDEX IF NOT EXISTS dataset_manifests_range_idx
    ON dataset_manifests (range_start, range_end);

COMMENT ON TABLE dataset_manifests IS
    'Immutable identity of every research dataset: what it contains, where it '
    'came from, its quality and point-in-time classification, and its checksum.';
COMMENT ON COLUMN dataset_manifests.pit_status IS
    'Whether the dataset may be used in strict predictive validation. Only '
    'PIT_SAFE may; NON_PIT is exploratory research only (Phase 3 §7).';
