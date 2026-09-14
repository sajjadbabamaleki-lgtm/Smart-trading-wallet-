"""Integration tests against the running stack.

Marked `integration` and excluded from the default run, because they need
`make stack-up`. Run with `make test-integration`.

These are what make M1's claim checkable: not that the clients compile, but
that each store accepts the operation the platform actually needs from it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from libs.config import Settings, load_settings
from libs.storage import clickhouse as ch
from libs.storage import object_store as obj
from libs.storage import postgres as pg
from libs.storage import redis_store as rds
from libs.storage.object_store import raw_key

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def settings() -> Settings:
    return load_settings()


class TestHealthChecks:
    def test_postgres_is_healthy(self, settings: Settings) -> None:
        health = pg.check_health(settings.postgres_dsn)
        assert health.is_usable, health.detail
        assert "version" in health.facts

    def test_clickhouse_is_healthy(self, settings: Settings) -> None:
        health = ch.check_health_from_settings(settings)
        assert health.is_usable, health.detail

    def test_redis_is_healthy_and_ephemeral(self, settings: Settings) -> None:
        """Persistence must be off — Redis is never capital state."""
        health = rds.check_health(settings.redis_url)
        assert health.is_usable, health.detail
        assert health.facts["save_policy"] == "disabled"

    def test_object_store_is_healthy_and_versioned(self, settings: Settings) -> None:
        """Versioning is what makes the raw archive effectively immutable."""
        health = obj.check_health_from_settings(settings)
        assert health.is_usable, health.detail
        assert health.facts["versioning"] == "Enabled"


class TestMigrations:
    def test_postgres_migrations_apply_and_are_idempotent(self, settings: Settings) -> None:
        with pg.connect(settings.postgres_dsn) as connection:
            runner = pg.build_runner(connection, directory=REPO_ROOT / pg.MIGRATION_DIRECTORY)
            runner.apply()
            assert runner.plan().is_empty

    def test_clickhouse_migrations_apply_and_are_idempotent(self, settings: Settings) -> None:
        with ch.connect_from_settings(settings) as client:
            runner = ch.build_runner(client, directory=REPO_ROOT / ch.MIGRATION_DIRECTORY)
            runner.apply()
            assert runner.plan().is_empty


class TestPostgresConstraints:
    """The constraints are the point — they must actually reject bad rows."""

    def test_audit_event_rejects_an_unknown_severity(self, settings: Settings) -> None:
        with pg.connect(settings.postgres_dsn) as connection:
            with connection.cursor() as cursor, pytest.raises(Exception, match="severity"):
                cursor.execute(
                    "INSERT INTO audit_events (event_id, event_type, occurred_at, "
                    "service, actor_type, correlation_id, severity) "
                    "VALUES (%s, 'test', now(), 'test', 'SYSTEM', 'cor_1', 'CHATTY')",
                    (str(uuid.uuid4()),),
                )
            connection.rollback()

    def test_audit_event_rejects_a_future_timestamp(self, settings: Settings) -> None:
        with pg.connect(settings.postgres_dsn) as connection:
            with connection.cursor() as cursor, pytest.raises(Exception, match="future"):
                cursor.execute(
                    "INSERT INTO audit_events (event_id, event_type, occurred_at, "
                    "service, actor_type, correlation_id, severity) "
                    "VALUES (%s, 'test', now() + INTERVAL '2 days', 'test', 'SYSTEM', "
                    "'cor_1', 'INFO')",
                    (str(uuid.uuid4()),),
                )
            connection.rollback()

    def test_gap_cannot_be_recovered_while_its_extent_is_unknown(self, settings: Settings) -> None:
        with pg.connect(settings.postgres_dsn) as connection:
            with connection.cursor() as cursor, pytest.raises(Exception, match="closed"):
                cursor.execute(
                    "INSERT INTO data_gaps (gap_id, source, venue, asset, event_type, "
                    "gap_start, detection_reason, backfill_status) "
                    "VALUES (%s, 'test', 'hyperliquid', 'BTC', 'TRADE', now(), "
                    "'test', 'RECOVERED')",
                    (str(uuid.uuid4()),),
                )
            connection.rollback()

    def test_gap_end_before_start_is_rejected(self, settings: Settings) -> None:
        with pg.connect(settings.postgres_dsn) as connection:
            with connection.cursor() as cursor, pytest.raises(Exception, match="ordered"):
                cursor.execute(
                    "INSERT INTO data_gaps (gap_id, source, venue, asset, event_type, "
                    "gap_start, gap_end, detection_reason) "
                    "VALUES (%s, 'test', 'hyperliquid', 'BTC', 'TRADE', now(), "
                    "now() - INTERVAL '1 hour', 'test')",
                    (str(uuid.uuid4()),),
                )
            connection.rollback()

    def test_dataset_manifest_rejects_a_non_pit_status_typo(self, settings: Settings) -> None:
        with pg.connect(settings.postgres_dsn) as connection:
            with connection.cursor() as cursor, pytest.raises(Exception, match="pit"):
                cursor.execute(
                    "INSERT INTO dataset_manifests (dataset_id, source, assets, "
                    "data_types, range_start, range_end, schema_version, "
                    "quality_status, pit_status, checksum, storage_uri) "
                    "VALUES (%s, 'test', ARRAY['BTC'], ARRAY['TRADE'], now(), now(), "
                    "1, 'VALID', 'PROBABLY_FINE', 'abc', 's3://x')",
                    (f"ds-{uuid.uuid4()}",),
                )
            connection.rollback()


class TestClickHouseSchema:
    def test_market_event_round_trips_with_exact_decimals(self, settings: Settings) -> None:
        """A float would lose the venue tick; Decimal must survive storage."""
        event_id = f"evt_{uuid.uuid4().hex}"
        with ch.connect_from_settings(settings) as client:
            client.insert(
                "market_events",
                [
                    [
                        event_id,
                        1,
                        "test",
                        "hyperliquid",
                        "BTC",
                        "BTC-PERP",
                        "TRADE",
                        datetime.now(UTC),
                        None,
                        datetime.now(UTC),
                        1_000,
                        datetime.now(UTC),
                        None,
                        "60000.12345678",
                        "0.00000001",
                        "BUY",
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        "raw://test",
                        "VALID",
                        "PIT_SAFE",
                    ]
                ],
                column_names=[
                    "event_id",
                    "schema_version",
                    "source",
                    "venue",
                    "asset",
                    "instrument",
                    "event_type",
                    "exchange_time",
                    "consensus_time",
                    "local_receive_time",
                    "local_receive_monotonic_ns",
                    "persist_time",
                    "sequence",
                    "price",
                    "quantity",
                    "side",
                    "bid_price",
                    "bid_quantity",
                    "ask_price",
                    "ask_quantity",
                    "funding_rate",
                    "open_interest",
                    "raw_reference",
                    "quality_status",
                    "pit_status",
                ],
            )
            rows = client.query(
                "SELECT price, quantity FROM market_events WHERE event_id = %(id)s",
                parameters={"id": event_id},
            ).result_rows
            assert len(rows) == 1
            assert str(rows[0][0]) == "60000.12345678"
            assert str(rows[0][1]) == "1E-8"
            client.command(
                "ALTER TABLE market_events DELETE WHERE event_id = %(id)s",
                parameters={"id": event_id},
            )

    def test_twap_slice_is_marked_excluded_from_skill_scoring(self, settings: Settings) -> None:
        """The exclusion rule lives in one place, not in every query."""
        base = [
            1,
            "test",
            "hyperliquid",
            "BTC",
            "BTC-PERP",
            "FILL",
            datetime.now(UTC),
            None,
            datetime.now(UTC),
            1_000,
            datetime.now(UTC),
            "0xwallet",
            "",
            "BUY",
            "60000",
            "0.1",
            "6000",
            "",
            "",
        ]
        plain_id = f"evt_{uuid.uuid4().hex}"
        twap_id_row = f"evt_{uuid.uuid4().hex}"
        columns = [
            "event_id",
            "schema_version",
            "source",
            "venue",
            "asset",
            "instrument",
            "event_type",
            "exchange_time",
            "consensus_time",
            "local_receive_time",
            "local_receive_monotonic_ns",
            "persist_time",
            "wallet",
            "counterparty",
            "side",
            "price",
            "quantity",
            "notional",
            "order_id",
            "client_order_id",
            "twap_id",
            "start_position",
            "end_position",
            "raw_reference",
            "quality_status",
            "pit_status",
        ]
        with ch.connect_from_settings(settings) as client:
            client.insert(
                "trader_events",
                [
                    [plain_id, *base, "", None, None, "raw://a", "VALID", "PIT_SAFE"],
                    [twap_id_row, *base, "twap-7", None, None, "raw://b", "VALID", "PIT_SAFE"],
                ],
                column_names=columns,
            )
            rows = client.query(
                "SELECT event_id, excluded_from_skill_scoring FROM trader_events "
                "WHERE event_id IN (%(a)s, %(b)s) ORDER BY excluded_from_skill_scoring",
                parameters={"a": plain_id, "b": twap_id_row},
            ).result_rows
            assert rows == [(plain_id, 0), (twap_id_row, 1)]
            client.command(
                "ALTER TABLE trader_events DELETE WHERE event_id IN (%(a)s, %(b)s)",
                parameters={"a": plain_id, "b": twap_id_row},
            )


class TestObjectStore:
    def test_raw_object_write_and_read_round_trips(self, settings: Settings) -> None:
        key = raw_key(source="test", channel="trades", date="2026-09-14", raw_id=uuid.uuid4().hex)
        payload = b'{"test": true}'
        with obj.connect_from_settings(settings) as client:
            client.put_object(Bucket=settings.object_store_bucket, Key=key, Body=payload)
            fetched = client.get_object(Bucket=settings.object_store_bucket, Key=key)["Body"].read()
            assert fetched == payload
            client.delete_object(Bucket=settings.object_store_bucket, Key=key)

    def test_overwriting_a_key_keeps_the_previous_version(self, settings: Settings) -> None:
        """Raw evidence must survive a rewrite (Phase 3 §17)."""
        key = raw_key(source="test", channel="trades", date="2026-09-14", raw_id=uuid.uuid4().hex)
        with obj.connect_from_settings(settings) as client:
            client.put_object(Bucket=settings.object_store_bucket, Key=key, Body=b"first")
            client.put_object(Bucket=settings.object_store_bucket, Key=key, Body=b"second")
            versions = client.list_object_versions(
                Bucket=settings.object_store_bucket, Prefix=key
            ).get("Versions", [])
            assert len(versions) == 2
            for version in versions:
                client.delete_object(
                    Bucket=settings.object_store_bucket,
                    Key=key,
                    VersionId=version["VersionId"],
                )


class TestRedis:
    def test_namespaced_key_round_trips(self, settings: Settings) -> None:
        key = rds.namespaced("test", uuid.uuid4().hex)
        with rds.connect(settings.redis_url) as client:
            client.set(key, "value", ex=60)
            assert client.get(key) == "value"
            client.delete(key)
