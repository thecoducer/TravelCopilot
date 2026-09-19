"""SerpAPI Google Flights and Google Hotels adapters."""

from __future__ import annotations

from typing import Any

from app.config import (
    PROVIDER_SERPAPI,
    SERPAPI_FLIGHTS_AUTOCOMPLETE_ENGINE,
    SERPAPI_FLIGHTS_ENGINE,
    SERPAPI_HOTELS_ENGINE,
    SERPAPI_ONE_WAY_TYPE,
    settings,
)
from app.services.external_api_client import (
    ExternalAPIClient,
    ExternalResponse,
    get_external_api_client,
)
from app.tools.real._helpers import invalid_request_result, provider_result, require_credential


class FlightSearchTool:
    name = "search_flights"
    description = "Real flight search via SerpAPI google_flights engine."

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        self._client = client or get_external_api_client()

    async def run(
        self,
        origin: str = "",
        destination: str = "",
        departure_date: str = "",
        return_date: str = "",
        adults: int | None = None,
        currency: str = "",
        language: str | None = None,
        **kwargs: object,
    ) -> dict[str, Any]:
        adults = settings.serpapi_default_adults if adults is None else adults
        language = language or settings.serpapi_default_language
        currency = (currency or settings.default_currency).strip().upper()
        empty_result: dict[str, Any] = {"best_flights": [], "other_flights": []}
        if not origin or not destination or not departure_date:
            return invalid_request_result(
                "origin, destination, and departure_date are required", empty_result
            )
        require_credential(settings.serpapi_key, PROVIDER_SERPAPI)
        origin_id, origin_response = await self._resolve_location(origin, language)
        destination_id, destination_response = await self._resolve_location(destination, language)
        response = await self._search_flights(
            origin_id,
            destination_id,
            departure_date,
            return_date,
            adults,
            currency,
            language,
        )
        response.exchanges = (
            origin_response.exchanges + destination_response.exchanges + response.exchanges
        )
        response.retry_count += origin_response.retry_count + destination_response.retry_count
        response.duration_ms += origin_response.duration_ms + destination_response.duration_ms
        return provider_result(response.payload, response, empty_result)

    async def _resolve_location(self, location: str, language: str) -> tuple[str, ExternalResponse]:
        response = await self._client.request_json(
            PROVIDER_SERPAPI,
            "GET",
            settings.serpapi_search_url,
            params={
                "engine": SERPAPI_FLIGHTS_AUTOCOMPLETE_ENGINE,
                "q": location,
                "hl": language,
                "api_key": settings.serpapi_key,
            },
        )
        suggestions = response.payload.get("suggestions", [])
        if isinstance(suggestions, list):
            for suggestion in suggestions:
                if not isinstance(suggestion, dict):
                    continue
                airports = suggestion.get("airports", [])
                if isinstance(airports, list) and airports:
                    airport = airports[0]
                    if isinstance(airport, dict) and airport.get("id"):
                        return str(airport["id"]), response
                if suggestion.get("id"):
                    return str(suggestion["id"]), response
        return location, response

    async def _search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str,
        adults: int,
        currency: str,
        language: str,
    ) -> ExternalResponse:
        params: dict[str, str | int | float | bool] = {
            "engine": SERPAPI_FLIGHTS_ENGINE,
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": departure_date,
            "currency": currency,
            "hl": language,
            "gl": settings.serpapi_default_country,
            "adults": max(1, adults),
            "type": "1" if return_date else SERPAPI_ONE_WAY_TYPE,
            "api_key": settings.serpapi_key,
        }
        if return_date:
            params["return_date"] = return_date
        return await self._client.request_json(
            PROVIDER_SERPAPI, "GET", settings.serpapi_search_url, params=params
        )


class HotelSearchTool:
    name = "search_hotels"
    description = "Real hotel search via SerpAPI google_hotels engine."

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        self._client = client or get_external_api_client()

    async def run(
        self,
        location: str = "",
        check_in: str = "",
        check_out: str = "",
        adults: int | None = None,
        currency: str = "",
        language: str | None = None,
        **kwargs: object,
    ) -> dict[str, Any]:
        adults = settings.serpapi_default_hotel_adults if adults is None else adults
        language = language or settings.serpapi_default_language
        currency = (currency or settings.default_currency).strip().upper()
        empty_result: dict[str, Any] = {"properties": []}
        if not location or not check_in or not check_out:
            return invalid_request_result(
                "location, check_in, and check_out are required", empty_result
            )
        require_credential(settings.serpapi_key, PROVIDER_SERPAPI)
        params: dict[str, str | int | float | bool] = {
            "engine": SERPAPI_HOTELS_ENGINE,
            "q": location,
            "check_in_date": check_in,
            "check_out_date": check_out,
            "adults": max(1, adults),
            "currency": currency,
            "hl": language,
            "gl": settings.serpapi_default_country,
            "api_key": settings.serpapi_key,
        }
        response = await self._client.request_json(
            PROVIDER_SERPAPI, "GET", settings.serpapi_search_url, params=params
        )
        return provider_result(response.payload, response, empty_result)
