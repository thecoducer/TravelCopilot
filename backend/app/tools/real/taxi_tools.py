"""Taxi-operator discovery via Google Places API (New)."""

from __future__ import annotations

from typing import Any

from app.config import TOOL_RUNTIME_KEY
from app.services.external_api_client import ExternalAPIClient, get_external_api_client
from app.tools.real.places_tools import PlaceSearchTool


class TaxiInfoTool:
    name = "search_taxi_info"
    description = "Google Places search for taxi services and taxi stands."

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        self._places = PlaceSearchTool(client or get_external_api_client())

    async def run(
        self, location: str = "", destination: str = "", **kwargs: object
    ) -> dict[str, Any]:
        query_location = location or destination
        if not query_location:
            return {"options": [], "source": "google_places"}

        result = await self._places.run(
            location=query_location,
            query=f"taxi service in {query_location}",
            included_types=["taxi_stand"],
        )
        runtime = result.pop(TOOL_RUNTIME_KEY, {})
        options = []
        for place in result.get("places", []):
            options.append(
                {
                    "name": place.get("displayName", {}).get("text"),
                    "address": place.get("formattedAddress"),
                    "phone": place.get("nationalPhoneNumber"),
                    "website": place.get("websiteUri"),
                    "booking_url": place.get("websiteUri"),
                    "google_maps_url": place.get("googleMapsUri"),
                    "rating": place.get("rating"),
                    "review_count": place.get("userRatingCount"),
                    "source": "google_places",
                }
            )
        return {"options": options, "source": "google_places", TOOL_RUNTIME_KEY: runtime}
