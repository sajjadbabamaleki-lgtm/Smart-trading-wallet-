"""Storage helpers that need no store: health rendering and key construction."""

from __future__ import annotations

import pytest

from libs.storage.health import StoreHealth, StoreStatus, check_all
from libs.storage.object_store import raw_key
from libs.storage.redis_store import namespaced


class TestStoreStatus:
    def test_only_healthy_is_usable(self) -> None:
        assert StoreStatus.HEALTHY.is_usable
        for status in (
            StoreStatus.DEGRADED,
            StoreStatus.UNREACHABLE,
            StoreStatus.MISCONFIGURED,
        ):
            assert not status.is_usable


class TestCheckAll:
    def test_every_check_runs_and_reports(self) -> None:
        results = check_all(
            {
                "a": lambda: StoreHealth(store="a", status=StoreStatus.HEALTHY),
                "b": lambda: StoreHealth(store="b", status=StoreStatus.DEGRADED),
            }
        )
        assert [r.store for r in results] == ["a", "b"]

    def test_a_raising_check_becomes_a_result_not_a_crash(self) -> None:
        """Aborting on the first failure would hide the state of the rest."""

        def explode() -> StoreHealth:
            raise ConnectionRefusedError("nothing listening")

        results = check_all(
            {
                "broken": explode,
                "fine": lambda: StoreHealth(store="fine", status=StoreStatus.HEALTHY),
            }
        )
        assert results[0].status is StoreStatus.UNREACHABLE
        assert "ConnectionRefusedError" in results[0].detail
        assert results[1].is_usable

    def test_rendering_includes_status_and_detail(self) -> None:
        health = StoreHealth(
            store="postgres",
            status=StoreStatus.DEGRADED,
            latency_ms=12.4,
            detail="persistence enabled",
        )
        rendered = health.render()
        assert "postgres" in rendered
        assert "degraded" in rendered
        assert "12ms" in rendered
        assert "persistence enabled" in rendered


class TestRedisKeys:
    def test_keys_are_namespaced(self) -> None:
        assert namespaced("recorder", "btc", "last_event") == "stw:recorder:btc:last_event"

    def test_empty_key_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one part"):
            namespaced()

    def test_empty_part_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            namespaced("recorder", "")

    def test_embedded_separator_is_refused(self) -> None:
        """Otherwise two different key structures collapse to one string."""
        with pytest.raises(ValueError, match="must not contain"):
            namespaced("recorder:btc")


class TestRawArchiveKeys:
    def test_key_is_date_partitioned(self) -> None:
        key = raw_key(source="hyperliquid", channel="trades", date="2026-09-14", raw_id="abc")
        assert key == "raw/hyperliquid/trades/2026-09-14/abc.json"

    def test_malformed_date_is_refused(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            raw_key(source="hyperliquid", channel="trades", date="14/09/2026", raw_id="abc")

    @pytest.mark.parametrize("field", ["source", "channel", "raw_id"])
    def test_path_separator_in_a_component_is_refused(self, field: str) -> None:
        """A '/' would silently restructure the archive layout."""
        kwargs = {
            "source": "hyperliquid",
            "channel": "trades",
            "date": "2026-09-14",
            "raw_id": "abc",
        }
        kwargs[field] = "a/b"
        with pytest.raises(ValueError, match="no '/'"):
            raw_key(**kwargs)

    @pytest.mark.parametrize("field", ["source", "channel", "raw_id"])
    def test_empty_component_is_refused(self, field: str) -> None:
        kwargs = {
            "source": "hyperliquid",
            "channel": "trades",
            "date": "2026-09-14",
            "raw_id": "abc",
        }
        kwargs[field] = ""
        with pytest.raises(ValueError, match="non-empty"):
            raw_key(**kwargs)
