"""Mock road routing tool."""

from __future__ import annotations

from typing import Any


class MockRoadRouteTool:
    name = "search_road_routes"
    description = "Mock driving route search for taxis and cabs, no network calls."

    async def run(
        self, origin: str = "", destination: str = "", **kwargs: object
    ) -> dict[str, Any]:
        return {
            "options": [
                {
                    "mode": "taxi",
                    "origin": origin,
                    "destination": destination,
                    "duration": "1800s",
                    "distanceMeters": 25000,
                    "description": f"Driving route from {origin} to {destination}",
                    "source": "mock_google_routes",
                }
            ]
            if origin and destination
            else [],
        }
