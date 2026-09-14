"""Migration discovery and application.

Fully exercised without a database: the runner reaches its store through two
injected callables, so a list and a dict stand in for one.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from libs.storage.migrations import (
    MigrationError,
    MigrationRunner,
    discover_migrations,
)


class FakeStore:
    """Records statements and answers the ledger query from them."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.applied: dict[str, str] = {}
        self.fail_on: str | None = None

    def execute(self, statement: str) -> None:
        if self.fail_on is not None and self.fail_on in statement:
            raise RuntimeError(f"simulated failure on {self.fail_on}")
        self.statements.append(statement)
        if statement.startswith("INSERT INTO schema_migrations"):
            version = statement.split("VALUES ('", 1)[1].split("'", 1)[0]
            checksum = statement.split("', '")[2].split("'", 1)[0]
            self.applied[version] = checksum

    def fetch_applied(self) -> Sequence[tuple[str, str]]:
        return list(self.applied.items())


def write(directory: Path, name: str, sql: str) -> Path:
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return path


def runner_for(directory: Path, store: FakeStore) -> MigrationRunner:
    return MigrationRunner(
        directory=directory, execute=store.execute, fetch_applied=store.fetch_applied
    )


class TestDiscovery:
    def test_migrations_are_ordered_by_version(self, tmp_path: Path) -> None:
        write(tmp_path, "002_second.sql", "SELECT 2;")
        write(tmp_path, "001_first.sql", "SELECT 1;")
        write(tmp_path, "003_third.sql", "SELECT 3;")
        found = discover_migrations(tmp_path)
        assert [m.version for m in found] == ["001", "002", "003"]
        assert [m.name for m in found] == ["first", "second", "third"]

    def test_missing_directory_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(MigrationError, match="does not exist"):
            discover_migrations(tmp_path / "absent")

    def test_empty_directory_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(MigrationError, match="no migrations found"):
            discover_migrations(tmp_path)

    def test_badly_named_file_is_refused(self, tmp_path: Path) -> None:
        write(tmp_path, "001_first.sql", "SELECT 1;")
        write(tmp_path, "add_index.sql", "SELECT 2;")
        with pytest.raises(MigrationError, match="do not match"):
            discover_migrations(tmp_path)

    def test_gap_in_numbering_is_refused(self, tmp_path: Path) -> None:
        """A gap is ambiguous about whether a migration was lost."""
        write(tmp_path, "001_first.sql", "SELECT 1;")
        write(tmp_path, "003_third.sql", "SELECT 3;")
        with pytest.raises(MigrationError, match="contiguous"):
            discover_migrations(tmp_path)

    def test_hidden_files_are_ignored(self, tmp_path: Path) -> None:
        write(tmp_path, "001_first.sql", "SELECT 1;")
        write(tmp_path, ".DS_Store", "junk")
        assert len(discover_migrations(tmp_path)) == 1

    def test_checksum_changes_with_content(self, tmp_path: Path) -> None:
        path = write(tmp_path, "001_first.sql", "SELECT 1;")
        before = discover_migrations(tmp_path)[0].checksum
        path.write_text("SELECT 2;", encoding="utf-8")
        assert discover_migrations(tmp_path)[0].checksum != before

    def test_checksum_ignores_line_endings(self, tmp_path: Path) -> None:
        """A checkout on another platform must not read as modified."""
        write(tmp_path, "001_first.sql", "SELECT 1;\nSELECT 2;\n")
        unix = discover_migrations(tmp_path)[0].checksum
        write(tmp_path, "001_first.sql", "SELECT 1;\r\nSELECT 2;\r\n")
        assert discover_migrations(tmp_path)[0].checksum == unix


class TestStatementSplitting:
    def test_statements_are_split_on_semicolons(self, tmp_path: Path) -> None:
        write(tmp_path, "001_first.sql", "CREATE TABLE a (x Int);\nCREATE TABLE b (y Int);")
        assert len(discover_migrations(tmp_path)[0].statements) == 2

    def test_comments_are_stripped(self, tmp_path: Path) -> None:
        write(tmp_path, "001_first.sql", "-- a note\nSELECT 1;\n-- another\n")
        statements = discover_migrations(tmp_path)[0].statements
        assert statements == ("SELECT 1",)

    def test_semicolon_inside_a_string_does_not_split(self, tmp_path: Path) -> None:
        write(tmp_path, "001_first.sql", "SELECT 'a;b' AS value;")
        statements = discover_migrations(tmp_path)[0].statements
        assert statements == ("SELECT 'a;b' AS value",)

    def test_trailing_statement_without_semicolon_is_kept(self, tmp_path: Path) -> None:
        write(tmp_path, "001_first.sql", "SELECT 1;\nSELECT 2")
        assert len(discover_migrations(tmp_path)[0].statements) == 2

    def test_comment_only_file_yields_no_statements(self, tmp_path: Path) -> None:
        write(tmp_path, "001_first.sql", "-- nothing to do yet\n")
        assert discover_migrations(tmp_path)[0].statements == ()


class TestApplication:
    def test_pending_migrations_are_applied_in_order(self, tmp_path: Path) -> None:
        write(tmp_path, "001_first.sql", "CREATE TABLE a (x Int);")
        write(tmp_path, "002_second.sql", "CREATE TABLE b (y Int);")
        store = FakeStore()
        applied = runner_for(tmp_path, store).apply()
        assert [m.version for m in applied] == ["001", "002"]
        assert store.statements[0].startswith("CREATE TABLE a")
        assert store.statements[2].startswith("CREATE TABLE b")

    def test_reapplying_does_nothing(self, tmp_path: Path) -> None:
        write(tmp_path, "001_first.sql", "CREATE TABLE a (x Int);")
        store = FakeStore()
        runner = runner_for(tmp_path, store)
        runner.apply()
        count = len(store.statements)
        assert runner.apply() == ()
        assert len(store.statements) == count

    def test_only_new_migrations_are_applied(self, tmp_path: Path) -> None:
        write(tmp_path, "001_first.sql", "CREATE TABLE a (x Int);")
        store = FakeStore()
        runner_for(tmp_path, store).apply()
        write(tmp_path, "002_second.sql", "CREATE TABLE b (y Int);")
        applied = runner_for(tmp_path, store).apply()
        assert [m.version for m in applied] == ["002"]

    def test_dry_run_applies_nothing(self, tmp_path: Path) -> None:
        write(tmp_path, "001_first.sql", "CREATE TABLE a (x Int);")
        store = FakeStore()
        pending = runner_for(tmp_path, store).apply(dry_run=True)
        assert [m.version for m in pending] == ["001"]
        assert store.statements == []

    def test_a_ledger_row_is_written_per_migration(self, tmp_path: Path) -> None:
        write(tmp_path, "001_first.sql", "CREATE TABLE a (x Int);")
        store = FakeStore()
        runner_for(tmp_path, store).apply()
        inserts = [s for s in store.statements if s.startswith("INSERT INTO schema_migrations")]
        assert len(inserts) == 1
        assert "001" in inserts[0]

    def test_application_stops_at_the_first_failure(self, tmp_path: Path) -> None:
        """A later migration may depend on an earlier one."""
        write(tmp_path, "001_first.sql", "CREATE TABLE a (x Int);")
        write(tmp_path, "002_second.sql", "CREATE TABLE b (y Int);")
        write(tmp_path, "003_third.sql", "CREATE TABLE c (z Int);")
        store = FakeStore()
        store.fail_on = "TABLE b"
        with pytest.raises(MigrationError, match="002 \\(second\\) failed"):
            runner_for(tmp_path, store).apply()
        assert "001" in store.applied
        assert "003" not in store.applied
        assert not any("TABLE c" in s for s in store.statements)


class TestDivergenceDetection:
    def test_editing_an_applied_migration_is_refused(self, tmp_path: Path) -> None:
        """Environments would silently diverge while reporting one version."""
        path = write(tmp_path, "001_first.sql", "CREATE TABLE a (x Int);")
        store = FakeStore()
        runner_for(tmp_path, store).apply()

        path.write_text("CREATE TABLE a (x String);", encoding="utf-8")
        with pytest.raises(MigrationError, match="have been modified"):
            runner_for(tmp_path, store).plan()

    def test_the_refusal_says_what_to_do_instead(self, tmp_path: Path) -> None:
        path = write(tmp_path, "001_first.sql", "CREATE TABLE a (x Int);")
        store = FakeStore()
        runner_for(tmp_path, store).apply()
        path.write_text("CREATE TABLE a (x String);", encoding="utf-8")
        with pytest.raises(MigrationError, match="Add a new migration instead"):
            runner_for(tmp_path, store).plan()

    def test_deleting_an_applied_migration_is_refused(self, tmp_path: Path) -> None:
        """The ledger would describe a schema that cannot be reproduced."""
        write(tmp_path, "001_first.sql", "CREATE TABLE a (x Int);")
        write(tmp_path, "002_second.sql", "CREATE TABLE b (y Int);")
        store = FakeStore()
        runner_for(tmp_path, store).apply()

        (tmp_path / "002_second.sql").unlink()
        with pytest.raises(MigrationError, match="missing from"):
            runner_for(tmp_path, store).plan()

    def test_plan_reports_pending_and_applied(self, tmp_path: Path) -> None:
        write(tmp_path, "001_first.sql", "CREATE TABLE a (x Int);")
        store = FakeStore()
        runner_for(tmp_path, store).apply()
        write(tmp_path, "002_second.sql", "CREATE TABLE b (y Int);")

        plan = runner_for(tmp_path, store).plan()
        assert plan.already_applied == ("001",)
        assert [m.version for m in plan.pending] == ["002"]
        assert not plan.is_empty


class TestRepositoryMigrations:
    """The real migration files must satisfy the same rules."""

    @pytest.mark.parametrize("store", ["postgres", "clickhouse"])
    def test_shipped_migrations_are_discoverable(self, store: str) -> None:
        directory = Path(__file__).resolve().parents[2] / "infrastructure/database" / store
        migrations = discover_migrations(directory)
        assert len(migrations) >= 1
        assert migrations[0].version == "001"
        assert "schema_migrations" in migrations[0].sql

    @pytest.mark.parametrize("store", ["postgres", "clickhouse"])
    def test_shipped_migrations_apply_cleanly_against_a_fake_store(self, store: str) -> None:
        directory = Path(__file__).resolve().parents[2] / "infrastructure/database" / store
        fake = FakeStore()
        applied = MigrationRunner(
            directory=directory, execute=fake.execute, fetch_applied=fake.fetch_applied
        ).apply()
        assert len(applied) == len(discover_migrations(directory))

    @pytest.mark.parametrize("store", ["postgres", "clickhouse"])
    def test_every_shipped_migration_yields_at_least_one_statement(self, store: str) -> None:
        directory = Path(__file__).resolve().parents[2] / "infrastructure/database" / store
        for migration in discover_migrations(directory):
            assert migration.statements, f"{migration.path.name} produced no statements"
