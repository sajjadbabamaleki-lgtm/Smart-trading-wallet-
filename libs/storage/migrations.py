"""SQL migrations without a framework (ADR-008).

Migrations are numbered `.sql` files applied in order, with the checksum of
each file recorded as applied. Two properties matter more than convenience:

**A migration that changed after being applied is detected.** Editing an
applied migration produces environments whose schemas differ while both claim
to be at the same version — a divergence that surfaces later as a confusing
data defect. The runner refuses to proceed instead.

**Applying is idempotent and ordered.** Re-running applies nothing. A gap or a
duplicate in the numbering is refused rather than guessed at, because the order
in which schema changes are applied is not something to leave ambiguous.

The runner is deliberately small and store-agnostic: it executes SQL and writes
a ledger row, and knows nothing about PostgreSQL or ClickHouse beyond what the
injected executor does. That is what lets the same logic serve both — Alembic
would cover only one (ADR-008).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

FILENAME_PATTERN = re.compile(r"^(?P<version>\d{3})_(?P<name>[a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    """A migration cannot be applied safely. Nothing further is attempted."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One migration file."""

    version: str
    name: str
    path: Path
    sql: str
    checksum: str

    @property
    def statements(self) -> tuple[str, ...]:
        """SQL split into individual statements.

        ClickHouse's HTTP interface accepts one statement per request, so a
        multi-statement file must be split. The split is on semicolons outside
        of line comments and string literals; anything more elaborate would
        need a real parser, and migration files are ours to keep simple.
        """
        statements: list[str] = []
        current: list[str] = []
        in_string = False
        index = 0
        while index < len(self.sql):
            char = self.sql[index]
            pair = self.sql[index : index + 2]

            if not in_string and pair == "--":
                newline = self.sql.find("\n", index)
                index = len(self.sql) if newline == -1 else newline
                continue
            if char == "'":
                in_string = not in_string
            if char == ";" and not in_string:
                statements.append("".join(current).strip())
                current = []
                index += 1
                continue
            current.append(char)
            index += 1

        tail = "".join(current).strip()
        if tail:
            statements.append(tail)
        return tuple(statement for statement in statements if statement)


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """What applying would do, without doing it."""

    pending: tuple[Migration, ...]
    already_applied: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.pending


def _checksum(sql: str) -> str:
    """Checksum of a migration's content.

    Line endings are normalised so a file checked out on a different platform
    does not read as modified.
    """
    normalised = sql.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def discover_migrations(directory: Path) -> tuple[Migration, ...]:
    """Load migrations from `directory`, ordered by version.

    Refuses a filename that does not match `NNN_lower_snake_name.sql`, a
    duplicate version, or a gap in the sequence. Each of those is ambiguous
    about ordering, and ambiguity about the order of schema changes is not
    something to resolve by guessing.
    """
    if not directory.is_dir():
        raise MigrationError(f"migration directory does not exist: {directory}")

    migrations: list[Migration] = []
    unmatched: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        match = FILENAME_PATTERN.match(path.name)
        if match is None:
            unmatched.append(path.name)
            continue
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=match.group("version"),
                name=match.group("name"),
                path=path,
                sql=sql,
                checksum=_checksum(sql),
            )
        )

    if unmatched:
        raise MigrationError(
            f"file(s) in {directory} do not match NNN_name.sql: {', '.join(sorted(unmatched))}"
        )
    if not migrations:
        raise MigrationError(f"no migrations found in {directory}")

    versions = [migration.version for migration in migrations]
    duplicates = sorted({version for version in versions if versions.count(version) > 1})
    if duplicates:
        raise MigrationError(f"duplicate migration version(s): {', '.join(duplicates)}")

    expected = [f"{index:03d}" for index in range(1, len(migrations) + 1)]
    if versions != expected:
        raise MigrationError(
            f"migration versions must be contiguous from 001; found "
            f"{', '.join(versions)} but expected {', '.join(expected)}"
        )

    return tuple(migrations)


class MigrationRunner:
    """Applies migrations against one store.

    The store is reached through two injected callables, so this class has no
    database dependency and is fully testable without one:

    `execute`
        Run one SQL statement.
    `fetch_applied`
        Return `(version, checksum)` for every recorded migration.
    """

    def __init__(
        self,
        *,
        directory: Path,
        execute: Callable[[str], None],
        fetch_applied: Callable[[], Sequence[tuple[str, str]]],
        ledger_table: str = "schema_migrations",
    ) -> None:
        self._directory = directory
        self._execute = execute
        self._fetch_applied = fetch_applied
        self._ledger_table = ledger_table

    def plan(self) -> MigrationPlan:
        """Determine what would be applied, verifying nothing has changed.

        Raises `MigrationError` when a recorded checksum no longer matches the
        file, or when a version is recorded that no longer exists on disk — a
        deleted migration means the ledger describes a schema that cannot be
        reproduced.
        """
        migrations = discover_migrations(self._directory)
        applied = dict(self._fetch_applied())
        by_version = {migration.version: migration for migration in migrations}

        modified = [
            f"{version} ({by_version[version].name})"
            for version, checksum in applied.items()
            if version in by_version and by_version[version].checksum != checksum
        ]
        if modified:
            raise MigrationError(
                f"applied migration(s) have been modified: {', '.join(sorted(modified))}. "
                f"An applied migration must never be edited - environments would "
                f"silently diverge while reporting the same version. Add a new "
                f"migration instead."
            )

        vanished = sorted(set(applied) - set(by_version))
        if vanished:
            raise MigrationError(
                f"migration(s) recorded as applied but missing from {self._directory}: "
                f"{', '.join(vanished)}"
            )

        pending = tuple(migration for migration in migrations if migration.version not in applied)
        return MigrationPlan(pending=pending, already_applied=tuple(sorted(applied)))

    def apply(self, *, dry_run: bool = False) -> tuple[Migration, ...]:
        """Apply pending migrations in order, returning those applied.

        Stops at the first failure rather than continuing: a later migration
        may depend on an earlier one, so proceeding past a failure risks
        applying changes to a schema that is not in the expected state.
        """
        plan = self.plan()
        if dry_run:
            return plan.pending

        applied: list[Migration] = []
        for migration in plan.pending:
            for statement in migration.statements:
                try:
                    self._execute(statement)
                except Exception as exc:
                    raise MigrationError(
                        f"migration {migration.version} ({migration.name}) failed: {exc}"
                    ) from exc
            self._execute(self._ledger_insert(migration))
            applied.append(migration)
        return tuple(applied)

    def _ledger_insert(self, migration: Migration) -> str:
        """SQL recording a migration as applied.

        Values are safe to interpolate: version and name come from a filename
        that matched `FILENAME_PATTERN` (digits and lower-snake only) and the
        checksum is hex from hashlib, so none can carry a quote. The duration is
        recorded as 0 here because elapsed time is measured per store at a
        higher level; the column exists so timing can be filled in without a
        schema change.
        """
        # S608 (SQL built by interpolation) is suppressed deliberately: the
        # table name is a constructor argument, version and name come from a
        # filename that matched FILENAME_PATTERN (digits and lower-snake only),
        # and the checksum is hex from hashlib — none can carry a quote. The
        # store-agnostic executor takes a plain string, so there is no
        # parameter binding available here.
        return (
            f"INSERT INTO {self._ledger_table} (version, name, checksum, duration_ms) "  # noqa: S608
            f"VALUES ('{migration.version}', '{migration.name}', "
            f"'{migration.checksum}', 0)"
        )
