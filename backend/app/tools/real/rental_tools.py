"""Grounded vehicle rental and fuel-price tools."""

from __future__ import annotations

from typing import Any

from app.config import TOOL_RUNTIME_KEY
from app.services.external_api_client import ExternalAPIClient, get_external_api_client
from app.tools.real.places_tools import PlaceSearchTool
from app.tools.real.tavily_tools import TavilySearchTool


class RentalSearchTool:
    name = "rental_search"
    description = "Real rental search via Google Places (car_rental type) + Tavily."

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        shared_client = client or get_external_api_client()
        self._places = PlaceSearchTool(shared_client)
        self._tavily = TavilySearchTool(shared_client)

    async def run(
        self,
        destination: str = "",
        vehicle_type: str = "",
        **kwargs: object,
    ) -> dict[str, Any]:
        places = await self._places.run(
            location=destination,
            query=f"{vehicle_type or 'vehicle'} rental in {destination}",
            included_types=["car_rental"],
        )
        research = await self._tavily.run(
            query=f"{vehicle_type or 'vehicle'} rental prices and providers in {destination}",
            max_results=5,
        )
        place_rentals = [self._place_to_rental(place) for place in places.get("places", [])]
        web_rentals = [
            self._result_to_rental(item, destination) for item in research.get("results", [])
        ]
        runtime = self._merge_runtime(places, research)
        return {"rentals": [*place_rentals, *web_rentals], TOOL_RUNTIME_KEY: runtime}

    def _place_to_rental(self, place: dict[str, Any]) -> dict[str, Any]:
        display_name = place.get("displayName", {})
        return {
            "name": display_name.get("text", place.get("name")),
            "address": place.get("formattedAddress"),
            "type": "vehicle_rental",
            "booking_url": place.get("websiteUri"),
            "source": "google_places",
            "bookable": False,
        }

    def _result_to_rental(self, result: dict[str, Any], destination: str) -> dict[str, Any]:
        return {
            "name": result.get("title"),
            "address": destination,
            "description": result.get("content"),
            "booking_url": result.get("url"),
            "source": "tavily",
            "bookable": False,
        }

    def _merge_runtime(self, places: dict[str, Any], research: dict[str, Any]) -> dict[str, Any]:
        places_runtime = places.pop(TOOL_RUNTIME_KEY, {})
        research_runtime = research.pop(TOOL_RUNTIME_KEY, {})
        return {
            "status": "success",
            "exchanges": places_runtime.get("exchanges", [])
            + research_runtime.get("exchanges", []),
            "retry_count": places_runtime.get("retry_count", 0)
            + research_runtime.get("retry_count", 0),
            "duration_ms": places_runtime.get("duration_ms", 0)
            + research_runtime.get("duration_ms", 0),
        }


class FuelPriceTool:
    name = "fuel_price"
    description = "Real live fuel price via Tavily search."

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        self._tavily = TavilySearchTool(client or get_external_api_client())

    async def run(
        self,
        destination: str = "",
        fuel_type: str = "petrol",
        currency: str = "",
        **kwargs: object,
    ) -> dict[str, Any]:
        result = await self._tavily.run(
            query=f"current {fuel_type} fuel price in {destination} {currency}".strip(),
            max_results=5,
        )
        runtime = result.pop(TOOL_RUNTIME_KEY, {})
        sources = [item.get("url") for item in result.get("results", []) if item.get("url")]
        return {
            "destination": destination,
            "fuel_type": fuel_type,
            "price_per_litre": None,
            "currency_code": currency or None,
            "available": False,
            "sources": sources,
            TOOL_RUNTIME_KEY: runtime,
        }
