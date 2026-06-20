"""Real visa tool stubs."""

from __future__ import annotations

from typing import Any


class VisaCentreSearchTool:
    name = "visa_centre_search"
    description = (
        "Discovers the correct visa application centre company for a corridor "
        "via Tavily, then fetches address/hours from Google Places."
    )

    async def run(self, **kwargs: object) -> dict[str, Any]:
        raise NotImplementedError(
            "VisaCentreSearchTool requires TAVILY_API_KEY + GOOGLE_PLACES_API_KEY"
            " — implement in Phase 5."
        )


class EmbassySearchTool:
    name = "embassy_search"
    description = "Finds nearest embassy/consulate via Google Places."

    async def run(self, **kwargs: object) -> dict[str, Any]:
        raise NotImplementedError(
            "EmbassySearchTool requires GOOGLE_PLACES_API_KEY — implement in Phase 5."
        )
