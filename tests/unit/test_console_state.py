"""What the product console is allowed to claim.

`apps/README.md` argues that designing product screens before the decision
object exists inverts the dependency and pressures the engine into producing
whatever a mockup promised. These tests are the guard against that: the console
may report that something does not exist, and may not render a value for it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.state import Availability, snapshot
from libs.config import load_settings


@pytest.fixture
def state() -> dict[str, Any]:
    return snapshot(load_settings())


class TestHonesty:
    def test_unbuilt_subsystems_are_labelled_not_blank(self, state: dict[str, Any]) -> None:
        """An empty positions table implies a system that could hold one."""
        by_name = {item["name"]: item for item in state["capabilities"]}
        assert by_name["Positions and P&L"]["availability"] == Availability.NOT_IMPLEMENTED
        assert by_name["Strategy"]["availability"] == Availability.NOT_IMPLEMENTED
        assert by_name["Risk Engine"]["availability"] == Availability.NOT_IMPLEMENTED

    def test_every_capability_explains_itself(self, state: dict[str, Any]) -> None:
        """A status with no reason is a status nobody can act on."""
        for item in state["capabilities"]:
            assert item["detail"], f"{item['name']} has no explanation"

    def test_no_capability_carries_a_fabricated_value(self, state: dict[str, Any]) -> None:
        """The state exposes availability and prose, never a number to render.

        A `pnl: 0` would be the exact failure this console exists to avoid: a
        plausible value for something that does not exist.
        """
        for item in state["capabilities"]:
            assert set(item) == {"name", "availability", "detail", "milestone"}


class TestSafetyReporting:
    def test_safety_comes_from_settings(self, state: dict[str, Any]) -> None:
        settings = load_settings()
        assert state["safety"]["trading_enabled"] == settings.trading_enabled
        assert state["safety"]["may_submit_orders"] == settings.may_submit_orders
        assert state["safety"]["venue_endpoint"] == settings.venue_endpoint

    def test_the_development_default_reaches_no_capital(self, state: dict[str, Any]) -> None:
        assert state["safety"]["reaches_real_capital"] is False
        assert state["safety"]["venue_endpoint"] is None
        assert state["safety"]["may_submit_orders"] is False


class TestModes:
    def test_autopilot_is_unavailable_not_merely_off(self, state: dict[str, Any]) -> None:
        """Off is a setting. Unavailable is the truth at this build stage."""
        autopilot = next(mode for mode in state["modes"] if mode["name"] == "Autopilot")
        assert autopilot["active"] is False
        assert autopilot["available"] is False

    def test_research_is_the_only_reachable_mode(self, state: dict[str, Any]) -> None:
        available = [mode["name"] for mode in state["modes"] if mode["available"]]
        assert available == ["Research"]


class TestAccountModel:
    def test_the_three_layers_stay_separate(self, state: dict[str, Any]) -> None:
        """Phase 9 §3: never presented as one indistinguishable object."""
        names = [layer["name"] for layer in state["account_layers"]]
        assert len(names) == 3
        assert any("User Wallet" in name for name in names)
        assert any("Trading Authorization" in name for name in names)
        assert any("Trading Account" in name for name in names)

    def test_the_wallet_layer_states_that_keys_never_reach_the_backend(
        self, state: dict[str, Any]
    ) -> None:
        """Invariant 18, stated where a user would look for it."""
        wallet = next(layer for layer in state["account_layers"] if "Wallet" in layer["name"])
        assert "never leave the wallet environment" in wallet["detail"]


class TestEmergencyControls:
    def test_the_controls_are_listed_even_while_inert(self, state: dict[str, Any]) -> None:
        """§56: a control that appears only when needed is unpractised."""
        names = [control["name"] for control in state["emergency_controls"]]
        assert "PAUSE AUTOPILOT" in names
        assert "CANCEL ENTRY ORDERS" in names
        assert "REDUCE EXPOSURE" in names

    def test_none_is_armed_because_none_has_anything_to_act_on(self, state: dict[str, Any]) -> None:
        assert all(not control["enabled"] for control in state["emergency_controls"])


class TestApi:
    def test_state_is_served(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/state")
        assert response.status_code == 200
        assert response.json()["safety"]["may_submit_orders"] is False

    def test_the_console_page_is_served(self) -> None:
        with TestClient(app) as client:
            response = client.get("/")
        assert response.status_code == 200
        assert "Smart Trading Wallet" in response.text

    def test_the_api_exposes_no_mutation(self) -> None:
        """Structural, not a phase to grow out of.

        The frontend is not an authorization boundary. An API with no endpoint
        that could enable trading cannot be talked into it by a compromised
        console.
        """
        methods = {method for route in app.routes for method in getattr(route, "methods", set())}
        assert methods <= {"GET", "HEAD"}, f"the console API accepts {methods}"
