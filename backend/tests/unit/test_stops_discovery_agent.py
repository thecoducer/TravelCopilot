"""Unit tests for StopsDiscoveryAgent — route/stop/leg identity and day allocation.

These tests cover route structuring only (per specs/stops-discovery-agent-spec.md
Phase 5 item 18): no Tavily, Google Places, geocoding, or route-distance checks.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.stops_discovery_agent import (
    StopsDiscoveryAgent,
    _GatewayOption,
    _Route,
    _Stop,
)
from app.graph.state import initial_state
from app.models.stops import SOURCE_STOP_ID, LegType
from app.models.user_profile import TripDates


def _make_llm(return_value: Any = None, side_effect: Exception | None = None) -> MagicMock:
    chain = MagicMock()
    if side_effect is not None:
        chain.ainvoke = AsyncMock(side_effect=side_effect)
    else:
        chain.ainvoke = AsyncMock(return_value=return_value)
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=chain)
    return llm


def _base_state(**overrides: Any) -> dict[str, Any]:
    state = {
        **initial_state(query="trip", session_id="s"),
        "source": "Kolkata",
        "destination": "Arunachal Pradesh",
        "dates": TripDates(departure=date(2026, 7, 1), return_date=date(2026, 7, 6)),  # 5 days
        "travelers": 2,
        "self_drive_intent": False,
    }
    state.update(overrides)
    return state


class TestSingleDestination:
    async def test_single_destination_status_produces_no_route_structure(self) -> None:
        route = _Route(route_discovery_status="single_destination")
        agent = StopsDiscoveryAgent(llm=_make_llm(route))

        result = await agent(_base_state(destination="Osaka"))

        assert result["route_discovery_status"] == "single_destination"
        assert result["stops"] == {}
        assert result["route_legs"] == {}
        assert result["stops_by_day"] == {}
        assert result["gateway_options"] == []

    async def test_missing_dates_defaults_to_single_destination_without_llm_call(self) -> None:
        llm = _make_llm(_Route(route_discovery_status="single_destination"))
        agent = StopsDiscoveryAgent(llm=llm)

        result = await agent(_base_state(dates=None))

        assert result["route_discovery_status"] == "single_destination"
        llm.with_structured_output.assert_not_called()


class TestMultiStopRouteShaping:
    def _route(self) -> _Route:
        return _Route(
            route_discovery_status="multi_stop_provisional",
            overnight_stops=[
                _Stop(name="Bhalukpong", nights_hint=1),
                _Stop(name="Dirang", nights_hint=1),
                _Stop(name="Tawang", nights_hint=1),
                _Stop(name="Dirang", nights_hint=1),
            ],
            gateway_options=[
                _GatewayOption(
                    option_id="gw_flight",
                    gateway_name="Fly via Guwahati",
                    gateway_stop=_Stop(name="Guwahati", stop_kind="gateway_transit"),
                    transit_duration_hours=2.0,
                    cost_tier="mid",
                    is_recommended=True,
                ),
            ],
        )

    async def test_repeated_stop_gets_distinct_stop_ids(self) -> None:
        agent = StopsDiscoveryAgent(llm=_make_llm(self._route()))
        result = await agent(_base_state())

        stop_ids = list(result["stops"].keys())
        dirang_ids = [sid for sid in stop_ids if sid.startswith("dirang")]
        assert len(dirang_ids) == 2
        assert dirang_ids[0] != dirang_ids[1]

    async def test_gateway_leg_types_assigned_correctly(self) -> None:
        agent = StopsDiscoveryAgent(llm=_make_llm(self._route()))
        result = await agent(_base_state())

        legs_by_type: dict[LegType, list[Any]] = {}
        for leg in result["route_legs"].values():
            legs_by_type.setdefault(leg.leg_type, []).append(leg)

        assert len(legs_by_type[LegType.SOURCE_TO_GATEWAY]) == 1
        assert len(legs_by_type[LegType.GATEWAY_TO_STOP]) == 1
        assert len(legs_by_type[LegType.STOP_TO_GATEWAY]) == 1
        assert len(legs_by_type[LegType.GATEWAY_TO_SOURCE]) == 1
        assert len(legs_by_type[LegType.INTERNAL_TRANSFER]) == 3  # 4 stops -> 3 transfers

        entry_leg = legs_by_type[LegType.SOURCE_TO_GATEWAY][0]
        assert entry_leg.origin_stop_id == SOURCE_STOP_ID
        exit_leg = legs_by_type[LegType.GATEWAY_TO_SOURCE][0]
        assert exit_leg.destination_stop_id == SOURCE_STOP_ID

    async def test_return_leg_anchored_at_last_overnight_stop(self) -> None:
        agent = StopsDiscoveryAgent(llm=_make_llm(self._route()))
        result = await agent(_base_state())

        overnight_ids = [
            sid for sid, stop in result["stops"].items() if stop.stop_kind == "overnight"
        ]
        last_stop_id = max(
            (result["stops"][sid] for sid in overnight_ids), key=lambda s: s.sequence
        ).stop_id

        stop_to_gateway = next(
            leg for leg in result["route_legs"].values() if leg.leg_type == LegType.STOP_TO_GATEWAY
        )
        assert stop_to_gateway.origin_stop_id == last_stop_id

    async def test_day_allocation_sums_to_trip_length(self) -> None:
        agent = StopsDiscoveryAgent(llm=_make_llm(self._route()))
        state = _base_state()
        result = await agent(state)

        trip_days = state["dates"].trip_days
        assert len(result["stops_by_day"]) == trip_days
        assert set(result["stops_by_day"].keys()) == set(range(trip_days))

        nights_total = sum(
            stop.nights for stop in result["stops"].values() if stop.stop_kind == "overnight"
        )
        assert nights_total == trip_days

    async def test_gateway_options_capped_and_one_recommended(self) -> None:
        route = self._route()
        route.gateway_options = [
            _GatewayOption(
                option_id=f"gw_{i}",
                gateway_name=f"Option {i}",
                gateway_stop=_Stop(name="Guwahati", stop_kind="gateway_transit"),
            )
            for i in range(5)
        ]
        agent = StopsDiscoveryAgent(llm=_make_llm(route))

        result = await agent(_base_state())

        from app.config import settings

        assert len(result["gateway_options"]) == settings.max_gateway_options
        assert sum(1 for g in result["gateway_options"] if g.is_recommended) == 1

    async def test_direct_gateway_when_first_stop_has_no_separate_transit(self) -> None:
        route = _Route(
            route_discovery_status="multi_stop_provisional",
            overnight_stops=[
                _Stop(name="Leh", nights_hint=3),
                _Stop(name="Nubra Valley", nights_hint=2),
            ],
            gateway_options=[
                _GatewayOption(
                    option_id="gw_direct",
                    gateway_name="Direct flight",
                    gateway_stop=_Stop(name="Leh", stop_kind="overnight"),
                    is_recommended=True,
                )
            ],
        )
        agent = StopsDiscoveryAgent(llm=_make_llm(route))

        result = await agent(_base_state(destination="Ladakh"))

        # No distinct gateway_transit stop — gateway coincides with the first overnight stop.
        gateway_stops = [s for s in result["stops"].values() if s.stop_kind == "gateway_transit"]
        assert gateway_stops == []
        leg_types = {leg.leg_type for leg in result["route_legs"].values()}
        assert LegType.GATEWAY_TO_STOP not in leg_types
        assert LegType.SOURCE_TO_GATEWAY in leg_types


class TestDiscoveryFailed:
    async def test_llm_exception_sets_discovery_failed(self) -> None:
        agent = StopsDiscoveryAgent(llm=_make_llm(side_effect=RuntimeError("boom")))

        result = await agent(_base_state())

        assert result["route_discovery_status"] == "discovery_failed"
        assert result["stops"] == {}

    async def test_route_version_increments_on_each_call(self) -> None:
        route = _Route(route_discovery_status="single_destination")
        agent = StopsDiscoveryAgent(llm=_make_llm(route))

        first = await agent(_base_state())
        second = await agent(_base_state(route_version=first["route_version"]))

        assert second["route_version"] == first["route_version"] + 1


if __name__ == "__main__":
    pytest.main([__file__])
