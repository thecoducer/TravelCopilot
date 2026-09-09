"""Taxi-operator discovery via Google Places API (New)."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class TaxiInfoTool:
    name = "search_taxi_info"
    description = "Google Places search for taxi services and taxi stands."

    async def run(
        self, location: str = "", destination: str = "", **kwargs: object
    ) -> dict[str, Any]:
        query_location = location or destination
        if not query_location:
            return {"options": [], "source": "google_places"}

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.google_places_api_key or settings.google_maps_api_key,
            "X-Goog-FieldMask": (
                "places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
                "places.websiteUri,places.googleMapsUri,places.rating,places.userRatingCount"
            ),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers=headers,
                json={"textQuery": f"taxi service in {query_location}"},
            )
            response.raise_for_status()
            data = response.json()

        options = []
        for place in data.get("places", []):
            options.append(
                {
                    "name": place.get("displayName", {}).get("text"),
                    "address": place.get("formattedAddress"),
                    "phone": place.get("nationalPhoneNumber"),
                    "website": place.get("websiteUri"),
                    "booking_url": place.get("websiteUri"),
                    "google_maps_url": place.get("googleMapsUri"),
                    "rating": place.get("rating"),
                    "review_count": place.get("userRatingCount"),
                    "source": "google_places",
                }
            )
        return {"options": options, "source": "google_places"}