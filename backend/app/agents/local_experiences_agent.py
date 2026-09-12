"""LocalExperiencesAgent — Layer 2: curated attractions, activities, and experiences.

Uses an LLM to discover and recommend authentic attractions, hidden gems, and
cultural/outdoor activities tailored to the traveler's interests, fitness level,
and travel dates. Geocodes locations via GeocodeTool to ensure valid lat/lng
coordinates for downstream clustering by ItineraryCompilerAgent.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import get_llm
from app.logging import get_agent_logger
from app.models.itinerary import (
    Experience,
    ExperiencesOutput,
)
from app.models.stops import TripStop
from app.tools.factory import ToolFactory

_SYSTEM_PROMPT = """\
You are an expert local guide and travel curator with deep worldwide knowledge of attractions, \
landmarks, outdoor activities, cultural experiences, and hidden gems.

Given a destination or stop, user travel profile, interests, and dates, curate a diverse, \
high-quality list of 6 to 12 top experiences and attractions.

Rules:
1. Tailor choices to the traveler's specified interests, travel style, and fitness level.
2. Include both iconic must-see highlights and authentic local gems.
3. Provide realistic duration_hours (e.g. 1.0 - 4.0) and best_time_to_visit (e.g. 'Morning for soft light and fewer crowds', 'Sunset').
4. Estimate realistic price_range ('Free', 'Inexpensive', 'Moderate', 'Expensive').
5. Estimate approximate latitude (lat) and longitude (lng) coordinates if known.
6. Avoid generic or fabricated places — only suggest real, verifiable venues and landmarks.
"""


class LocalExperiencesAgent:
    """Layer 2 — LLM-driven attractions, activities, and experiences with geocode enrichment."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: Any | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._tool_factory = factory
        self._geocode_tool = factory.get("geocode")
        self._llm = llm

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        destination: str = state.get("destination", "")
        user_profile = state.get("user_profile")
        session_id: str = state.get("session_id", "")
        interests = user_profile.interests if user_profile else []
        dates = state.get("dates")

        log = get_agent_logger("local_experiences", session_id, destination=destination)
        log.info("agent_start", interests=interests)

        # Route multi-stop itineraries to per-stop curation
        stops: dict[str, TripStop] = state.get("stops", {})
        overnight_stops = [s for s in stops.values() if s.stop_kind == "overnight"]
        if state.get("route_discovery_status") == "multi_stop_provisional" and overnight_stops:
            return await self._curate_experiences_for_stops(
                overnight_stops, user_profile, dates, session_id, state.get("route_version", 0), log
            )

        # Default: single destination trip
        experiences = await self._curate_experiences_for_location(
            destination, user_profile, dates, session_id, log
        )
        log.info("agent_done", experiences_found=len(experiences))
        return {"experiences_raw": experiences}

    async def _curate_experiences_for_stops(
        self,
        overnight_stops: list[TripStop],
        user_profile: Any,
        dates: Any,
        session_id: str,
        route_version: int,
        log: Any,
    ) -> dict[str, Any]:
        """Curate experiences for every overnight stop occurrence in parallel.

        Keyed by ``stop_id`` — not stop name — so two occurrences of the same
        place (e.g. visited outbound and again on the way back) never collide.
        Each ``Experience`` also carries its producing ``stop_id`` so later
        clustering can never misplace it into another stop's segment.
        """
        tasks = [
            self._curate_single_stop_experiences(
                stop, user_profile, dates, session_id, route_version, log
            )
            for stop in overnight_stops
        ]
        results = await asyncio.gather(*tasks)
        experiences_raw_by_stop = {
            stop.stop_id: exps for stop, exps in zip(overnight_stops, results, strict=True)
        }
        log.info(
            "agent_done",
            mode="multi_stop_provisional",
            stops=list(experiences_raw_by_stop.keys()),
        )
        return {"experiences_raw_by_stop": experiences_raw_by_stop}

    async def _curate_single_stop_experiences(
        self,
        stop: TripStop,
        user_profile: Any,
        dates: Any,
        session_id: str,
        route_version: int,
        log: Any,
    ) -> list[Experience]:
        """Curate experiences for a single stop occurrence and bind its stop metadata."""
        exps = await self._curate_experiences_for_location(
            stop.name,
            user_profile,
            dates,
            session_id,
            log,
            fallback_coords=(stop.lat, stop.lng),
        )
        return [
            e.model_copy(update={"stop_id": stop.stop_id, "route_version": route_version})
            for e in exps
        ]

    async def _curate_experiences_for_location(
        self,
        location: str,
        user_profile: Any,
        dates: Any,
        session_id: str,
        log: Any,
        fallback_coords: tuple[float | None, float | None] | None = None,
    ) -> list[Experience]:
        """Curate experiences for a specific location using LLM discovery and geocode enrichment."""
        raw_experiences = await self._generate_experiences(
            location, user_profile, dates, session_id, log
        )
        if not raw_experiences:
            return [self._build_fallback_experience(location, fallback_coords)]

        enriched = await self._enrich_coordinates(location, raw_experiences, fallback_coords)
        return enriched

    async def _generate_experiences(
        self,
        location: str,
        user_profile: Any,
        dates: Any,
        session_id: str,
        log: Any,
    ) -> list[Experience]:
        """Query the LLM with structured output to generate personalized attraction recommendations."""
        llm = self._llm or get_llm("local_experiences", session_id)
        structured_llm = llm.with_structured_output(ExperiencesOutput)

        interests = user_profile.interests if user_profile else []
        travel_style = getattr(user_profile, "travel_style", None) or "balanced"
        fitness_level = getattr(user_profile, "fitness_level", None) or "moderate"

        dates_info = ""
        if dates:
            dep = getattr(dates, "departure", None)
            ret = getattr(dates, "return_date", None)
            if dep:
                dates_info = f"Travel Dates: {dep} to {ret or dep} (Month: {dep.strftime('%B')})"

        prompt = (
            f"Destination / Location: {location}\n"
            f"User Interests: {', '.join(interests) if interests else 'General sightseeing, culture, nature'}\n"
            f"Travel Style: {travel_style}\n"
            f"Fitness Level: {fitness_level}\n"
            f"{dates_info}\n\n"
            f"Please recommend 6 to 12 top experiences and attractions for {location}."
        )

        try:
            response: ExperiencesOutput = await structured_llm.ainvoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )
            return response.experiences or []
        except Exception as exc:
            log.warning("local_experiences_llm_failed", error=str(exc))
            return []

    async def _enrich_coordinates(
        self,
        location: str,
        experiences: list[Experience],
        fallback_coords: tuple[float | None, float | None] | None = None,
    ) -> list[Experience]:
        """Resolve valid geographic coordinates for each experience to enable downstream spatial clustering."""
        base_lat: float | None = fallback_coords[0] if fallback_coords else None
        base_lng: float | None = fallback_coords[1] if fallback_coords else None
        if base_lat is None or base_lng is None or base_lat == 0.0:
            base_geo = await self._geocode_tool.run(location=location)
            base_lat = float(base_geo.get("lat", 0.0) or 0.0)
            base_lng = float(base_geo.get("lng", 0.0) or 0.0)

        tasks = [
            self._resolve_experience_coordinates(i, exp, location, base_lat, base_lng)
            for i, exp in enumerate(experiences)
        ]
        return await asyncio.gather(*tasks)

    async def _resolve_experience_coordinates(
        self,
        index: int,
        exp: Experience,
        location: str,
        base_lat: float | None,
        base_lng: float | None,
    ) -> Experience:
        """Resolve coordinates for an individual experience, falling back to geocoding or offset coordinates."""
        lat = exp.lat
        lng = exp.lng
        if lat == 0.0 and lng == 0.0:
            geo_res = await self._geocode_tool.run(location=f"{exp.name}, {location}")
            geo_lat = float(geo_res.get("lat", 0.0) or 0.0)
            geo_lng = float(geo_res.get("lng", 0.0) or 0.0)
            if geo_lat != 0.0 or geo_lng != 0.0:
                lat, lng = geo_lat, geo_lng
            else:
                lat = (base_lat or 0.0) + (index * 0.005)
                lng = (base_lng or 0.0) + (index * 0.005)

        return exp.model_copy(
            update={
                "lat": lat,
                "lng": lng,
                "source": "llm",
                "address": exp.address or location,
            }
        )

    def _build_fallback_experience(
        self,
        location: str,
        fallback_coords: tuple[float | None, float | None] | None = None,
    ) -> Experience:
        """Construct a minimal default experience if LLM curation fails to return items."""
        lat = fallback_coords[0] if fallback_coords and fallback_coords[0] else 0.0
        lng = fallback_coords[1] if fallback_coords and fallback_coords[1] else 0.0
        return Experience(
            name=f"Explore {location}",
            type="tourist_attraction",
            description=f"Discover the historic sights, vibrant streets, and local culture of {location}.",
            duration_hours=2.5,
            price_range="Free",
            lat=lat,
            lng=lng,
            best_time_to_visit="Morning",
            source="llm",
            rating=4.5,
            review_count=500,
            address=location,
        )
