"""The mobile app's backing state.

Five screens: Home, Trade, Positions, Wallet, Account. The rules come from
Phase 9 rather than from taste: the mode is always stated (§23), the four money
figures stay apart (§76), the health of what trading depends on is part of the
state (§51), and the API cannot move anything (Invariant 4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.data import app_state, history
from apps.api.main import app
from libs.config import load_settings


@pytest.fixture
def state() -> dict[str, Any]:
    return app_state(load_settings())


class TestWallet:
    def test_no_wallet_is_connected(self, state: dict[str, Any]) -> None:
        """No adapter exists, so the app is in the ordinary pre-connect state."""
        assert state["wallet"]["connected"] is False
        assert state["wallet"]["address"] is None

    def test_no_balances_are_invented(self, state: dict[str, Any]) -> None:
        """A disconnected wallet has no balances to show, not balances of zero."""
        assert state["wallet"]["balances"] == []
        assert state["wallet"]["balance_usd"] is None

    def test_no_trading_authorization_is_claimed(self, state: dict[str, Any]) -> None:
        """§19: the scope of what the platform may do is not implied, it is stated."""
        assert state["authorization"]["granted"] is False
        assert state["authorization"]["scope"] is None


class TestMarket:
    def test_market_state_says_whether_it_is_available(self, state: dict[str, Any]) -> None:
        """An unreachable store must not become a price."""
        market = state["market"]
        assert "available" in market
        if not market["available"]:
            assert market["reason"]
            assert "mid" not in market
        else:
            assert market["mid"] > 0
            assert market["bid"] <= market["ask"]
            # §67-adjacent: a price the recorder caught minutes ago is not the
            # market, and the screen is told which it is holding.
            assert isinstance(market["stale"], bool)
            assert market["age_seconds"] >= 0


class FakeQuery:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.result_rows = rows


class FakeClient:
    """Stands in for ClickHouse so the chart's rules can be tested without it."""

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.parameters: dict[str, object] | None = None

    def query(self, sql: str, parameters: dict[str, object] | None = None) -> FakeQuery:  # noqa: ARG002
        self.parameters = parameters
        return FakeQuery(self.rows)


class TestPriceHistory:
    def test_a_series_is_returned_when_there_is_something_to_draw(self) -> None:
        client = FakeClient([(60_000.0,), (60_100.0,), (59_900.0,)])
        assert history(client) == [60_000.0, 60_100.0, 59_900.0]

    def test_one_point_is_not_a_chart(self) -> None:
        """A line through a single observation claims the market held still."""
        assert history(FakeClient([(60_000.0,)])) is None

    def test_no_points_is_not_a_chart(self) -> None:
        assert history(FakeClient([])) is None

    def test_empty_buckets_are_dropped(self) -> None:
        client = FakeClient([(60_000.0,), (None,), (60_050.0,)])
        assert history(client) == [60_000.0, 60_050.0]

    def test_the_window_comes_from_our_clock_not_the_store_s(self) -> None:
        """`now()` is the store's clock, and on the recording host it runs two
        hours ahead of the timestamps the recorder writes — which emptied every
        window. The cutoff is a value we compute and send."""
        client = FakeClient([(1.0,), (2.0,)])
        history(client, hours=3, bucket_minutes=10)
        assert client.parameters is not None
        assert client.parameters["bucket"] == 10
        cutoff = client.parameters["cutoff"]
        assert isinstance(cutoff, datetime)
        assert cutoff.tzinfo is not None
        elapsed = (datetime.now(UTC) - cutoff).total_seconds()
        assert 3 * 3600 - 5 < elapsed < 3 * 3600 + 5


class TestMode:
    def test_the_mode_is_always_stated(self, state: dict[str, Any]) -> None:
        """§23: nobody should have to wonder whether the system can trade."""
        mode = state["mode"]
        assert mode["name"] in {"research", "copilot", "autopilot"}
        assert mode["label"]
        assert mode["reason"]

    def test_a_build_that_cannot_submit_orders_is_research_only(
        self, state: dict[str, Any]
    ) -> None:
        """The banner is derived from the same conjunction the executor obeys."""
        settings = load_settings()
        if not settings.may_submit_orders:
            assert state["mode"]["name"] == "research"

    def test_autopilot_is_never_claimed_without_a_grant(self, state: dict[str, Any]) -> None:
        """§25: Autopilot is a separate grant with nine preconditions."""
        assert state["mode"]["name"] != "autopilot"


class TestMoneyFiguresStayApart:
    def test_the_four_figures_are_separate_fields(self, state: dict[str, Any]) -> None:
        """§76: wallet balance, equity, margin and capital at risk are not one number."""
        account = state["account"]
        for field in ("trading_equity", "available_margin", "capital_at_risk"):
            assert field in account
        assert "balance_usd" in state["wallet"]

    def test_an_unauthorized_account_has_no_figures_not_zeroes(self, state: dict[str, Any]) -> None:
        """Zero would read as a funded account holding nothing."""
        account = state["account"]
        assert account["trading_equity"] is None
        assert account["available_margin"] is None
        assert account["reason"]


class TestHealth:
    def test_health_reports_what_trading_depends_on(self, state: dict[str, Any]) -> None:
        """§51: the state says whether the things trading needs are up."""
        health = state["health"]
        assert health["market_data"] in {"ok", "unavailable"}
        assert health["kill_switch"] in {"engaged", "released"}

    def test_the_kill_switch_reading_matches_settings(self, state: dict[str, Any]) -> None:
        engaged = state["health"]["kill_switch"] == "engaged"
        assert engaged is not load_settings().trading_enabled


class TestLimits:
    def test_the_position_limit_is_the_configured_one(self, state: dict[str, Any]) -> None:
        """The screen shows a limit the engine actually enforces."""
        assert state["limits"]["max_order_notional"] == float(load_settings().max_order_notional)


class TestSafety:
    def test_trading_state_comes_from_settings(self, state: dict[str, Any]) -> None:
        settings = load_settings()
        assert state["trading_enabled"] == settings.trading_enabled
        assert state["can_submit_orders"] == settings.may_submit_orders

    def test_the_default_build_cannot_submit_orders(self, state: dict[str, Any]) -> None:
        assert state["can_submit_orders"] is False


class TestApi:
    def test_state_is_served(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/app")
        assert response.status_code == 200
        assert response.json()["wallet"]["connected"] is False

    def test_the_app_is_served(self) -> None:
        with TestClient(app) as client:
            page = client.get("/")
        assert page.status_code == 200
        assert "Smart Trading Wallet" in page.text

    def test_the_app_has_exactly_five_tabs(self) -> None:
        with TestClient(app) as client:
            page = client.get("/").text
        for name in ("home", "trade", "positions", "wallet", "account"):
            assert f'data-tab="{name}"' in page
        assert page.count("data-tab=") == 5

    def test_the_api_cannot_move_anything(self) -> None:
        """Invariant 4: the frontend is not an authorization boundary.

        There is no endpoint that could place an order, swap, or transfer, so a
        compromised client cannot reach funds by asking. Those arrive as
        separately authorized endpoints once the Risk Engine bounds them.
        """
        methods = {method for route in app.routes for method in getattr(route, "methods", set())}
        assert methods <= {"GET", "HEAD"}, f"the app API accepts {methods}"
