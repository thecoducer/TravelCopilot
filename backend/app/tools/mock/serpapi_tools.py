"""Mock SerpAPI tools — flight and hotel search from fixtures.

Returns data in the same format as SerpAPI google_flights / google_hotels:
  flights: {best_flights: [...], other_flights: [...]}
  hotels:  {properties: [...]}
"""

from __future__ import annotations

from typing import Any

from app.tools.mock._helpers import find_fixture


class MockFlightSearchTool:
    name = "search_flights"
    description = "Mock flight search — SerpAPI google_flights format, no network calls."

    async def run(
        self, origin: str = "", destination: str = "", **kwargs: object
    ) -> dict[str, Any]:
        data = find_fixture("flights", origin, destination)
        if data is None:
            data = find_fixture("flights", origin, "")
        if data is None:
            return {"best_flights": [], "other_flights": []}
        return data


class MockHotelSearchTool:
    name = "search_hotels"
    description = "Mock hotel search — SerpAPI google_hotels format, no network calls."

    async def run(self, location: str = "", **kwargs: object) -> dict[str, Any]:
        data = find_fixture("hotels", location)
        if data is None:
            return {"properties": []}
        return data
