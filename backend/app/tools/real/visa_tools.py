"""Grounded visa-centre and embassy discovery tools."""

from __future__ import annotations

from typing import Any

from app.config import TOOL_RUNTIME_KEY
from app.services.external_api_client import ExternalAPIClient, get_external_api_client
from app.tools.real.places_tools import PlaceSearchTool
from app.tools.real.tavily_tools import TavilySearchTool


class VisaCentreSearchTool:
    name = "visa_centre_search"
    description = (
        "Discovers the correct visa application centre company for a corridor "
        "via Tavily, then fetches address/hours from Google Places."
    )

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        shared_client = client or get_external_api_client()
        self._tavily = TavilySearchTool(shared_client)
        self._places = PlaceSearchTool(shared_client)

    async def run(
        self,
        passport_country: str = "",
        destination_country: str = "",
        home_city: str = "",
        **kwargs: object,
    ) -> dict[str, Any]:
        query = (
            f"{passport_country} passport {destination_country} visa application centre "
            f"official operator in {home_city}"
        )
        research = await self._tavily.run(query=query, max_results=5)
        centre_query = f"visa application centre for {destination_country} in {home_city}"
        places = await self._places.run(location=home_city, query=centre_query)
        runtime = self._merge_runtime(research, places)
        sources = [
            {"title": item.get("title", ""), "url": item.get("url", "")}
            for item in research.get("results", [])
            if item.get("url")
        ]
        place = places.get("places", [{}])[0] if places.get("places") else None
        return {
            "application_centre": self._place_to_centre(place) if place else None,
            "sources": sources,
            "last_verified_at": runtime.get("fetched_at"),
            TOOL_RUNTIME_KEY: runtime,
        }

    def _place_to_centre(self, place: dict[str, Any]) -> dict[str, Any]:
        display_name = place.get("displayName", {})
        return {
            "name": display_name.get("text", place.get("name")),
            "address": place.get("formattedAddress"),
            "phone": place.get("nationalPhoneNumber"),
            "booking_url": place.get("websiteUri"),
            "website": place.get("websiteUri"),
            "google_maps_url": place.get("googleMapsUri"),
            "source": "google_places",
        }

    def _merge_runtime(self, research: dict[str, Any], places: dict[str, Any]) -> dict[str, Any]:
        research_runtime = research.pop(TOOL_RUNTIME_KEY, {})
        places_runtime = places.pop(TOOL_RUNTIME_KEY, {})
        return {
            "status": "success",
            "fetched_at": research_runtime.get("fetched_at"),
            "exchanges": research_runtime.get("exchanges", [])
            + places_runtime.get("exchanges", []),
            "retry_count": research_runtime.get("retry_count", 0)
            + places_runtime.get("retry_count", 0),
            "duration_ms": research_runtime.get("duration_ms", 0)
            + places_runtime.get("duration_ms", 0),
        }


class EmbassySearchTool:
    name = "embassy_search"
    description = "Finds nearest embassy/consulate via Google Places."

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        self._places = PlaceSearchTool(client or get_external_api_client())

    async def run(
        self,
        passport_country: str = "",
        destination_country: str = "",
        home_city: str = "",
        **kwargs: object,
    ) -> dict[str, Any]:
        result = await self._places.run(
            location=home_city,
            query=f"{destination_country} embassy or consulate in {home_city}",
        )
        runtime = result.pop(TOOL_RUNTIME_KEY, {})
        place = result.get("places", [{}])[0] if result.get("places") else None
        return {
            "embassy": self._place_to_embassy(place) if place else None,
            TOOL_RUNTIME_KEY: runtime,
        }

    def _place_to_embassy(self, place: dict[str, Any]) -> dict[str, Any]:
        display_name = place.get("displayName", {})
        return {
            "name": display_name.get("text", place.get("name")),
            "address": place.get("formattedAddress"),
            "phone": place.get("nationalPhoneNumber"),
            "website": place.get("websiteUri"),
            "google_maps_url": place.get("googleMapsUri"),
            "source": "google_places",
        }
