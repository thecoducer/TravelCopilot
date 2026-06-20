"""LocalExperiencesAgent — Layer 2: attractions, activities, and tours.

Pure tool-call agent — no LLM.  Returns a list of ``Experience`` objects that
feed into Layer 3 ReviewsAgent, Layer 4 FoodDiscoveryAgent, and ultimately the
ItineraryCompilerAgent's geo-clustering step.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.models.itinerary import Experience, OpeningHours
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)

# Google Places types that represent experiences (not food/services)
_EXPERIENCE_TYPES = [
    "tourist_attraction",
    "museum",
    "art_gallery",
    "park",
    "amusement_park",
    "zoo",
    "aquarium",
    "stadium",
    "spa",
    "night_club",
    "casino",
]

# Mapping of user interests → Google Places types
_INTEREST_TYPE_MAP: dict[str, list[str]] = {
    "history": ["museum", "tourist_attraction"],
    "art": ["art_gallery", "museum"],
    "nightlife": ["night_club", "casino", "bar"],
    "nature": ["park", "zoo", "aquarium"],
    "adventure": ["tourist_attraction", "park"],
    "wellness": ["spa"],
    "sports": ["stadium"],
    "food": [],  # handled by FoodDiscoveryAgent
}


def _build_types(interests: list[str]) -> list[str]:
    """Return Google Places types relevant to the user's interests."""
    if not interests:
        return _EXPERIENCE_TYPES[:6]
    types: set[str] = set()
    for interest in interests:
        types.update(_INTEREST_TYPE_MAP.get(interest.lower(), []))
    return list(types) or _EXPERIENCE_TYPES[:6]


def _parse_experience(item: dict[str, Any], source: str) -> Experience | None:
    """Convert a raw Places API item dict to an Experience model."""
    try:
        location = item.get("location", {})
        lat = float(location.get("latitude", 0))
        lng = float(location.get("longitude", 0))

        raw_hours = item.get("opening_hours", {})
        hours: OpeningHours | None = None
        if isinstance(raw_hours, dict) and raw_hours.get("open"):
            hours = OpeningHours(
                open=raw_hours.get("open", "09:00"),
                close=raw_hours.get("close", "18:00"),
                days=raw_hours.get("days", []),
            )

        return Experience(
            name=item.get("displayName", {}).get("text", "") or item.get("name", ""),
            type=item.get("primaryType", "tourist_attraction"),
            description=item.get("editorialSummary", {}).get("text", "")
            or item.get("description", ""),
            duration_hours=float(item.get("duration_hours", 2.0)),
            price_range=item.get("priceLevel", "Moderate"),
            lat=lat,
            lng=lng,
            photos=[photo.get("name", "") for photo in item.get("photos", [])[:3]],
            google_maps_url=item.get("googleMapsUri"),
            opening_hours=hours,
            best_time_to_visit=item.get("best_time_to_visit"),
            source=source,
            rating=item.get("rating"),
            review_count=item.get("userRatingCount"),
            address=item.get("formattedAddress"),
        )
    except Exception:
        return None


class LocalExperiencesAgent:
    """Layer 2 — Attractions, activities, and tours at the destination."""

    def __init__(self, tool_factory: ToolFactory | None = None) -> None:
        factory = tool_factory or ToolFactory()
        self._places_tool = factory.get("search_places")
        self._tavily_tool = factory.get("tavily_search")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        destination: str = state.get("destination", "")
        user_profile = state.get("user_profile")
        session_id: str = state.get("session_id", "")

        interests = user_profile.interests if user_profile else []
        log = logger.bind(agent="local_experiences", destination=destination, session_id=session_id)
        log.info("agent_start", interests=interests)

        included_types = _build_types(interests)

        # Parallel: Google Places search + Tavily "hidden gems"
        places_task = self._places_tool.run(
            location=destination,
            query=f"top attractions {destination}",
            included_types=included_types,
        )
        tavily_task = self._tavily_tool.run(
            query=f"hidden gems things to do {destination} locals recommend 2026",
            destination=destination,
        )

        places_result, tavily_result = await asyncio.gather(
            places_task, tavily_task, return_exceptions=True
        )

        experiences: list[Experience] = []
        # Track names already confirmed by Google Places for deduplication
        confirmed_names: set[str] = set()

        # Parse Google Places results — trusted source, no grounding needed
        if not isinstance(places_result, Exception):
            for item in places_result.get("places", []):
                exp = _parse_experience(item, "google_places")
                if exp and exp.lat != 0.0:
                    experiences.append(exp)
                    confirmed_names.add(exp.name.lower())

        # Parse Tavily results with grounding check (D)
        # Every Tavily-sourced experience must be verified in Google Places
        if not isinstance(tavily_result, Exception):
            tavily_names = [
                item.get("title", "").split("—")[0].strip()
                for item in tavily_result.get("results", [])
                if item.get("title")
            ]

            if tavily_names:
                # Verify each Tavily-suggested place in Google Places
                verify_tasks = [
                    self._places_tool.run(
                        location=destination,
                        query=name,
                        included_types=["tourist_attraction", "point_of_interest"],
                    )
                    for name in tavily_names[:5]  # cap verification calls
                ]
                verify_results = await asyncio.gather(*verify_tasks, return_exceptions=True)

                for name, verify_result in zip(tavily_names, verify_results, strict=False):
                    if isinstance(verify_result, Exception):
                        continue  # drop on error
                    places = verify_result.get("places", [])
                    if not places:
                        log.debug("tavily_grounding_failed", name=name)
                        continue  # (D) drop Tavily result with no Places match
                    # Use the Places-verified version (richer data)
                    exp = _parse_experience(places[0], "google_places")
                    if exp and exp.lat != 0.0 and exp.name.lower() not in confirmed_names:
                        experiences.append(exp)
                        confirmed_names.add(exp.name.lower())

        log.info("agent_done", experiences_found=len(experiences))
        return {"experiences_raw": experiences}
