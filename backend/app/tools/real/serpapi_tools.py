"""Real SerpAPI tool stubs."""

from __future__ import annotations

from typing import Any


class FlightSearchTool:
    name = "search_flights"
    description = "Real flight search via SerpAPI google_flights engine."

    async def run(self, **kwargs: object) -> dict[str, Any]:
        raise NotImplementedError("FlightSearchTool requires SERPAPI_KEY — implement in Phase 5.")


class HotelSearchTool:
    name = "search_hotels"
    description = "Real hotel search via SerpAPI google_hotels engine."

    async def run(self, **kwargs: object) -> dict[str, Any]:
        raise NotImplementedError("HotelSearchTool requires SERPAPI_KEY — implement in Phase 5.")
