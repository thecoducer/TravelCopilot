"""Real transit search tool stub."""

from __future__ import annotations

from typing import Any


class TransitSearchTool:
    name = "search_transit"
    description = "Real transit search via Google Routes API (TRANSIT mode)."

    async def run(self, **kwargs: object) -> dict[str, Any]:
        raise NotImplementedError(
            "TransitSearchTool requires GOOGLE_MAPS_API_KEY — implement in Phase 5."
        )
