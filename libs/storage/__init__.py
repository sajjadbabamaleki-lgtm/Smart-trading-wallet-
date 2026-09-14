"""Storage access and schema migrations.

Each store has one responsibility, per the source-of-truth hierarchy in
Build 0.1 Rev.1 §16 (see ADR-002, ADR-003):

- PostgreSQL — transactional application state
- ClickHouse — analytical event history
- Redis      — ephemeral cache and coordination, never capital state
- Object store — immutable raw archive

No single store is authoritative for everything, and the venue is authoritative
for actual exposure.
"""

from libs.storage.health import StoreHealth, StoreStatus, check_all
from libs.storage.migrations import (
    Migration,
    MigrationError,
    MigrationPlan,
    MigrationRunner,
    discover_migrations,
)
from libs.storage.object_store import raw_key
from libs.storage.redis_store import namespaced

__all__ = [
    "Migration",
    "MigrationError",
    "MigrationPlan",
    "MigrationRunner",
    "StoreHealth",
    "StoreStatus",
    "check_all",
    "discover_migrations",
    "namespaced",
    "raw_key",
]
