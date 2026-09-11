"""LocalExperiencesAgent — Layer 2: attractions, activities, and tours.

Pure tool-call agent — no LLM.  Returns a list of ``Experience`` objects that
feed into Layer 3 ReviewsAgent, Layer 4 FoodDiscoveryAgent, and ultimately the
ItineraryCompilerAgent's geo-clustering step.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.logging import get_agent_logger
from app.models.itinerary import Experience, OpeningHours
from app.tools.factory import ToolFactory

# Google Places API (New) types that represent experiences (not food/services)
_EXPERIENCE_TYPES = [
    "tourist_attraction",
    "museum",
    "historical_landmark",
    "historical_place",
    "monument",
    "cultural_landmark",
    "cultural_center",
    "art_gallery",
    "art_studio",
    "sculpture",
    "park",
    "national_park",
    "state_park",
    "garden",
    "botanical_garden",
    "hiking_area",
    "amusement_park",
    "water_park",
    "zoo",
    "aquarium",
    "wildlife_park",
    "wildlife_refuge",
    "stadium",
    "sports_complex",
    "spa",
    "sauna",
    "yoga_studio",
    "night_club",
    "casino",
    "comedy_club",
    "karaoke",
    "movie_theater",
    "performing_arts_theater",
    "opera_house",
    "concert_hall",
    "philharmonic_hall",
    "observation_deck",
    "planetarium",
    "visitor_center",
    "marina",
    "plaza",
    "church",
    "hindu_temple",
    "mosque",
    "synagogue",
]

# Mapping of user interests → Google Places API (New) types
_INTEREST_TYPE_MAP: dict[str, list[str]] = {
    "history": [
        "museum",
        "historical_landmark",
        "historical_place",
        "monument",
        "cultural_landmark",
    ],
    "art": ["art_gallery", "art_studio", "sculpture", "museum", "cultural_center"],
    "culture": ["cultural_center", "cultural_landmark", "museum", "performing_arts_theater"],
    "nightlife": ["night_club", "casino", "comedy_club", "karaoke", "bar"],
    "nature": ["park", "national_park", "state_park", "garden", "botanical_garden", "hiking_area"],
    "wildlife": ["zoo", "aquarium", "wildlife_park", "wildlife_refuge"],
    "adventure": ["tourist_attraction", "hiking_area", "water_park", "amusement_park"],
    "wellness": ["spa", "sauna", "yoga_studio"],
    "relaxation": ["spa", "sauna", "garden", "botanical_garden", "marina"],
    "sports": ["stadium", "sports_complex"],
    "entertainment": [
        "movie_theater",
        "performing_arts_theater",
        "opera_house",
        "concert_hall",
        "philharmonic_hall",
    ],
    "photography": ["observation_deck", "plaza", "historical_landmark", "botanical_garden"],
    "religion": ["church", "hindu_temple", "mosque", "synagogue"],
    "family": ["amusement_park", "water_park", "zoo", "aquarium", "planetarium"],
    "food": [],  # handled by FoodDiscoveryAgent
}


def _build_types(interests: list[str]) -> list[str]:
    """Return Google Places types relevant to the user's interests."""
    if not interests:
        return _EXPERIENCE_TYPES
    types: set[str] = set()
    for interest in interests:
        types.update(_INTEREST_TYPE_MAP.get(interest.lower(), []))
    return list(types) or _EXPERIENCE_TYPES


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

        log = get_agent_logger("local_experiences", session_id, destination=destination)
        log.info("agent_start", interests=interests)

        places_result, tavily_result = await self._search(destination, interests, state.get("dates"))

        experiences: list[Experience] = []
        confirmed_names: set[str] = set()
        self._collect_places_experiences(places_result, experiences, confirmed_names)
        await self._collect_grounded_tavily_experiences(
            tavily_result, destination, experiences, confirmed_names, log
        )

        log.info("agent_done", experiences_found=len(experiences))
        return {"experiences_raw": experiences}

    async def _search(
        self, destination: str, interests: list[str], dates: Any
    ) -> tuple[dict[str, Any] | BaseException, dict[str, Any] | BaseException]:
        """Run Google Places and Tavily "hidden gems" searches in parallel."""
        included_types = _build_types(interests)

        places_task = self._places_tool.run(
            location=destination,
            query=f"top attractions {destination}",
            included_types=included_types,
        )
        tavily_task = self._tavily_tool.run(
            query=self._build_tavily_query(destination, dates),
            destination=destination,
        )

        places_result, tavily_result = await asyncio.gather(
            places_task, tavily_task, return_exceptions=True
        )
        return places_result, tavily_result

    @staticmethod
    def _build_tavily_query(destination: str, dates: Any) -> str:
        departure = getattr(dates, "departure", None)
        return_date = getattr(dates, "return_date", None)
        departure_str = departure.isoformat() if departure else ""
        return_date_str = return_date.isoformat() if return_date else ""

        return f"hidden gems things to do in {destination} locals recommend" + (
            f" between {departure_str} and {return_date_str}"
            if departure_str and return_date_str
            else f" in {destination}"
        )

    @staticmethod
    def _collect_places_experiences(
        places_result: dict[str, Any] | BaseException,
        experiences: list[Experience],
        confirmed_names: set[str],
    ) -> None:
        """Parse Google Places results — trusted source, no grounding needed."""
        if isinstance(places_result, BaseException):
            return
        for item in places_result.get("places", []):
            exp = _parse_experience(item, "google_places")
            if exp and exp.lat != 0.0:
                experiences.append(exp)
                confirmed_names.add(exp.name.lower())

    async def _collect_grounded_tavily_experiences(
        self,
        tavily_result: dict[str, Any] | BaseException,
        destination: str,
        experiences: list[Experience],
        confirmed_names: set[str],
        log: Any,
    ) -> None:
        """Parse Tavily results, keeping only entries verified in Google Places (D)."""
        if isinstance(tavily_result, BaseException):
            return

        tavily_names = [
            item.get("title", "").split("—")[0].strip()
            for item in tavily_result.get("results", [])
            if item.get("title")
        ]
        if not tavily_names:
            return

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
            if isinstance(verify_result, BaseException):
                continue  # drop on error
            places = verify_result.get("places", [])
            if not places:
                log.debug("tavily_grounding_failed", name=name)
                continue  # drop Tavily result with no Places match
            exp = _parse_experience(places[0], "google_places")  # use Places-verified data
            if exp and exp.lat != 0.0 and exp.name.lower() not in confirmed_names:
                experiences.append(exp)
                confirmed_names.add(exp.name.lower())
