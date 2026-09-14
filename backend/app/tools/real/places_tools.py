"""Google Places API (New) Text Search and Place Details adapters."""

from __future__ import annotations

from typing import Any

from app.config import (
    GOOGLE_PLACES_DETAILS_FIELD_MASK,
    GOOGLE_PLACES_SEARCH_FIELD_MASK,
    HTTP_HEADER_CONTENT_TYPE,
    HTTP_HEADER_GOOGLE_API_KEY,
    HTTP_HEADER_GOOGLE_FIELD_MASK,
    HTTP_HEADER_JSON,
    PROVIDER_GOOGLE,
    settings,
)
from app.services.external_api_client import ExternalAPIClient, get_external_api_client
from app.tools.real._helpers import invalid_request_result, provider_result, require_credential


class PlaceSearchTool:
    name = "search_places"
    description = "Real Places Text Search via Google Places API."

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        self._client = client or get_external_api_client()

    async def run(
        self,
        location: str = "",
        query: str = "",
        included_types: list[str] | None = None,
        max_results: int = 20,
        **kwargs: object,
    ) -> dict[str, Any]:
        empty_result: dict[str, Any] = {"places": []}
        if not location and not query:
            return invalid_request_result("location or query is required", empty_result)
        require_credential(settings.google_cloud_api_key, PROVIDER_GOOGLE)
        text_query = query or location
        if location and query and location.lower() not in query.lower():
            text_query = f"{query} in {location}"
        request_body: dict[str, Any] = {
            "textQuery": text_query,
            "maxResultCount": max(1, min(max_results, 20)),
        }
        if included_types:
            request_body["includedType"] = included_types[0]
        response = await self._client.request_json(
            PROVIDER_GOOGLE,
            "POST",
            settings.google_places_search_url,
            headers={
                HTTP_HEADER_CONTENT_TYPE: HTTP_HEADER_JSON,
                HTTP_HEADER_GOOGLE_API_KEY: settings.google_cloud_api_key,
                HTTP_HEADER_GOOGLE_FIELD_MASK: GOOGLE_PLACES_SEARCH_FIELD_MASK,
            },
            json_body=request_body,
        )
        return provider_result(response.payload, response, empty_result)


class PlaceDetailsTool:
    name = "place_details"
    description = "Real Place Details via Google Places Details API."

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        self._client = client or get_external_api_client()

    async def run(
        self,
        place_id: str = "",
        name: str = "",
        **kwargs: object,
    ) -> dict[str, Any]:
        empty_result: dict[str, Any] = {
            "place_id": place_id,
            "name": name,
            "reviews": [],
            "photos": [],
        }
        if not place_id:
            return invalid_request_result("place_id is required", empty_result)
        require_credential(settings.google_cloud_api_key, PROVIDER_GOOGLE)
        resource_name = place_id if place_id.startswith("places/") else f"places/{place_id}"
        response = await self._client.request_json(
            PROVIDER_GOOGLE,
            "GET",
            f"{settings.google_places_details_url}/{resource_name.removeprefix('places/')}",
            headers={
                HTTP_HEADER_CONTENT_TYPE: HTTP_HEADER_JSON,
                HTTP_HEADER_GOOGLE_API_KEY: settings.google_cloud_api_key,
                HTTP_HEADER_GOOGLE_FIELD_MASK: GOOGLE_PLACES_DETAILS_FIELD_MASK,
            },
        )
        normalized_result = self._normalize_details(response.payload, place_id, name)
        return provider_result(normalized_result, response, empty_result)

    def _normalize_details(
        self, payload: dict[str, Any], place_id: str, fallback_name: str
    ) -> dict[str, Any]:
        display_name = payload.get("displayName", {})
        location = payload.get("location", {})
        return {
            "place_id": payload.get("id", place_id),
            "name": display_name.get("text", fallback_name),
            "rating": payload.get("rating"),
            "review_count": payload.get("userRatingCount"),
            "reviews": payload.get("reviews", []),
            "photos": payload.get("photos", []),
            "opening_hours": payload.get("regularOpeningHours"),
            "current_opening_hours": payload.get("currentOpeningHours"),
            "website": payload.get("websiteUri"),
            "google_maps_url": payload.get("googleMapsUri"),
            "address": payload.get("formattedAddress"),
            "lat": location.get("latitude"),
            "lng": location.get("longitude"),
        }
