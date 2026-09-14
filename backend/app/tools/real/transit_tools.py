"""Google Routes API public-transit adapter."""

from __future__ import annotations

from typing import Any

from app.config import GOOGLE_TRAVEL_MODE_TRANSIT
from app.services.external_api_client import ExternalAPIClient, get_external_api_client
from app.tools.real.routes_helpers import GoogleRoutesClient, route_result


class TransitSearchTool:
    name = "search_transit"
    description = "Google Routes API routes for train, bus, and ferry legs."

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        self._routes = GoogleRoutesClient(client or get_external_api_client())

    async def run(
        self,
        origin: str = "",
        destination: str = "",
        mode: str = "transit",
        departure_date: str = "",
        **kwargs: object,
    ) -> dict[str, Any]:
        if not origin or not destination:
            return {"options": [], "source": "google_routes"}
        departure_time = f"{departure_date}T09:00:00Z" if departure_date else ""
        response = await self._routes.compute_route(
            origin, destination, GOOGLE_TRAVEL_MODE_TRANSIT, departure_time
        )
        return route_result(response, origin, destination, mode)
