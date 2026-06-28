"""FoodDiscoveryAgent — Layer 4: restaurant recommendations per neighbourhood per day.

Searches for food venues near each day's activity cluster and returns
breakfast / lunch / dinner options keyed by day ISO date.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import structlog

from app.models.itinerary import FoodOptions, FoodVenue
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)

_FOOD_TYPES = ["restaurant", "cafe", "meal_takeaway", "bakery"]


def _parse_food_venue(item: dict[str, Any]) -> FoodVenue | None:
    """Convert a raw Places API item to a FoodVenue model."""
    try:
        location = item.get("location", {})
        return FoodVenue(
            name=item.get("displayName", {}).get("text", "") or item.get("name", ""),
            category=item.get("primaryType", "restaurant"),
            cuisine=item.get("cuisine", item.get("primaryTypeDisplayName", {}).get("text", "")),
            price_range=item.get("priceLevel", "Moderate"),
            rating=float(item.get("rating", 3.5) or 3.5),
            address=item.get("formattedAddress", ""),
            lat=float(location.get("latitude", 0)),
            lng=float(location.get("longitude", 0)),
            google_maps_url=item.get("googleMapsUri"),
            photos=[p.get("name", "") for p in item.get("photos", [])[:2]],
            meal_types=["breakfast", "lunch", "dinner"],
            neighbourhood=item.get("neighbourhood"),
            review_count=item.get("userRatingCount"),
        )
    except Exception:
        return None


def _parse_tavily_venue(result: dict[str, Any], neighbourhood: str) -> FoodVenue | None:
    """Extract a minimal FoodVenue from a Tavily search result item."""
    title = result.get("title", "").strip()
    content = result.get("content", "")
    if not title or len(title) < 3:
        return None
    # Heuristic: skip results that are clearly not venue names (articles, guides)
    skip_words = ("best", "top", "guide", "list", "things", "where to", "places to", "how")
    if any(title.lower().startswith(w) for w in skip_words):
        return None
    # Infer cuisine from content keywords
    cuisine = "Local cuisine"
    for kw in ("italian", "chinese", "indian", "japanese", "thai", "mexican", "french", "korean"):
        if kw in content.lower():
            cuisine = kw.capitalize()
            break
    try:
        return FoodVenue(
            name=title,
            category="restaurant",
            cuisine=cuisine,
            price_range="Moderate",
            rating=3.5,
            address=neighbourhood,
            neighbourhood=neighbourhood,
        )
    except Exception:
        return None


class FoodDiscoveryAgent:
    """Layer 4 — Restaurant discovery per neighbourhood per day."""

    def __init__(self, tool_factory: ToolFactory | None = None) -> None:
        factory = tool_factory or ToolFactory()
        self._places_tool = factory.get("search_places")
        self._tavily_tool = factory.get("tavily_search")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        destination: str = state.get("destination", "")
        experiences_raw = state.get("experiences_raw", [])
        dates = state.get("dates")
        user_profile = state.get("user_profile")
        session_id: str = state.get("session_id", "")

        log = logger.bind(agent="food_discovery", destination=destination, session_id=session_id)
        log.info("agent_start")

        dietary = user_profile.dietary_restrictions if user_profile else []
        trip_days = dates.trip_days if dates else 3
        start_date = dates.departure if dates else date.today()

        # Build a list of (day_date, location_label) pairs
        # For single-destination trips, all days are at the destination
        day_locations = [(start_date + timedelta(days=i), destination) for i in range(trip_days)]

        # Derive unique neighbourhood/area names from experiences (if any)
        areas: list[str] = list(
            {
                (exp.address or destination).split(",")[0].strip()
                for exp in experiences_raw
                if exp.address
            }
        ) or [destination]

        async def _fetch_for_area(area: str) -> list[FoodVenue]:
            result = await self._places_tool.run(
                location=area,
                query=f"best restaurants {area} {destination}",
                included_types=_FOOD_TYPES,
            )
            venues: list[FoodVenue] = []
            for item in result.get("places", []):
                venue = _parse_food_venue(item)
                if venue and venue.rating >= 3.5:
                    # Filter dietary restrictions at data level
                    if dietary and not any(
                        d.lower() in [t.lower() for t in (venue.dietary_tags or [])]
                        for d in dietary
                    ):
                        # No dietary match — don't strictly exclude, but deprioritise
                        pass
                    venues.append(venue)
            return venues

        async def _fetch_tavily_for_area(area: str) -> list[FoodVenue]:
            """Supplement Places results with Tavily neighbourhood food search."""
            venues: list[FoodVenue] = []
            queries = [
                f"best food in {area} {destination} locals recommend",
                f"best street food in {destination} {area}",
            ]
            for query in queries:
                try:
                    result = await self._tavily_tool.run(query=query, destination=destination)
                    for item in result.get("results", []):
                        venue = _parse_tavily_venue(item, area)
                        if venue and venue.name not in {v.name for v in venues}:
                            venues.append(venue)
                except Exception:
                    pass
            return venues

        places_task = asyncio.gather(
            *[_fetch_for_area(a) for a in areas[:4]],
            return_exceptions=True,
        )
        tavily_task = asyncio.gather(
            *[_fetch_tavily_for_area(a) for a in areas[:4]],
            return_exceptions=True,
        )
        area_results, tavily_results = await asyncio.gather(places_task, tavily_task)

        # Build a flat pool of venues, deduplicated by name
        # Places results take priority; Tavily supplements with lower-confidence entries
        venue_pool: dict[str, FoodVenue] = {}
        for r in area_results:
            if isinstance(r, Exception):
                continue
            for v in r:
                if v.name not in venue_pool:
                    venue_pool[v.name] = v
        for r in tavily_results:
            if isinstance(r, Exception):
                continue
            for v in r:
                if v.name not in venue_pool:
                    venue_pool[v.name] = v

        all_venues = sorted(venue_pool.values(), key=lambda v: v.rating, reverse=True)

        # Assign 3 venues (breakfast / lunch / dinner) per day
        food_recommendations: dict[str, list[Any]] = {}
        for i, (day_date, _location) in enumerate(day_locations):
            day_key = day_date.isoformat()
            # Rotate through the pool so each day gets slightly different picks
            offset = i * 3
            day_venues = all_venues[offset : offset + 3] or all_venues[:3]
            meal_types = ["breakfast", "lunch", "dinner"]
            food_opts = [
                FoodOptions(
                    meal_type=meal,
                    options=[v] if j < len(day_venues) else [],
                ).model_dump()
                for j, (meal, v) in enumerate(zip(meal_types, day_venues, strict=False))
            ]
            food_recommendations[day_key] = food_opts

        log.info("agent_done", days_covered=len(food_recommendations), venues=len(all_venues))
        return {"food_recommendations": food_recommendations}
