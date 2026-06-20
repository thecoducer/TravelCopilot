"""Real Google Places tool stubs."""

from __future__ import annotations

from typing import Any


class PlaceSearchTool:
    name = "search_places"
    description = "Real Places Text Search via Google Places API."

    async def run(self, **kwargs: object) -> dict[str, Any]:
        raise NotImplementedError(
            "PlaceSearchTool requires GOOGLE_PLACES_API_KEY — implement in Phase 5."
        )


class PlaceDetailsTool:
    name = "place_details"
    description = "Real Place Details via Google Places Details API."

    async def run(self, **kwargs: object) -> dict[str, Any]:
        raise NotImplementedError(
            "PlaceDetailsTool requires GOOGLE_PLACES_API_KEY — implement in Phase 5."
        )
