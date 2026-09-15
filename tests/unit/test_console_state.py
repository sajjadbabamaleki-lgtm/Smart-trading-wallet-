"""The mobile app's backing state.

Five screens: Home, Wallet, Trade, Swap, Account. The rules that matter are
that the API cannot move anything, and that balances are not invented while no
wallet is connected.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.data import app_state
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


class TestLimits:
    def test_the_position_limit_is_the_configured_one(self, state: dict[str, Any]) -> None:
        """The screen shows a limit the engine actually enforces."""
        assert state["max_order_notional"] == float(load_settings().max_order_notional)


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
        for name in ("home", "wallet", "trade", "swap", "account"):
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
