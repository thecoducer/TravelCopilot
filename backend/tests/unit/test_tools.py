"""Unit tests for the tool factory, real adapters, and local tool logic."""

from __future__ import annotations

import pytest

from app.config import (
    TOOL_RESPONSE_STATUS_ERROR,
    TOOL_RUNTIME_KEY,
    TOOL_RUNTIME_STATUS_KEY,
)
from app.tools.base import BaseTool
from app.tools.factory import ToolFactory
from app.tools.real.geo_tools import ClusterByProximityTool


class TestToolFactory:
    def test_mock_mode_returns_replay_wrapper(self):
        factory = ToolFactory(mock=True)
        tool = factory.get("search_flights")
        assert factory.is_mock is True
        assert isinstance(tool, BaseTool)
        assert tool.name == "search_flights"
        assert tool.description
        assert callable(tool.run)

    def test_real_mode_returns_adapter_wrapper(self):
        factory = ToolFactory(mock=False)
        tool = factory.get("search_flights")
        assert factory.is_mock is False
        assert isinstance(tool, BaseTool)
        assert tool.name == "search_flights"
        assert tool.description
        assert callable(tool.run)

    def test_unknown_tool_raises_key_error(self):
        with pytest.raises(KeyError):
            ToolFactory(mock=True).get("nonexistent_tool")

    def test_all_replay_tools_instantiable(self):
        factory = ToolFactory(mock=True)
        for name in factory.all_names():
            tool = factory.get(name)
            assert isinstance(tool, BaseTool)
            assert tool.name == name
            assert tool.description
            assert callable(tool.run)

    def test_all_real_adapters_instantiable(self):
        factory = ToolFactory(mock=False)
        for name in factory.all_names():
            tool = factory.get(name)
            assert isinstance(tool, BaseTool)
            assert tool.name == name


class TestReplayMissingRecording:
    @pytest.mark.asyncio
    async def test_missing_recording_returns_typed_error(self):
        result = (
            await ToolFactory(mock=True)
            .get("search_flights")
            .run(
                origin="missing-origin",
                destination="missing-destination",
                departure_date="2099-01-01",
            )
        )
        assert result["error"]["type"] == "missing_recording"
        assert result["_meta"]["status"] == TOOL_RESPONSE_STATUS_ERROR


class TestRealAdapters:
    @pytest.mark.asyncio
    async def test_flight_invalid_request_returns_typed_error(self):
        from app.tools.real.serpapi_tools import FlightSearchTool

        result = await FlightSearchTool().run()
        assert result[TOOL_RUNTIME_KEY][TOOL_RUNTIME_STATUS_KEY] == TOOL_RESPONSE_STATUS_ERROR

    @pytest.mark.asyncio
    async def test_hotel_invalid_request_returns_typed_error(self):
        from app.tools.real.serpapi_tools import HotelSearchTool

        result = await HotelSearchTool().run()
        assert result[TOOL_RUNTIME_KEY][TOOL_RUNTIME_STATUS_KEY] == TOOL_RESPONSE_STATUS_ERROR

    @pytest.mark.asyncio
    async def test_tavily_invalid_request_returns_typed_error(self):
        from app.tools.real.tavily_tools import TavilySearchTool

        result = await TavilySearchTool().run()
        assert result[TOOL_RUNTIME_KEY][TOOL_RUNTIME_STATUS_KEY] == TOOL_RESPONSE_STATUS_ERROR

    @pytest.mark.asyncio
    async def test_fx_invalid_request_returns_typed_error(self):
        from app.tools.real.fx_tools import CurrencyConvertTool

        result = await CurrencyConvertTool().run()
        assert result[TOOL_RUNTIME_KEY][TOOL_RUNTIME_STATUS_KEY] == TOOL_RESPONSE_STATUS_ERROR

    @pytest.mark.asyncio
    async def test_distance_matrix_invalid_request_returns_typed_error(self):
        from app.tools.real.geo_tools import DistanceMatrixTool

        result = await DistanceMatrixTool().run()
        assert result[TOOL_RUNTIME_KEY][TOOL_RUNTIME_STATUS_KEY] == TOOL_RESPONSE_STATUS_ERROR

    @pytest.mark.asyncio
    async def test_geocode_invalid_request_returns_typed_error(self):
        from app.tools.real.geo_tools import GeocodeTool

        result = await GeocodeTool().run()
        assert result[TOOL_RUNTIME_KEY][TOOL_RUNTIME_STATUS_KEY] == TOOL_RESPONSE_STATUS_ERROR


class TestClusterByProximityTool:
    @pytest.mark.asyncio
    async def test_clusters_3_groups(self):
        experiences = (
            [{"lat": 35.6, "lng": 139.7, "name": f"Tokyo-{i}"} for i in range(4)]
            + [{"lat": 19.0, "lng": 72.8, "name": f"Mumbai-{i}"} for i in range(4)]
            + [{"lat": 51.5, "lng": -0.12, "name": f"London-{i}"} for i in range(4)]
        )
        result = await ClusterByProximityTool().run(experiences=experiences, num_clusters=3)
        assert "clusters" in result
        assert len(result["clusters"]) == 3

    @pytest.mark.asyncio
    async def test_total_experiences_preserved(self):
        experiences = [
            {"lat": 35.6 + i * 0.01, "lng": 139.7 + i * 0.01, "name": f"P{i}"} for i in range(9)
        ]
        result = await ClusterByProximityTool().run(experiences=experiences, num_clusters=3)
        total = sum(len(cluster["experiences"]) for cluster in result["clusters"])
        assert total == 9

    @pytest.mark.asyncio
    async def test_k_capped_at_len(self):
        experiences = [{"lat": 35.0, "lng": 139.0, "name": "only"}]
        result = await ClusterByProximityTool().run(experiences=experiences, num_clusters=5)
        assert len(result["clusters"]) == 1

    @pytest.mark.asyncio
    async def test_empty_input(self):
        result = await ClusterByProximityTool().run(experiences=[], num_clusters=3)
        assert result["clusters"] == []
