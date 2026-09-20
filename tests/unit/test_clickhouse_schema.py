"""Static checks over the ClickHouse DDL.

The migration that creates `market_events` failed on its first run against a
real server: ClickHouse refuses a sorting key containing a nullable column
unless `allow_nullable_key` is set, and `exchange_time` is nullable by design.

Nothing about that needed a database to detect. It is a property of the SQL
text, and this is the cheap check that would have caught it before the stack
was ever started — which matters here beyond the one bug, because a failed
migration is discovered late, on a machine the author may not have, after
several minutes of setup.

The parsing is deliberately literal: it reads the DDL the way the file is
written rather than modelling SQL. A file that stops matching these shapes
should be read by a person, and an unparseable one fails rather than passes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DDL_DIR = Path(__file__).resolve().parents[2] / "infrastructure" / "database" / "clickhouse"

CREATE_TABLE = re.compile(
    r"CREATE TABLE IF NOT EXISTS\s+(?P<name>\w+)\s*\((?P<body>.*?)\n\)", re.DOTALL
)
ORDER_BY = re.compile(r"^ORDER BY\s*\((?P<columns>[^)]*)\)", re.MULTILINE)
# A column declaration: leading whitespace, an identifier, then its type. Lines
# that begin with a comment marker or a keyword are not declarations.
COLUMN = re.compile(r"^\s{2,}(?P<name>[a-z_][a-z0-9_]*)\s+(?P<type>[A-Za-z].*?),?\s*$")


def ddl_files() -> list[Path]:
    files = sorted(DDL_DIR.glob("*.sql"))
    assert files, f"no DDL found in {DDL_DIR}"
    return files


def column_types(body: str) -> dict[str, str]:
    """Map column name to its declared type, for one CREATE TABLE body."""
    types: dict[str, str] = {}
    for line in body.splitlines():
        if not line.strip() or line.strip().startswith("--"):
            continue
        match = COLUMN.match(line)
        if match and not match.group("name").isupper():
            types[match.group("name")] = match.group("type")
    return types


@pytest.mark.parametrize("path", ddl_files(), ids=lambda p: p.name)
def test_sorting_key_columns_are_not_nullable(path: Path) -> None:
    """ClickHouse rejects a nullable sorting key, and it is right to.

    A column that is nullable *on purpose* — absent means the venue supplied
    nothing — cannot also carry a position in the table's ordering without the
    engine inventing one for the unknowns. The fix is never to enable
    `allow_nullable_key`; it is to sort by a column that is always present.
    """
    sql = path.read_text()
    for table in CREATE_TABLE.finditer(sql):
        types = column_types(table.group("body"))
        # Searched from the end of this table's body rather than from the
        # start of the file. Every migration here defines one table, but the
        # earlier version took the file's first ORDER BY for every CREATE
        # TABLE in it -- which in a two-table file checked one table's
        # columns against the other's sorting key, and would just as easily
        # have missed a real violation in the second table.
        order_by = ORDER_BY.search(sql, table.end())
        if order_by is None:
            continue
        for column in (part.strip() for part in order_by.group("columns").split(",")):
            declared = types.get(column)
            assert declared is not None, (
                f"{path.name}: sorting key names {column!r}, which is not a column of "
                f"{table.group('name')}"
            )
            assert "Nullable(" not in declared, (
                f"{path.name}: {table.group('name')} sorts by {column!r}, declared "
                f"{declared!r}. ClickHouse refuses a nullable sorting key. Sort by a "
                f"column that is always present — local_receive_time is ours and is "
                f"never absent — rather than enabling allow_nullable_key."
            )


@pytest.mark.parametrize("path", ddl_files(), ids=lambda p: p.name)
def test_allow_nullable_key_is_never_enabled(path: Path) -> None:
    """The setting exists; using it here would hide the question above."""
    assert "allow_nullable_key" not in path.read_text()


def test_event_tables_sort_by_receipt_time() -> None:
    """Point-in-time correctness is expressed in the sorting key, not a comment.

    At decision time T only information received by T may be used, so the scan
    the research layer must run is a `local_receive_time` range. If the tables
    were ordered by venue time, that query would be the unindexed one — the
    invariant would survive in prose while the schema worked against it.
    """
    for name in ("002_market_events.sql", "003_trader_events.sql"):
        sql = (DDL_DIR / name).read_text()
        order_by = ORDER_BY.search(sql)
        assert order_by is not None, f"{name}: no ORDER BY found"
        columns = [part.strip() for part in order_by.group("columns").split(",")]
        assert "local_receive_time" in columns, f"{name}: sorts by {columns}"
        assert "exchange_time" not in columns, (
            f"{name}: sorts by venue time {columns}; the point-in-time query is over receipt time"
        )
