"""ToolFactory — single source of truth for tool instantiation.

Usage:
    factory = ToolFactory()          # respects settings.mock_external_apis
    factory = ToolFactory(mock=True) # force mock mode (tests)
    tool = factory.get("search_flights")
"""

from __future__ import annotations

from importlib import import_module
from typing import NamedTuple

from app.config import settings
from app.tools.base import BaseTool


class _ToolEntry(NamedTuple):
    """Maps a logical tool name to its module file and real class name.

    The mock class is always ``"Mock" + cls`` by convention — enforced across
    all tools in ``app/tools/mock/`` and ``app/tools/real/``.
    """

    module: str  # module file under tools/{mock,real}/  e.g. "serpapi_tools"
    cls: str  # real class name                        e.g. "FlightSearchTool"


# Registry: logical tool name → (_ToolEntry)
# Mock class name is derived as  "Mock" + entry.cls  (see ToolFactory.get)
_REGISTRY: dict[str, _ToolEntry] = {
    "search_flights": _ToolEntry("serpapi_tools", "FlightSearchTool"),
    "search_hotels": _ToolEntry("serpapi_tools", "HotelSearchTool"),
    "search_transit": _ToolEntry("transit_tools", "TransitSearchTool"),
    "search_places": _ToolEntry("places_tools", "PlaceSearchTool"),
    "place_details": _ToolEntry("places_tools", "PlaceDetailsTool"),
    "tavily_search": _ToolEntry("tavily_tools", "TavilySearchTool"),
    "visa_centre_search": _ToolEntry("visa_tools", "VisaCentreSearchTool"),
    "embassy_search": _ToolEntry("visa_tools", "EmbassySearchTool"),
    "rental_search": _ToolEntry("rental_tools", "RentalSearchTool"),
    "fuel_price": _ToolEntry("rental_tools", "FuelPriceTool"),
    "cluster_by_proximity": _ToolEntry("geo_tools", "ClusterByProximityTool"),
    "distance_matrix": _ToolEntry("geo_tools", "DistanceMatrixTool"),
    "currency_convert": _ToolEntry("fx_tools", "CurrencyConvertTool"),
    "identify_hubs": _ToolEntry("hub_tools", "IdentifyHubsTool"),
}


class ToolFactory:
    def __init__(self, mock: bool | None = None) -> None:
        self._mock: bool = mock if mock is not None else settings.mock_external_apis

    @property
    def is_mock(self) -> bool:
        return self._mock

    def get(self, tool_name: str) -> BaseTool:
        if tool_name not in _REGISTRY:
            raise KeyError(f"Unknown tool '{tool_name}'. Valid names: {sorted(_REGISTRY)}")
        entry = _REGISTRY[tool_name]
        namespace = "mock" if self._mock else "real"
        cls_name = f"Mock{entry.cls}" if self._mock else entry.cls
        module = import_module(f"app.tools.{namespace}.{entry.module}")
        cls = getattr(module, cls_name)
        return cls()  # type: ignore[no-any-return]

    def all_names(self) -> list[str]:
        return list(_REGISTRY)
