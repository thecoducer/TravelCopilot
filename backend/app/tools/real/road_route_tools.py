"""Google Routes API road-routing adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.config import settings


class RoadRouteTool:
    name = "search_road_routes"
    description = "Google Routes API driving routes for taxi and cab legs."

    async def run(
        self, origin: str = "", destination: str = "", **kwargs: object
    ) -> dict[str, Any]:
        if not origin or not destination:
            return {"options": [], "source": "google_routes"}

        payload: dict[str, Any] = {
            "origin": {"address": origin},
            "destination": {"address": destination},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "computeAlternativeRoutes": True,
        }
        departure_date = kwargs.get("departure_date")
        if departure_date:
            payload["departureTime"] = f"{departure_date}T09:00:00Z"

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.google_maps_api_key,
            "X-Goog-FieldMask": (
                "routes.duration,routes.distanceMeters,routes.description,routes.legs"
            ),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://routes.googleapis.com/directions/v2:computeRoutes",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        options = []
        for route in data.get("routes", []):
            options.append(
                {
                    **route,
                    "mode": "taxi",
                    "origin": origin,
                    "destination": destination,
                    "source": "google_routes",
                    "fetched_at": datetime.now().astimezone().isoformat(),
                }
            )
        return {"options": options, "source": "google_routes"}
