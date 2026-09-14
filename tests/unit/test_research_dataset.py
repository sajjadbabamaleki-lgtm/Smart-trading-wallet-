"""The dataset builder's decisions.

M4's deliverable is not a file — it is the claim attached to one. These tests
are over that claim: what the range means, what the checksum covers, when a
dataset may be called VALID, and what a consumer is told about what it is
holding.

No store is reached. Rows and gaps arrive through the injected callables the
builder takes, which is what lets the awkward cases be constructed at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from libs.schemas.dataset import DatasetManifest
from libs.schemas.enums import DataQualityStatus, PitStatus
from services.research.dataset import (
    DatasetError,
    DatasetSpec,
    GapRecord,
    build_dataset,
    compute_checksum,
    derive_dataset_id,
)

START = datetime(2026, 9, 14, 21, 0, tzinfo=UTC)
END = START + timedelta(hours=1)
NOW = END + timedelta(minutes=1)


def row(
    *,
    event_id: str = "evt_1",
    event_type: str = "TRADE",
    received: datetime | None = None,
    exchange_time: datetime | None = None,
    price: Decimal = Decimal(60000),
    quality: str = "VALID",
) -> dict[str, Any]:
    moment = received or START + timedelta(minutes=1)
    return {
        "event_id": event_id,
        "asset": "BTC",
        "instrument": "BTC-PERP",
        "event_type": event_type,
        "exchange_time": exchange_time or moment,
        "local_receive_time": moment,
        "venue_event_id": "1001",
        "price": price,
        "quantity": Decimal("0.01"),
        "side": "BUY",
        "bid_price": None,
        "bid_quantity": None,
        "ask_price": None,
        "ask_quantity": None,
        "funding_rate": None,
        "open_interest": None,
        "quality_status": quality,
        "pit_status": "PIT_SAFE",
    }


def build(
    rows: list[dict[str, Any]],
    gaps: list[GapRecord] | None = None,
    spec: DatasetSpec | None = None,
) -> DatasetManifest:
    def write(_rows: Sequence[dict[str, Any]], dataset_id: str) -> str:
        return f"file:///tmp/{dataset_id}"

    return build_dataset(
        spec or DatasetSpec(asset="BTC", range_start=START, range_end=END),
        fetch_rows=lambda _: rows,
        fetch_gaps=lambda _: gaps or [],
        write=write,
        now=NOW,
    )


def gap(
    *,
    gap_id: str = "11111111-1111-1111-1111-111111111111",
    end: datetime | None = None,
    status: str = "PENDING",
) -> GapRecord:
    return GapRecord(
        gap_id=gap_id,
        asset="BTC",
        event_type="TRADE",
        gap_start=START + timedelta(minutes=10),
        gap_end=end,
        backfill_status=status,
    )


class TestSpec:
    def test_a_backwards_range_is_refused(self) -> None:
        with pytest.raises(DatasetError, match="after range_start"):
            DatasetSpec(asset="BTC", range_start=END, range_end=START)

    def test_a_naive_range_is_refused(self) -> None:
        """A naive bound is ambiguous, and the ambiguity is a silent hour."""
        with pytest.raises(DatasetError, match="timezone-aware"):
            DatasetSpec(
                asset="BTC",
                range_start=datetime(2026, 9, 14, 21, 0),
                range_end=END,
            )

    def test_an_empty_quality_filter_is_refused(self) -> None:
        """It would silently build an empty dataset from a healthy range."""
        with pytest.raises(DatasetError, match="at least one status"):
            DatasetSpec(asset="BTC", range_start=START, range_end=END, quality_filter=())


class TestChecksum:
    def test_the_same_rows_hash_the_same(self) -> None:
        assert compute_checksum([row()]) == compute_checksum([row()])

    def test_a_changed_value_changes_the_checksum(self) -> None:
        assert compute_checksum([row()]) != compute_checksum([row(price=Decimal(60001))])

    def test_order_is_part_of_identity(self) -> None:
        """Two orderings of the same rows are two different datasets.

        This is why the query orders explicitly: an unordered read would give
        the same data a new identity on every run.
        """
        first, second = row(event_id="a"), row(event_id="b")
        assert compute_checksum([first, second]) != compute_checksum([second, first])

    def test_a_decimal_is_hashed_as_written(self) -> None:
        """Never through float: a round-trip can move the last digit of a tick."""
        exact = compute_checksum([row(price=Decimal("60000.00000001"))])
        assert exact != compute_checksum([row(price=Decimal("60000.00000002"))])

    def test_timezone_representation_does_not_change_identity(self) -> None:
        """The same instant in another zone is the same instant.

        A connection configured to return local time must not produce a second
        identity for rows that have not changed.
        """
        tehran = timezone(timedelta(hours=3, minutes=30))
        moment = START + timedelta(minutes=5)
        assert compute_checksum([row(received=moment)]) == compute_checksum(
            [row(received=moment.astimezone(tehran))]
        )


class TestIdentity:
    def test_the_same_data_yields_the_same_id(self) -> None:
        """Rebuilding an unchanged range must cite the same dataset."""
        assert build([row()]).dataset_id == build([row()]).dataset_id

    def test_different_data_yields_a_different_id(self) -> None:
        assert build([row()]).dataset_id != build([row(price=Decimal(1))]).dataset_id

    def test_the_id_names_the_range_it_covers(self) -> None:
        spec = DatasetSpec(asset="BTC", range_start=START, range_end=END)
        identifier = derive_dataset_id(spec, "abc123def456789")
        assert "btc" in identifier
        assert "20260914T210000Z" in identifier
        assert "hyperliquid" in identifier


class TestQualityFilter:
    def test_only_valid_rows_are_admitted_by_default(self) -> None:
        manifest = build([row(event_id="a"), row(event_id="b", quality="INVALID")])
        assert manifest.row_count == 1

    def test_exclusions_are_counted_rather_than_silent(self) -> None:
        """A dataset that dropped a tenth of its range must say so."""
        manifest = build([row(event_id="a"), row(event_id="b", quality="INVALID")])
        assert manifest.quality_summary["rows_excluded_by_quality_filter"] == 1

    def test_the_filter_used_is_recorded(self) -> None:
        manifest = build([row()])
        assert manifest.quality_summary["quality_filter"] == ["VALID"]

    def test_admitting_warnings_is_a_deliberate_widening(self) -> None:
        spec = DatasetSpec(
            asset="BTC",
            range_start=START,
            range_end=END,
            quality_filter=(DataQualityStatus.VALID, DataQualityStatus.WARNING),
        )
        manifest = build([row(event_id="a", quality="WARNING")], spec=spec)
        assert manifest.row_count == 1
        assert manifest.quality_summary["quality_filter"] == ["VALID", "WARNING"]


class TestGaps:
    def test_an_overlapping_gap_travels_with_the_manifest(self) -> None:
        manifest = build([row()], [gap(end=START + timedelta(minutes=20))])
        assert manifest.known_gap_ids == ("11111111-1111-1111-1111-111111111111",)

    def test_an_open_gap_makes_the_dataset_invalid(self) -> None:
        """The stream never resumed, so not even the extent is known."""
        manifest = build([row()], [gap(end=None)])
        assert manifest.quality_status is DataQualityStatus.INVALID

    def test_an_unrecovered_closed_gap_is_a_warning(self) -> None:
        manifest = build([row()], [gap(end=START + timedelta(minutes=20))])
        assert manifest.quality_status is DataQualityStatus.WARNING

    def test_a_recovered_gap_leaves_the_dataset_valid(self) -> None:
        """Recovery means the data is present; the gap is history, not damage."""
        manifest = build([row()], [gap(end=START + timedelta(minutes=20), status="RECOVERED")])
        assert manifest.quality_status is DataQualityStatus.VALID

    def test_a_partial_recovery_still_counts_as_missing(self) -> None:
        manifest = build([row()], [gap(end=START + timedelta(minutes=20), status="PARTIAL")])
        assert manifest.quality_status is DataQualityStatus.WARNING


class TestEmptyDatasets:
    def test_an_empty_dataset_is_invalid(self) -> None:
        """It verified nothing, so it cannot be a clean research input."""
        assert build([]).quality_status is DataQualityStatus.INVALID

    def test_an_empty_dataset_is_not_usable_for_training(self) -> None:
        assert not build([]).usable_for_training

    def test_the_manifest_refuses_to_call_an_empty_dataset_valid(self) -> None:
        with pytest.raises(ValueError, match="verified nothing"):
            DatasetManifest(
                dataset_id="d",
                source="s",
                assets=("BTC",),
                data_types=("TRADE",),
                range_start=START,
                range_end=END,
                row_count=0,
                created_at=NOW,
                quality_status=DataQualityStatus.VALID,
                pit_status=PitStatus.PIT_SAFE,
                checksum="x",
                storage_uri="file:///tmp/x",
            )


class TestBackfillVisibility:
    def test_replayed_rows_are_counted(self) -> None:
        """An event stamped before the range opened was replayed, not observed.

        Sound data that no latency figure may be computed from, so a consumer
        has to be able to see how much of the dataset it is.
        """
        manifest = build(
            [
                row(event_id="a", exchange_time=START - timedelta(seconds=35)),
                row(event_id="b"),
            ]
        )
        assert manifest.quality_summary["backfill_rows"] == 1

    def test_a_dataset_of_live_rows_reports_no_backfill(self) -> None:
        assert build([row()]).quality_summary["backfill_rows"] == 0


class TestManifestClaims:
    def test_the_range_is_the_one_that_was_asked_for(self) -> None:
        manifest = build([row()])
        assert manifest.range_start == START
        assert manifest.range_end == END

    def test_rows_are_broken_down_by_type(self) -> None:
        manifest = build([row(event_id="a"), row(event_id="b", event_type="BBO")])
        assert manifest.quality_summary["rows_by_event_type"] == {"BBO": 1, "TRADE": 1}

    def test_a_clean_dataset_is_usable_for_training(self) -> None:
        manifest = build([row()])
        assert manifest.quality_status is DataQualityStatus.VALID
        assert manifest.pit_status is PitStatus.PIT_SAFE
        assert manifest.usable_for_training

    def test_a_gapped_dataset_is_not_usable_for_training(self) -> None:
        """Both conditions are required, and quality is the one that fails here."""
        manifest = build([row()], [gap(end=None)])
        assert manifest.pit_status is PitStatus.PIT_SAFE
        assert not manifest.usable_for_training

    def test_the_manifest_is_frozen(self) -> None:
        """It describes data already written; changing it would make them disagree."""
        manifest = build([row()])
        with pytest.raises(ValueError, match="frozen"):
            manifest.row_count = 99  # type: ignore[misc]
