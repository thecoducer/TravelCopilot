"""FoodDiscoveryAgent — Layer 4: restaurant recommendations per neighbourhood per day.

Searches for food venues near each day's activity cluster and returns
breakfast / lunch / dinner options keyed by day ISO date.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from app.agents.base import AgentClarificationMixin
from app.logging import get_agent_logger
from app.models.enums import StopKind
from app.models.itinerary import FoodOptions, FoodVenue
from app.models.stops import SINGLE_STOP_ID, DayAllocation, TripStop
from app.models.user_profile import budget_from_state
from app.tools.factory import ToolFactory

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
            # Places photo objects are resource names, not URLs — omit until a
            # renderable-URL source is wired up (avoids broken <img> tags).
            photos=[],
            meal_types=["breakfast", "lunch", "dinner"],
            neighbourhood=item.get("neighbourhood"),
            review_count=item.get("userRatingCount"),
        )
    except Exception:
        return None


def _assign_daily_venues(
    day_dates: list[date], all_venues: list[FoodVenue]
) -> dict[str, list[Any]]:
    """Assign 3 venues (breakfast / lunch / dinner) per day, rotating through the pool."""
    food_recommendations: dict[str, list[Any]] = {}
    for i, day_date in enumerate(day_dates):
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
    return food_recommendations


class FoodDiscoveryAgent(AgentClarificationMixin):
    """Layer 4 — Restaurant discovery per neighbourhood per day."""

    def __init__(self, tool_factory: ToolFactory | None = None) -> None:
        factory = tool_factory or ToolFactory()
        self._places_tool = factory.get("search_places")
        self._places_execution_mode = "replay" if getattr(factory, "is_mock", False) else "live"

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        all_stops = dict(state.get("stops", {}) or {})
        # Gateway pass-through stops have no nights, so every venue found for them
        # is discarded during day assignment — the search is pure API spend.
        stops = {
            stop_id: stop
            for stop_id, stop in all_stops.items()
            if stop.stop_kind == StopKind.OVERNIGHT
        } or all_stops
        stops_by_day: dict[int, DayAllocation] = state.get("stops_by_day", {})
        user_profile = state.get("user_profile")
        session_id: str = state.get("session_id", "")

        log = get_agent_logger("food_discovery", session_id)
        log.info("agent_start", stops=list(stops), skipped=len(all_stops) - len(stops))

        dietary = user_profile.dietary_restrictions if user_profile else []
        preferred_cuisines = user_profile.preferred_cuisines if user_profile else []
        budget_tier = str(budget_from_state(state.get("budget")).tier)

        recommendations = await self._search_stops(
            stops, stops_by_day, dietary, preferred_cuisines, budget_tier, log
        )

        log.info("agent_done", stops=len(recommendations))
        return {
            "food_recommendations_by_stop": recommendations,
            "food_recommendations": recommendations.get(SINGLE_STOP_ID, {}),
        }

    async def _search_stops(
        self,
        stops: dict[str, TripStop],
        stops_by_day: dict[int, DayAllocation],
        dietary: list[str],
        preferred_cuisines: list[str],
        budget_tier: str,
        log: Any,
    ) -> dict[str, Any]:
        """Search food once per overnight stop and return results keyed by stop ID."""

        async def _search_one(stop: TripStop) -> tuple[str, dict[str, list[Any]]]:
            venue_pool = await self._build_venue_pool(
                stop.name, dietary, preferred_cuisines, budget_tier, log
            )
            all_venues = sorted(venue_pool.values(), key=lambda v: v.rating, reverse=True)
            day_dates = sorted(
                allocation.date
                for allocation in stops_by_day.values()
                if allocation.stop_id == stop.stop_id
            )
            return stop.stop_id, _assign_daily_venues(day_dates, all_venues)

        results = await asyncio.gather(*[_search_one(stop) for stop in stops.values()])
        return dict(results)

    async def _build_venue_pool(
        self,
        stop_name: str,
        dietary: list[str],
        preferred_cuisines: list[str],
        budget_tier: str,
        log: Any,
    ) -> dict[str, FoodVenue]:
        """Run one Google Places search for a stop, deduplicated by venue name."""

        log.info(
            "places_search_batch_start",
            provider="google_places",
            execution_mode=self._places_execution_mode,
            stop=stop_name,
        )

        result = await self._search_places(stop_name, dietary, preferred_cuisines, budget_tier, log)

        venue_pool: dict[str, FoodVenue] = {}
        for item in result.get("places", []):
            venue = _parse_food_venue(item)
            if venue and venue.rating >= 3.5:
                venue_pool.setdefault(venue.name, venue)
        log.info(
            "places_search_batch_done",
            provider="google_places",
            execution_mode=self._places_execution_mode,
            stop=stop_name,
            venues_found=len(venue_pool),
        )
        return venue_pool

    async def _search_places(
        self,
        stop_name: str,
        dietary: list[str],
        preferred_cuisines: list[str],
        budget_tier: str,
        log: Any,
    ) -> dict[str, Any]:
        """Search Google Places once for the stop."""
        preferences = " ".join([*preferred_cuisines, *dietary, budget_tier])
        query = f"best restaurants {preferences} in {stop_name}".strip()
        log.info(
            "places_search_start",
            provider="google_places",
            execution_mode=self._places_execution_mode,
            location=stop_name,
            stop=stop_name,
        )
        result = await self._places_tool.run(
            location=stop_name,
            query=query,
            included_types=_FOOD_TYPES,
        )
        metadata = result.get("meta") or {}
        log.info(
            "places_search_done",
            provider="google_places",
            execution_mode=self._places_execution_mode,
            location=stop_name,
            stop=stop_name,
            result_count=len(result.get("places", [])),
            result_status=metadata.get("status"),
        )
        return result
