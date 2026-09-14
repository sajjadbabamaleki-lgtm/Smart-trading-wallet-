"""Writing a dataset to disk."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from services.research.dataset import CANONICAL_COLUMNS
from services.research.writer import write_parquet

MOMENT = datetime(2026, 9, 14, 21, 0, tzinfo=UTC)


def row(event_id: str = "evt_1") -> dict[str, Any]:
    values: dict[str, Any] = dict.fromkeys(CANONICAL_COLUMNS)
    values.update(
        {
            "event_id": event_id,
            "asset": "BTC",
            "instrument": "BTC-PERP",
            "event_type": "TRADE",
            "exchange_time": MOMENT,
            "local_receive_time": MOMENT,
            "venue_event_id": "1001",
            "price": Decimal(60000),
            "quantity": Decimal("0.01"),
            "side": "BUY",
            "quality_status": "VALID",
            "pit_status": "PIT_SAFE",
        }
    )
    return values


def test_rows_survive_the_round_trip(tmp_path: Path) -> None:
    uri = write_parquet([row()], "d1", directory=tmp_path)
    frame = pl.read_parquet(tmp_path / "d1.parquet")
    assert frame.height == 1
    assert frame["event_id"][0] == "evt_1"
    assert uri.startswith("file://")


def test_the_column_order_is_the_canonical_one(tmp_path: Path) -> None:
    """The checksum is computed over these in this order."""
    write_parquet([row()], "d2", directory=tmp_path)
    assert tuple(pl.read_parquet(tmp_path / "d2.parquet").columns) == CANONICAL_COLUMNS


def test_an_empty_dataset_still_has_its_schema(tmp_path: Path) -> None:
    """A reader should fail on absent data, not on absent columns."""
    write_parquet([], "d3", directory=tmp_path)
    frame = pl.read_parquet(tmp_path / "d3.parquet")
    assert frame.height == 0
    assert tuple(frame.columns) == CANONICAL_COLUMNS


def test_an_existing_dataset_is_never_rewritten(tmp_path: Path) -> None:
    """A dataset id is content-derived, so a rewrite could only differ by defect."""
    write_parquet([row()], "d4", directory=tmp_path)
    with pytest.raises(FileExistsError, match="same rows"):
        write_parquet([row()], "d4", directory=tmp_path)


def test_the_directory_is_created_on_demand(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "datasets"
    write_parquet([row()], "d5", directory=target)
    assert (target / "d5.parquet").is_file()
