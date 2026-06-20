"""Mock transit search tool.

Returns data in Google Routes API format: {routes: [...]}
"""

from __future__ import annotations

from typing import Any

from app.tools.mock._helpers import find_fixture


class MockTransitSearchTool:
    name = "search_transit"
    description = "Mock transit search — Google Routes API format, no network calls."

    async def run(
        self, origin: str = "", destination: str = "", **kwargs: object
    ) -> dict[str, Any]:
        data = find_fixture("transit", origin, destination)
        if data is None:
            return {"routes": []}
        return data
