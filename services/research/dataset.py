"""Building the first BTC research dataset (M4).

Build 0.1 Rev.2 §23 gates this on recorder integrity, which M1 and M2 passed
against a real stack and the live venue on 2026-09-14. What it adds is
identity: a set of rows nobody can name is not a dataset, and a result computed
from one cannot be reproduced or refuted.

Four decisions shape the implementation.

**The range is receipt time.** Point-in-time correctness is defined by when
information reached us — at decision time T, only what we had received by T may
be used. Selecting on venue time would admit rows we did not yet have. This is
the same reasoning that put `local_receive_time` in the ClickHouse sorting key,
so the selection is also the indexed one.

**The checksum covers the rows, not the file.** A Parquet writer embeds its own
version string, so byte-level hashing would give the same data a different
identity after a dependency upgrade and silently invalidate every recorded
experiment. The checksum is taken over a canonical rendering of the rows
themselves, which is what a reader actually needs to know has not changed.

**Exclusions are counted, never silent.** Rows dropped by the quality filter
are reported in the manifest's summary. A dataset that quietly discarded a
tenth of its range looks identical to one that had nothing to discard.

**Gaps travel with the data.** Any gap overlapping the range is recorded on the
manifest, and an open one — a stream that never resumed — means the range is
not known-complete and the dataset cannot be VALID. A backtest over the silent
version produces a confident wrong answer (Phase 3 §29).

The builder reaches no store directly. Rows and gaps arrive through injected
callables, as in `libs.storage.migrations`, so the whole thing is exercised
without ClickHouse or PostgreSQL and a test can construct the awkward cases.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

from libs.schemas.dataset import SCHEMA_VERSION, DatasetManifest
from libs.schemas.enums import DataQualityStatus, PitStatus

SOURCE: Final = "clickhouse:market_events"

CANONICAL_COLUMNS: Final[tuple[str, ...]] = (
    "event_id",
    "asset",
    "instrument",
    "event_type",
    "exchange_time",
    "local_receive_time",
    "venue_event_id",
    "price",
    "quantity",
    "side",
    "bid_price",
    "bid_quantity",
    "ask_price",
    "ask_quantity",
    "funding_rate",
    "open_interest",
    "quality_status",
    "pit_status",
)
"""The columns a dataset carries, in a fixed order.

Fixed because the checksum is computed over them: adding a column or reordering
these changes every dataset identity, which is correct and must be a deliberate
act rather than a side effect of editing a query.
"""


class DatasetError(RuntimeError):
    """A dataset cannot be built as specified. Nothing is written."""


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """What to build.

    `quality_filter` names the statuses admitted. It defaults to VALID alone
    because Rev.2 §21 forbids unknown quality becoming valid research data; a
    caller that wants the excluded rows must ask for them by name, and the
    manifest then records that it did.
    """

    asset: str
    range_start: datetime
    range_end: datetime
    data_types: tuple[str, ...] = ("TRADE", "BBO", "L2_SNAPSHOT")
    venue: str = "hyperliquid"
    quality_filter: tuple[DataQualityStatus, ...] = (DataQualityStatus.VALID,)

    def __post_init__(self) -> None:
        # Awareness first. Comparing a naive bound to an aware one raises
        # TypeError, which would replace a message naming the real problem with
        # one about datetime internals.
        if self.range_start.tzinfo is None or self.range_end.tzinfo is None:
            raise DatasetError(
                "dataset ranges must be timezone-aware; a naive bound is ambiguous and "
                "the ambiguity is a silently shifted hour of market data"
            )
        if self.range_end <= self.range_start:
            raise DatasetError("range_end must be after range_start")
        if not self.data_types:
            raise DatasetError("a dataset must request at least one data type")
        if not self.quality_filter:
            raise DatasetError(
                "quality_filter must admit at least one status; an empty filter would "
                "build an empty dataset from a healthy range"
            )


@dataclass(frozen=True, slots=True)
class GapRecord:
    """A gap overlapping the requested range."""

    gap_id: str
    asset: str
    event_type: str
    gap_start: datetime
    gap_end: datetime | None
    backfill_status: str

    @property
    def is_open(self) -> bool:
        """An unclosed gap: the stream never resumed, so its extent is unknown."""
        return self.gap_end is None

    @property
    def leaves_data_missing(self) -> bool:
        """Whether data is still absent because of this gap.

        PARTIAL counts as missing: some of the range was recovered and some was
        not, and a consumer cannot assume which rows it holds.
        """
        return self.backfill_status != "RECOVERED"


RowFetcher = Callable[[DatasetSpec], Sequence[dict[str, Any]]]
GapFetcher = Callable[[DatasetSpec], Sequence[GapRecord]]
Writer = Callable[[Sequence[dict[str, Any]], str], str]
"""Writes the rows and returns the storage URI it wrote them to."""


def _canonical_value(value: object) -> str:
    """Render one cell so that the same data always hashes the same.

    Decimals go through `str`, never `float`: a float round-trip can change the
    last digit of a venue tick, which would make an identical dataset hash
    differently on another machine. Datetimes are normalised to UTC, so a
    connection that returns local time does not produce a second identity for
    the same rows.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def compute_checksum(rows: Sequence[dict[str, Any]]) -> str:
    """Hash the rows themselves, in `CANONICAL_COLUMNS` order.

    Streamed rather than joined into one string: a dataset is expected to reach
    hundreds of millions of rows, and the checksum must not require holding a
    rendering of all of them in memory at once.
    """
    digest = hashlib.sha256()
    for row in rows:
        rendered = "\x1f".join(_canonical_value(row.get(column)) for column in CANONICAL_COLUMNS)
        digest.update(rendered.encode("utf-8"))
        digest.update(b"\x1e")
    return digest.hexdigest()


def derive_dataset_id(spec: DatasetSpec, checksum: str) -> str:
    """A name that the same data always produces.

    Content-derived rather than random, so rebuilding a dataset from an
    unchanged range yields the same id and two experiments citing that id are
    known to have used the same rows. A random uuid would make identity depend
    on when the builder happened to run.
    """
    start = spec.range_start.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    end = spec.range_end.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{spec.venue}-{spec.asset.lower()}-{start}-{end}-{checksum[:12]}"


def _summarise(
    rows: Sequence[dict[str, Any]],
    *,
    spec: DatasetSpec,
    excluded: int,
    gaps: Sequence[GapRecord],
) -> dict[str, object]:
    """Facts a consumer needs before trusting the rows."""
    by_type: dict[str, int] = {}
    backfill = 0
    for row in rows:
        event_type = str(row.get("event_type", "UNKNOWN"))
        by_type[event_type] = by_type.get(event_type, 0) + 1
        # Backfill is derivable rather than stored: an event the venue stamped
        # before the range opened was replayed to us, not observed live. It is
        # sound data that no latency figure may be computed from, so a consumer
        # has to be able to see how much of the dataset it is.
        occurred = row.get("exchange_time")
        if isinstance(occurred, datetime):
            moment = occurred if occurred.tzinfo else occurred.replace(tzinfo=UTC)
            if moment < spec.range_start:
                backfill += 1
    return {
        "rows_by_event_type": dict(sorted(by_type.items())),
        "rows_excluded_by_quality_filter": excluded,
        "quality_filter": [status.value for status in spec.quality_filter],
        "backfill_rows": backfill,
        "overlapping_gaps": len(gaps),
        "open_gaps": sum(1 for gap in gaps if gap.is_open),
        "unrecovered_gaps": sum(1 for gap in gaps if gap.leaves_data_missing),
    }


def _decide_quality(rows: Sequence[dict[str, Any]], gaps: Sequence[GapRecord]) -> DataQualityStatus:
    """The dataset's own status, which is not the rows' status.

    Every row may be VALID and the dataset still not be, because a dataset is a
    claim about a *range* and a gap means part of that range is missing. An open
    gap is worse than a closed one: the stream never resumed, so not even the
    extent of what is missing is known.
    """
    if not rows:
        return DataQualityStatus.INVALID
    if any(gap.is_open for gap in gaps):
        return DataQualityStatus.INVALID
    if any(gap.leaves_data_missing for gap in gaps):
        return DataQualityStatus.WARNING
    return DataQualityStatus.VALID


def build_dataset(
    spec: DatasetSpec,
    *,
    fetch_rows: RowFetcher,
    fetch_gaps: GapFetcher,
    write: Writer,
    now: datetime,
) -> DatasetManifest:
    """Build one dataset and return its manifest.

    The manifest is returned rather than written: this function decides what is
    true about the dataset, and persisting that decision is the caller's job.
    Keeping them apart means the classification can be tested without a
    database, and it is the classification that research depends on.
    """
    rows = list(fetch_rows(spec))
    admitted = {status.value for status in spec.quality_filter}
    kept = [row for row in rows if str(row.get("quality_status")) in admitted]
    excluded = len(rows) - len(kept)

    gaps = list(fetch_gaps(spec))
    checksum = compute_checksum(kept)
    dataset_id = derive_dataset_id(spec, checksum)
    storage_uri = write(kept, dataset_id)

    return DatasetManifest(
        dataset_id=dataset_id,
        source=SOURCE,
        venue=spec.venue,
        assets=(spec.asset,),
        data_types=spec.data_types,
        range_start=spec.range_start,
        range_end=spec.range_end,
        row_count=len(kept),
        created_at=now,
        schema_version=SCHEMA_VERSION,
        quality_status=_decide_quality(kept, gaps),
        quality_summary=_summarise(kept, spec=spec, excluded=excluded, gaps=gaps),
        # PIT_SAFE is a claim about leakage, not completeness. The range is
        # selected on receipt time and no column here can be revised after the
        # fact, so nothing from after T can reach a decision made at T. Whether
        # rows are *missing* is a quality question, and it is answered above.
        pit_status=PitStatus.PIT_SAFE,
        checksum=checksum,
        storage_uri=storage_uri,
        known_gap_ids=tuple(gap.gap_id for gap in gaps),
    )


def manifest_row(manifest: DatasetManifest) -> dict[str, Any]:
    """The manifest as the `dataset_manifests` table expects it."""
    return {
        "dataset_id": manifest.dataset_id,
        "source": manifest.source,
        "venue": manifest.venue,
        "assets": list(manifest.assets),
        "data_types": list(manifest.data_types),
        "range_start": manifest.range_start,
        "range_end": manifest.range_end,
        "row_count": manifest.row_count,
        "acquired_at": manifest.created_at,
        "source_version": manifest.source_version,
        "schema_version": manifest.schema_version,
        "feature_version": manifest.feature_version,
        "quality_status": manifest.quality_status.value,
        "quality_summary": json.dumps(manifest.quality_summary, sort_keys=True),
        "pit_status": manifest.pit_status.value,
        "checksum": manifest.checksum,
        "storage_uri": manifest.storage_uri,
        "known_gap_ids": list(manifest.known_gap_ids),
    }
