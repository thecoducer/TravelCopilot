"""Shared Google Routes request and normalization helpers."""

from __future__ import annotations

from typing import Any

from app.config import (
    GOOGLE_ROUTES_FIELD_MASK,
    GOOGLE_TRAVEL_MODE_DRIVE,
    HTTP_HEADER_CONTENT_TYPE,
    HTTP_HEADER_GOOGLE_API_KEY,
    HTTP_HEADER_GOOGLE_FIELD_MASK,
    HTTP_HEADER_JSON,
    PROVIDER_GOOGLE,
    settings,
)
from app.services.external_api_client import ExternalAPIClient, ExternalResponse
from app.tools.real._helpers import provider_result, require_credential


class GoogleRoutesClient:
    """Build and execute Compute Routes requests for road and transit tools."""

    def __init__(self, client: ExternalAPIClient) -> None:
        self._client = client

    async def compute_route(
        self,
        origin: str,
        destination: str,
        travel_mode: str,
        departure_time: str = "",
    ) -> ExternalResponse:
        require_credential(settings.google_cloud_api_key, PROVIDER_GOOGLE)
        request_body: dict[str, Any] = {
            "origin": {"address": origin},
            "destination": {"address": destination},
            "travelMode": travel_mode,
            "computeAlternativeRoutes": True,
        }
        if travel_mode == GOOGLE_TRAVEL_MODE_DRIVE:
            request_body["routingPreference"] = "TRAFFIC_AWARE"
        if departure_time:
            request_body["departureTime"] = departure_time
        return await self._client.request_json(
            PROVIDER_GOOGLE,
            "POST",
            settings.google_routes_url,
            headers={
                HTTP_HEADER_CONTENT_TYPE: HTTP_HEADER_JSON,
                HTTP_HEADER_GOOGLE_API_KEY: settings.google_cloud_api_key,
                HTTP_HEADER_GOOGLE_FIELD_MASK: GOOGLE_ROUTES_FIELD_MASK,
            },
            json_body=request_body,
        )


def route_result(
    response: ExternalResponse,
    origin: str,
    destination: str,
    mode: str,
) -> dict[str, Any]:
    routes = response.payload.get("routes", [])
    options = []
    if isinstance(routes, list):
        options = [
            {
                **route,
                "mode": mode,
                "origin": origin,
                "destination": destination,
                "source": PROVIDER_GOOGLE,
            }
            for route in routes
            if isinstance(route, dict)
        ]
    return provider_result(
        {"options": options, "source": PROVIDER_GOOGLE}, response, {"options": []}
    )
