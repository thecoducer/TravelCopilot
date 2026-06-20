"""Mock Google Places tools — attraction and food search from fixtures.

Returns data in Google Places new API format: {places: [...]}
Switches between attractions and food fixtures based on included_types.
"""

from __future__ import annotations

from typing import Any

from app.tools.mock._helpers import find_fixture

_FOOD_TYPES = frozenset(
    [
        "restaurant",
        "cafe",
        "meal_takeaway",
        "bakery",
        "bar",
        "food",
        "meal_delivery",
        "fast_food",
    ]
)


class MockPlaceSearchTool:
    name = "search_places"
    description = "Mock Places search — Google Places new API format, no network calls."

    async def run(
        self,
        location: str = "",
        query: str = "",
        included_types: list[str] | None = None,
        **kwargs: object,
    ) -> dict[str, Any]:
        loc = location.lower().split(",")[0].strip()
        # Route to food fixture if food types are requested
        if included_types and _FOOD_TYPES & set(included_types):
            data = find_fixture("food", loc)
            if data:
                return data
        # Default: attractions
        for suffix in ("attractions", ""):
            data = find_fixture("places", loc, suffix) if suffix else find_fixture("places", loc)
            if data:
                return data
        return {"places": []}


class MockPlaceDetailsTool:
    name = "place_details"
    description = "Mock Place Details — returns fixture place details, no network calls."

    async def run(self, place_id: str = "", name: str = "", **kwargs: object) -> dict[str, Any]:
        # Return a generic detail object with the provided name
        return {
            "place_id": place_id or "mock_place_id",
            "name": name or "Mock Place",
            "rating": 4.2,
            "review_count": 500,
            "reviews": [
                {"author": "Alice", "rating": 5, "text": "Wonderful experience! Highly recommend."},
                {"author": "Bob", "rating": 4, "text": "Good value, slightly crowded."},
                {"author": "Carol", "rating": 4, "text": "Clean facilities and helpful staff."},
            ],
            "photos": [
                "https://example.com/mock-place-photo-1.jpg",
                "https://example.com/mock-place-photo-2.jpg",
            ],
            "opening_hours": {
                "open": "09:00",
                "close": "18:00",
                "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            },
            "website": "https://example.com",
            "google_maps_url": f"https://maps.google.com/?q={place_id or 'mock'}",
        }
