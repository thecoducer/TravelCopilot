"""Real rental and fuel price tool stubs."""

from __future__ import annotations

from typing import Any


class RentalSearchTool:
    name = "rental_search"
    description = "Real rental search via Google Places (car_rental type) + Tavily."

    async def run(self, **kwargs: object) -> dict[str, Any]:
        raise NotImplementedError(
            "RentalSearchTool requires GOOGLE_PLACES_API_KEY + TAVILY_API_KEY"
            " — implement in Phase 5."
        )


class FuelPriceTool:
    name = "fuel_price"
    description = "Real live fuel price via Tavily search."

    async def run(self, **kwargs: object) -> dict[str, Any]:
        raise NotImplementedError("FuelPriceTool requires TAVILY_API_KEY — implement in Phase 5.")
