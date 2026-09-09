"""Mock taxi-operator discovery tool."""

from __future__ import annotations

from typing import Any


class MockTaxiInfoTool:
    name = "search_taxi_info"
    description = "Mock local taxi operator search, no network calls."

    async def run(
        self, location: str = "", destination: str = "", **kwargs: object
    ) -> dict[str, Any]:
        city = location or destination
        return {
            "options": [
                {
                    "name": f"{city} Taxi Services",
                    "location": city,
                    "phone": None,
                    "website": None,
                    "booking_url": None,
                    "source": "mock",
                }
            ]
            if city
            else [],
        }
