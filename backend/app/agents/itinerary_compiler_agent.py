"""ItineraryCompilerAgent — Layer 5: absorb every upstream finding into day-wise output.

The compiler is a **synthesizer, never an author**. Research agents have already
found the places, venues, hotels, routes, prices and advisories; this agent's job
is to lay them out across the calendar and explain the choices.

The LLM may only:
  * assign a *named* candidate experience to a (day, slot),
  * assign a *named* candidate venue to a (day, meal),
  * rank those picks, and
  * write grounded prose (title, per-day summary, recommendation reasons).

Every factual value — price, rating, address, coordinate, URL, advisory, cost — is
copied verbatim from upstream state by ``ItineraryCompilerService``'s deterministic
``inject_*`` methods. The LLM's structured outputs (``app.models.itinerary_compilation``)
carry only names and day numbers, so fabricating a factual field is structurally
impossible; unrecognised names are dropped and logged.

The compiler never guesses a trip length: if ``state["dates"]`` is unresolved it
raises rather than defaulting, because trip duration must be clarified by the
orchestrator (Layer 0) before any paid external API call is made.

Pipeline:
  1. Resolve the route into stops + one day allocation per calendar day.
  2. Per stop: geo-cluster experiences, pre-gate opening hours, ask the LLM to pick.
  3. Assemble a flat ``list[TripDays]`` with continuous day numbering.
  4. Deterministic quality gate (opening hours + duration) over those days.
  5. Inject stays, transport, safety, budget and reviews from upstream state.
  6. Narrate (title + day summaries), build the ``Itinerary``, verify nothing dropped.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, cast

from langchain_core.messages import HumanMessage

from app.agents.base import AgentClarificationMixin
from app.config import settings
from app.llm import StructuredOutputError, get_llm, invoke_structured
from app.logging import get_agent_logger
from app.models.enums import AgentName, LogEvent
from app.models.itinerary import MEAL_TYPES, SLOT_NAMES, Experience, TripDays
from app.models.itinerary_compilation import DayPlan, FoodPick, RoutePlan, TripNarrative
from app.models.stops import DayAllocation, TripStop
from app.prompts.itinerary_compiler_agent_prompts import (
    DAY_PLAN_CHAT_PROMPT,
    NARRATIVE_CHAT_PROMPT,
)
from app.services.itinerary_compiler_service import ItineraryCompilerService, MissingTripDatesError
from app.tools.factory import ToolFactory


def _fallback_day_plan(day_count: int, food_candidates: list[str]) -> DayPlan:
    """Assign meals round-robin when the planning call fails.

    Venue selection is a lookup, not a judgement, so discarding an already-fetched
    venue pool because the activity plan failed leaves days with no meals at all.
    """
    if not food_candidates:
        return DayPlan()
    picks: list[FoodPick] = []
    cursor = 0
    for day_number in range(1, day_count + 1):
        for meal_type in MEAL_TYPES:
            picks.append(
                FoodPick(
                    day_number=day_number,
                    meal_type=meal_type,
                    venue_name=food_candidates[cursor % len(food_candidates)],
                )
            )
            cursor += 1
    return DayPlan(food=picks)


class ItineraryCompilerAgent(AgentClarificationMixin):
    """Layer 5 — absorbs upstream agent output into a day-wise itinerary.

    Owns the LLM calls and the tool-calling quality-gate loop. Every deterministic
    transform (route resolution, pool building, day assembly, injection, prose
    templating) lives in ``ItineraryCompilerService`` instead.
    """

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: Any | None = None,
        compiler: ItineraryCompilerService | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._cluster_tool = factory.get("cluster_by_proximity")
        self._opening_hours_tool = factory.get("enforce_opening_hours")
        self._duration_tool = factory.get("validate_day_duration")
        self._llm = llm or get_llm("itinerary_compiler")
        self._compiler = compiler or ItineraryCompilerService()

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        destination: str = state.get("destination", "")
        session_id: str = state.get("session_id", "")
        log = get_agent_logger("itinerary_compiler", session_id, destination=destination)

        try:
            route = self._compiler.resolve_route(state)
        except MissingTripDatesError as exc:
            log.error("missing_trip_dates", error=str(exc))
            return {"error": str(exc)}

        log.info(
            "agent_start",
            mode="multi_stop_provisional" if route.is_multi_stop else "single_destination",
            stops=len(route.stops),
            days=len(route.allocations),
        )

        days = await self._compile_all_stops(route, state, log)
        if not days:
            days = self._compiler.build_stub_days(destination, route.allocations)
        days.sort(key=lambda d: d.day_number)

        days = await self._run_quality_gate(days, state.get("dates"), log)
        transport_section, days = self._enrich(days, route, state)

        narrative = await self._narrate(state, days, log)
        days = self._compiler.apply_narrative(days, narrative)

        itinerary = self._compiler.build_itinerary(state, route, days, transport_section, narrative)
        itinerary = itinerary.model_copy(update={"created_at": datetime.now(tz=UTC)})

        dropped = self._compiler.assert_upstream_absorbed(itinerary, state)
        if dropped:
            log.warning("upstream_data_dropped", keys=dropped)

        log.info("agent_done", title=itinerary.title, days=len(itinerary.trip_days))
        return {"itinerary": itinerary}

    # ── Per-stop compilation ─────────────────────────────────────────────────

    async def _compile_all_stops(
        self, route: RoutePlan, state: dict[str, Any], log: Any
    ) -> list[TripDays]:
        """Compile every stop that has at least one allocated day, in parallel."""
        stops_with_days = [
            (stop, allocations)
            for stop in route.stops
            if (allocations := route.allocations_for(stop.stop_id))
        ]
        results = await asyncio.gather(
            *(
                self._compile_stop_days(stop, allocations, route, state, log)
                for stop, allocations in stops_with_days
            )
        )
        return [day for stop_days in results for day in stop_days]

    async def _compile_stop_days(
        self,
        stop: TripStop,
        allocations: list[DayAllocation],
        route: RoutePlan,
        state: dict[str, Any],
        log: Any,
    ) -> list[TripDays]:
        """Lay one stop's verified experience and food pools across its days.

        Structure (day count, order, stop identity) comes from the route contract,
        never from the LLM — the LLM only chooses which candidate goes where.
        """
        experiences = self._compiler.experiences_for_stop(state, stop.stop_id)
        food_pool = self._compiler.food_pool_for_stop(state, stop.stop_id)
        day_count = len(allocations)

        clusters = await self._cluster_experiences(experiences, day_count)
        closed_names = await self._closed_venue_names(clusters, day_count, state.get("dates"))
        experience_pool = {e.name: e for e in experiences if e.name not in closed_names}
        day_candidates = self._compiler.build_day_candidates(allocations, clusters, closed_names)

        plan = await self._plan_stop(stop, day_count, day_candidates, sorted(food_pool), log)
        dropped = self._compiler.count_unverified_picks(plan, experience_pool, food_pool)
        if dropped:
            log.warning("llm_picks_dropped", stop=stop.name, dropped=dropped)

        return self._compiler.assemble_trip_days(
            stop,
            allocations,
            plan,
            experience_pool,
            food_pool,
            stop_id=stop.stop_id if route.is_multi_stop else None,
            route_version=state.get("route_version") if route.is_multi_stop else None,
        )

    async def _cluster_experiences(
        self, experiences: list[Experience], day_count: int
    ) -> list[dict[str, Any]]:
        """Geo-cluster experiences by proximity into ``day_count`` groups."""
        exp_dicts = [
            {
                "name": e.name,
                "type": e.type,
                "description": e.description,
                "lat": e.lat,
                "lng": e.lng,
                "duration_hours": e.duration_hours,
                "rating": e.rating,
                "address": e.address,
                "opening_hours": e.opening_hours.model_dump() if e.opening_hours else None,
            }
            for e in experiences
        ]
        result = await self._cluster_tool.run(experiences=exp_dicts, num_clusters=day_count)
        return cast(list[dict[str, Any]], result.get("clusters", []))

    async def _closed_venue_names(
        self, clusters: list[dict[str, Any]], day_count: int, dates: Any
    ) -> set[str]:
        """Pre-gate: drop experiences that fail the opening-hours check before the LLM sees them."""
        slotted = [
            {**exp, "assigned_slot": SLOT_NAMES[index % 3], "day_index": day_index}
            for day_index, cluster in enumerate(clusters[:day_count])
            for index, exp in enumerate(cluster.get("experiences", []))
        ]
        result = await self._opening_hours_tool.run(experiences=slotted, travel_dates=dates)
        return {conflict["name"] for conflict in result.get("conflicts", [])}

    async def _plan_stop(
        self,
        stop: TripStop,
        day_count: int,
        day_candidates: list[dict[str, Any]],
        food_candidates: list[str],
        log: Any,
    ) -> DayPlan:
        if not any(c["experiences"] for c in day_candidates) and not food_candidates:
            return DayPlan()

        try:
            return await invoke_structured(
                self._llm,
                DayPlan,
                DAY_PLAN_CHAT_PROMPT.format_messages(
                    day_count=day_count,
                    stop_name=stop.name,
                    max_activities_per_day=settings.itinerary_max_activities_per_day,
                    meal_types="/".join(MEAL_TYPES),
                    day_candidates=json.dumps(day_candidates, indent=2),
                    food_candidates=json.dumps(food_candidates, indent=2),
                ),
                agent=AgentName.ITINERARY_COMPILER,
                log=log,
            )
        except StructuredOutputError as exc:
            log.warning(
                LogEvent.AGENT_DEGRADED,
                section="day_plan",
                stop_id=stop.stop_id,
                truncated=exc.truncated,
                error=str(exc),
            )
            # Food assignment needs no reasoning, so it must survive a failed plan
            # rather than leaving the stop with no meals at all.
            return _fallback_day_plan(day_count, food_candidates)

    # ── Deterministic quality gate (tool calls stay here; logic lives in the service) ──

    async def _run_quality_gate(self, days: list[TripDays], dates: Any, log: Any) -> list[TripDays]:
        """Re-check opening hours and day duration, dropping or trimming what fails."""
        for iteration in range(settings.itinerary_max_gate_iterations):
            hours_check = await self._opening_hours_tool.run(
                experiences=self._compiler.extract_scheduled_activities(days), travel_dates=dates
            )
            duration_check = await self._duration_tool.run(
                day_slots=self._compiler.extract_day_slots(days)
            )

            conflicts = hours_check.get("conflicts", [])
            flags = duration_check.get("flags", [])
            if not conflicts and not flags:
                return days

            log.info(
                "gate_resolving",
                iteration=iteration + 1,
                conflicts=len(conflicts),
                duration_flags=len(flags),
            )
            days = self._compiler.resolve_conflicts(days, {c["name"] for c in conflicts}, flags)
        log.warning("gate_max_iterations_reached")
        return days

    # ── Enrichment ────────────────────────────────────────────────────────────

    def _enrich(
        self, days: list[TripDays], route: RoutePlan, state: dict[str, Any]
    ) -> tuple[Any, list[TripDays]]:
        """Copy stays, transport, budget and reviews from upstream state onto each day."""
        days = self._compiler.inject_stays(days, state)
        transport_section, days = self._compiler.inject_transport(days, state)
        days = self._compiler.inject_budget(days, state.get("budget_report"))
        days = self._compiler.inject_reviews(days, state.get("reviews_summary", {}))
        return transport_section, days

    # ── Narrative ────────────────────────────────────────────────────────────

    async def _narrate(
        self, state: dict[str, Any], days: list[TripDays], log: Any
    ) -> TripNarrative:
        if not days:
            return TripNarrative()
        try:
            return await invoke_structured(
                self._llm,
                TripNarrative,
                NARRATIVE_CHAT_PROMPT.format_messages(
                    narrative_context=[
                        HumanMessage(content=self._compiler.build_narrative_context(state, days))
                    ]
                ),
                agent=AgentName.ITINERARY_COMPILER,
                log=log,
            )
        except StructuredOutputError as exc:
            log.warning(LogEvent.AGENT_DEGRADED, section="narrative", error=str(exc))
            return TripNarrative()
