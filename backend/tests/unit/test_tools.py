"""Unit tests for tools — ToolFactory, mock tools, real stubs, ClusterByProximityTool."""

from __future__ import annotations

import pytest

from app.tools.factory import ToolFactory
from app.tools.mock.fx_tools import MockCurrencyConvertTool
from app.tools.mock.geo_tools import MockClusterByProximityTool
from app.tools.mock.hub_tools import MockIdentifyHubsTool
from app.tools.mock.serpapi_tools import MockFlightSearchTool, MockHotelSearchTool
from app.tools.mock.tavily_tools import MockTavilySearchTool
from app.tools.mock.visa_tools import MockVisaCentreSearchTool
from app.tools.real.geo_tools import ClusterByProximityTool

# ── ToolFactory ─────────────────────────────────────────────────────────────


class TestToolFactory:
    def test_mock_flight_returns_correct_type(self):
        factory = ToolFactory(mock=True)
        tool = factory.get("search_flights")
        assert isinstance(tool, MockFlightSearchTool)

    def test_mock_hotel_returns_correct_type(self):
        factory = ToolFactory(mock=True)
        tool = factory.get("search_hotels")
        assert isinstance(tool, MockHotelSearchTool)

    def test_real_mode_returns_real_type(self):
        from app.tools.real.serpapi_tools import FlightSearchTool

        factory = ToolFactory(mock=False)
        tool = factory.get("search_flights")
        assert isinstance(tool, FlightSearchTool)

    def test_unknown_tool_raises_key_error(self):
        factory = ToolFactory(mock=True)
        with pytest.raises(KeyError):
            factory.get("nonexistent_tool")

    def test_all_mock_tools_instantiable(self):
        factory = ToolFactory(mock=True)
        for name in factory.all_names():
            tool = factory.get(name)
            assert hasattr(tool, "name")
            assert hasattr(tool, "description")
            assert callable(getattr(tool, "run", None))

    def test_all_real_stubs_instantiable(self):
        factory = ToolFactory(mock=False)
        for name in factory.all_names():
            tool = factory.get(name)
            assert hasattr(tool, "name")


# ── Mock tool run() correctness ─────────────────────────────────────────────


class TestMockFlightSearch:
    @pytest.mark.asyncio
    async def test_kolkata_leh_returns_flights(self):
        tool = MockFlightSearchTool()
        result = await tool.run(origin="kolkata", destination="leh")
        # SerpAPI format: best_flights or other_flights
        assert "best_flights" in result or "other_flights" in result
        all_flights = result.get("best_flights", []) + result.get("other_flights", [])
        assert len(all_flights) >= 1

    @pytest.mark.asyncio
    async def test_unknown_route_returns_empty(self):
        tool = MockFlightSearchTool()
        result = await tool.run(origin="zzz", destination="yyy")
        # Falls back to first available fixture or returns empty — both valid
        assert "best_flights" in result or "other_flights" in result

    @pytest.mark.asyncio
    async def test_flight_has_required_fields(self):
        tool = MockFlightSearchTool()
        result = await tool.run(origin="kolkata", destination="leh")
        all_options = result.get("best_flights", []) + result.get("other_flights", [])
        assert len(all_options) >= 1
        option = all_options[0]
        # Each option has flights (legs) and price
        assert "flights" in option
        assert "price" in option
        assert "total_duration" in option
        leg = option["flights"][0]
        fields = (
            "airline",
            "departure_airport",
            "arrival_airport",
            "duration",
            "flight_number",
            "travel_class",
        )
        for field in fields:
            assert field in leg, f"Missing flight leg field: {field}"


class TestMockHotelSearch:
    @pytest.mark.asyncio
    async def test_leh_returns_hotels(self):
        tool = MockHotelSearchTool()
        result = await tool.run(location="leh")
        # SerpAPI format: properties array
        assert "properties" in result
        assert len(result["properties"]) >= 5

    @pytest.mark.asyncio
    async def test_hotel_has_required_fields(self):
        tool = MockHotelSearchTool()
        result = await tool.run(location="leh")
        hotel = result["properties"][0]
        assert "name" in hotel
        assert "rate_per_night" in hotel
        assert "extracted_lowest" in hotel["rate_per_night"]
        assert hotel["rate_per_night"]["extracted_lowest"] > 0
        assert "overall_rating" in hotel
        assert "gps_coordinates" in hotel
        assert "latitude" in hotel["gps_coordinates"]


class TestMockTavilySearch:
    @pytest.mark.asyncio
    async def test_scam_query_returns_results(self):
        tool = MockTavilySearchTool()
        result = await tool.run(query="scams in Leh Ladakh", destination="Leh")
        # Real Tavily format: results array
        assert "results" in result
        assert len(result["results"]) >= 1
        first = result["results"][0]
        assert "title" in first
        assert "url" in first
        assert "content" in first

    @pytest.mark.asyncio
    async def test_unknown_intent_returns_fallback(self):
        tool = MockTavilySearchTool()
        result = await tool.run(query="random query about destination", destination="Paris")
        assert "results" in result
        assert "answer" in result


class TestMockVisaCentreTool:
    @pytest.mark.asyncio
    async def test_india_portugal_returns_centre(self):
        tool = MockVisaCentreSearchTool()
        result = await tool.run(
            passport_country="india",
            destination_country="portugal",
            home_city="Mumbai",
        )
        assert "application_centre" in result
        centre = result["application_centre"]
        assert centre is not None
        assert centre.get("name") != ""

    @pytest.mark.asyncio
    async def test_sources_present_g(self):
        tool = MockVisaCentreSearchTool()
        result = await tool.run(passport_country="india", destination_country="portugal")
        assert "sources" in result
        assert len(result["sources"]) >= 1
        assert "last_verified_at" in result


class TestMockFxTool:
    @pytest.mark.asyncio
    async def test_jpy_to_inr_conversion(self):
        tool = MockCurrencyConvertTool()
        result = await tool.run(amount=10000, base="JPY", quote="INR")
        assert result["amount_converted"] > 0
        assert result["rate"] > 0
        assert result["fetched_at"] != ""

    @pytest.mark.asyncio
    async def test_same_currency_is_identity(self):
        tool = MockCurrencyConvertTool()
        result = await tool.run(amount=500, base="INR", quote="INR")
        assert result["amount_converted"] == 500
        assert result["rate"] == 1.0

    @pytest.mark.asyncio
    async def test_reverse_lookup(self):
        tool = MockCurrencyConvertTool()
        # INR→JPY should work even if only JPY→INR is in fixture
        result = await tool.run(amount=1000, base="INR", quote="JPY")
        assert result["amount_converted"] > 0


class TestMockHubTool:
    @pytest.mark.asyncio
    async def test_kol_leh_returns_combinations(self):
        tool = MockIdentifyHubsTool()
        result = await tool.run(origin="KOL", destination="LEH")
        assert "route_combinations" in result
        combos = result["route_combinations"]
        assert len(combos) >= 2  # at least direct + via hub

    @pytest.mark.asyncio
    async def test_unknown_route_fallback(self):
        tool = MockIdentifyHubsTool()
        result = await tool.run(origin="ABC", destination="XYZ")
        assert len(result["route_combinations"]) >= 1


class TestMockClusterTool:
    @pytest.mark.asyncio
    async def test_returns_clusters(self):
        tool = MockClusterByProximityTool()
        experiences = [
            {"name": f"Place {i}", "lat": 34.6 + i * 0.01, "lng": 135.5 + i * 0.01}
            for i in range(6)
        ]
        result = await tool.run(experiences=experiences, num_clusters=2)
        assert "clusters" in result
        assert len(result["clusters"]) == 2

    @pytest.mark.asyncio
    async def test_empty_input(self):
        tool = MockClusterByProximityTool()
        result = await tool.run(experiences=[], num_clusters=3)
        assert result["clusters"] == []


# ── Real tool stubs ────────────────────────────────────────────────────────-


class TestRealToolStubs:
    @pytest.mark.asyncio
    async def test_real_flight_raises(self):
        from app.tools.real.serpapi_tools import FlightSearchTool

        with pytest.raises(NotImplementedError):
            await FlightSearchTool().run()

    @pytest.mark.asyncio
    async def test_real_hotel_raises(self):
        from app.tools.real.serpapi_tools import HotelSearchTool

        with pytest.raises(NotImplementedError):
            await HotelSearchTool().run()

    @pytest.mark.asyncio
    async def test_real_tavily_raises(self):
        from app.tools.real.tavily_tools import TavilySearchTool

        with pytest.raises(NotImplementedError):
            await TavilySearchTool().run()

    @pytest.mark.asyncio
    async def test_real_fx_raises(self):
        from app.tools.real.fx_tools import CurrencyConvertTool

        with pytest.raises(NotImplementedError):
            await CurrencyConvertTool().run()

    @pytest.mark.asyncio
    async def test_real_distance_matrix_raises(self):
        from app.tools.real.geo_tools import DistanceMatrixTool

        with pytest.raises(NotImplementedError):
            await DistanceMatrixTool().run()


# ── Real ClusterByProximityTool (pure math — fully implemented) ─────────────


class TestClusterByProximityTool:
    @pytest.mark.asyncio
    async def test_clusters_3_groups(self):
        # Three very well-separated groups (Japan, India, UK) → k-means must split them
        experiences = (
            [{"lat": 35.6, "lng": 139.7, "name": f"Tokyo-{i}"} for i in range(4)]
            + [{"lat": 19.0, "lng": 72.8, "name": f"Mumbai-{i}"} for i in range(4)]
            + [{"lat": 51.5, "lng": -0.12, "name": f"London-{i}"} for i in range(4)]
        )
        tool = ClusterByProximityTool()
        result = await tool.run(experiences=experiences, num_clusters=3)
        assert "clusters" in result
        assert len(result["clusters"]) == 3

    @pytest.mark.asyncio
    async def test_total_experiences_preserved(self):
        experiences = [
            {"lat": 35.6 + i * 0.01, "lng": 139.7 + i * 0.01, "name": f"P{i}"} for i in range(9)
        ]
        tool = ClusterByProximityTool()
        result = await tool.run(experiences=experiences, num_clusters=3)
        total = sum(len(c["experiences"]) for c in result["clusters"])
        assert total == 9

    @pytest.mark.asyncio
    async def test_k_capped_at_len(self):
        experiences = [{"lat": 35.0, "lng": 139.0, "name": "only"}]
        tool = ClusterByProximityTool()
        result = await tool.run(experiences=experiences, num_clusters=5)
        assert len(result["clusters"]) == 1

    @pytest.mark.asyncio
    async def test_empty_input(self):
        tool = ClusterByProximityTool()
        result = await tool.run(experiences=[], num_clusters=3)
        assert result["clusters"] == []
