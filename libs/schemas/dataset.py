"""Dataset identity.

Build 0.1 Rev.2 §23: research without dataset identity is prohibited. Phase 4
§43 says why — "this strategy made 43%" is unacceptable without the exact
experiment identity, and that begins with being able to say precisely which
data was used.

This model is the in-memory form of the `dataset_manifests` row. It is frozen,
because a manifest describes a dataset that has already been written: changing
one would mean the record and the data disagree, and the record is the only
thing a later reader has.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from libs.schemas.enums import DataQualityStatus, PitStatus

SCHEMA_VERSION = 1


class DatasetManifest(BaseModel):
    """What a dataset contains, where it came from, and whether it can be trusted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str
    source: str = Field(description="What produced the rows, e.g. 'clickhouse:market_events'.")
    venue: str | None = None
    assets: tuple[str, ...]
    data_types: tuple[str, ...]

    range_start: datetime
    range_end: datetime
    """The range is expressed in *receipt* time, not venue time.

    Point-in-time correctness is defined by when information reached us: at
    decision time T only what we had received by T may be used. A range in
    venue time would admit a row we did not yet have, which is the leak the
    whole classification exists to prevent (Phase 3 §7, Phase 4 §9).
    """

    row_count: int = Field(ge=0)
    created_at: datetime
    source_version: str | None = None
    schema_version: int = SCHEMA_VERSION
    feature_version: str | None = None

    quality_status: DataQualityStatus
    quality_summary: dict[str, object] = Field(default_factory=dict)
    pit_status: PitStatus
    checksum: str
    storage_uri: str
    known_gap_ids: tuple[str, ...] = ()
    """Gaps overlapping this range.

    Empty means none were found, not that none were looked for — `quality_status`
    carries that distinction. A consumer that cannot see the gaps in its own
    data will backtest over the silent version and get a confident wrong answer
    (Phase 3 §29).
    """

    @model_validator(mode="after")
    def _check_range_is_ordered(self) -> Self:
        if self.range_end < self.range_start:
            raise ValueError("range_end precedes range_start")
        return self

    @model_validator(mode="after")
    def _check_assets_present(self) -> Self:
        if not self.assets:
            raise ValueError("a dataset must name at least one asset")
        if not self.data_types:
            raise ValueError("a dataset must name at least one data type")
        return self

    @model_validator(mode="after")
    def _check_empty_datasets_are_not_valid(self) -> Self:
        """A dataset with no rows cannot be VALID.

        Nothing was verified, because there was nothing to verify. Calling that
        VALID would let an empty range become a clean research input, and an
        experiment over no data is the one result that must never look like a
        passing one.
        """
        if self.row_count == 0 and self.quality_status is DataQualityStatus.VALID:
            raise ValueError("an empty dataset cannot be VALID; it verified nothing")
        return self

    @property
    def usable_for_training(self) -> bool:
        """Whether this dataset may enter a training or validation run.

        Both conditions, not either: quality decides whether the rows are sound,
        point-in-time status decides whether using them would leak the future.
        """
        return (
            self.quality_status.usable_for_training and self.pit_status.usable_for_strict_validation
        )
