"""Writing dataset rows to disk.

Parquet, per Build 0.1 Rev.1 §8-9, which names the columnar store as the
analytical foundation. Written through Polars for the same reason.

The file is not what identifies the dataset — `dataset.compute_checksum` does,
over the rows themselves. A Parquet writer embeds its own version string, so
hashing the file would give identical data a new identity after a dependency
upgrade and invalidate every experiment that cited the old one. The file is
storage; the checksum is identity.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from services.research.dataset import CANONICAL_COLUMNS


def write_parquet(rows: Sequence[dict[str, Any]], dataset_id: str, *, directory: Path) -> str:
    """Write one dataset and return its storage URI.

    Refuses to overwrite. A dataset_id is content-derived, so a file already
    under that name holds the same rows; rewriting it could only replace
    identical data, and could only *differ* if something upstream was not as
    deterministic as it claims. Failing is how that gets noticed.
    """
    import polars as pl  # noqa: PLC0415 - heavy import, only needed when writing

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{dataset_id}.parquet"
    if path.exists():
        raise FileExistsError(
            f"{path} already exists. A dataset id is derived from its content, so this "
            f"holds the same rows; refusing to rewrite rather than assume that."
        )

    # An explicit empty frame with the right columns, rather than whatever an
    # empty list infers: a dataset with no rows still has a schema, and a
    # reader should fail on absent data rather than on absent columns.
    frame = pl.DataFrame(
        [{column: row.get(column) for column in CANONICAL_COLUMNS} for row in rows]
        if rows
        else {column: [] for column in CANONICAL_COLUMNS}
    )
    frame.write_parquet(path, compression="zstd")
    return path.resolve().as_uri()
