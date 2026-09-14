"""Google Routes API road-routing adapter."""

from __future__ import annotations

from typing import Any

from app.config import GOOGLE_TRAVEL_MODE_DRIVE
from app.services.external_api_client import ExternalAPIClient, get_external_api_client
from app.tools.real.routes_helpers import GoogleRoutesClient, route_result


class RoadRouteTool:
    name = "search_road_routes"
    description = "Google Routes API driving routes for taxi and cab legs."

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        self._routes = GoogleRoutesClient(client or get_external_api_client())

    async def run(
        self, origin: str = "", destination: str = "", **kwargs: object
    ) -> dict[str, Any]:
        if not origin or not destination:
            return {"options": [], "source": "google_routes"}

        departure_date = kwargs.get("departure_date")
        departure_time = f"{departure_date}T09:00:00Z" if departure_date else ""
        response = await self._routes.compute_route(
            origin, destination, GOOGLE_TRAVEL_MODE_DRIVE, departure_time
        )
        return route_result(response, origin, destination, "taxi")
