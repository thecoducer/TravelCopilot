"""ItineraryCompilerService — the deterministic half of itinerary compilation.

``ItineraryCompilerAgent`` owns the LLM calls and the tool-calling quality-gate
loop; every pure transform lives here instead, so it can be unit tested without
mocking an LLM. Nothing in this module makes a network call, calls a tool, or
calls an LLM — it only resolves routes, builds candidate pools, assembles days,
and copies upstream agent output onto them.

Every value this service writes onto a ``TripDays`` is either:
  * read verbatim from upstream agent state (stays, transport, safety, budget,
    reviews), or
  * looked up by exact name from a verified candidate pool, in response to a
    name the compiler's LLM chose.
It never invents a fact. See ``ItineraryCompilerAgent``'s module docstring for
the full synthesizer contract.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote_plus

import structlog

from app.config import settings
from app.models.itinerary import (
    MEAL_TYPES,
    SLOT_NAMES,
    ActivityOption,
    DaySafetyBriefing,
    Experience,
    FoodOptions,
    FoodVenue,
    Itinerary,
    Place,
    StayOptions,
    TimeSlotOptions,
    TransportOptions,
    TransportSection,
    TripDays,
)
from app.models.itinerary_compilation import (
    SINGLE_STOP_ID,
    ActivityPick,
    DayPlan,
    RoutePlan,
    TripNarrative,
)
from app.models.reports import BudgetReport, SafetyReport
from app.models.stops import DayAllocation, RouteLegPlan, TripStop, stop_display_name
from app.models.transport import StayOption, TransportRecommendation

logger = structlog.get_logger(__name__)


class MissingTripDatesError(ValueError):
    """Raised when the compiler is asked to run before trip dates are resolved.

    The compiler must never guess a trip length — that decision belongs to the
    orchestrator's clarification gate (Layer 0), which runs long before any
    paid external API call is made.
    """


class ItineraryCompilerService:
    """Pure, stateless transforms used to compile an ``Itinerary`` from agent state."""

    # ── Route resolution ─────────────────────────────────────────────────────

    def resolve_route(self, state: dict[str, Any]) -> RoutePlan:
        """Resolve the trip into ordered stops and exactly one allocation per day.

        Single-destination trips are modelled as a one-stop route so both trip
        shapes share the same compilation path.
        """
        dates = state.get("dates")
        if dates is None:
            raise MissingTripDatesError(
                "Cannot compile an itinerary without resolved trip dates — "
                "trip duration must be clarified before Layer 5 runs."
            )

        multi_stop = self._resolve_multi_stop_route(state, dates.departure)
        if multi_stop is not None:
            return multi_stop
        return self._resolve_single_stop_route(state, dates.departure, dates.trip_days)

    def _resolve_multi_stop_route(
        self, state: dict[str, Any], start_date: date
    ) -> RoutePlan | None:
        if state.get("route_discovery_status") != "multi_stop_provisional":
            return None

        stops_by_id: dict[str, TripStop] = state.get("stops", {}) or {}
        overnight = sorted(
            (s for s in stops_by_id.values() if s.stop_kind == "overnight"),
            key=lambda s: s.sequence,
        )
        if not overnight:
            return None

        stops_by_day: dict[int, DayAllocation] = state.get("stops_by_day", {}) or {}
        allocations = [alloc for _index, alloc in sorted(stops_by_day.items())]
        return RoutePlan(
            stops=overnight,
            allocations=allocations or self._derive_allocations(overnight, start_date),
            is_multi_stop=True,
        )

    def _resolve_single_stop_route(
        self, state: dict[str, Any], start_date: date, day_count: int
    ) -> RoutePlan:
        single_stop = TripStop(
            stop_id=SINGLE_STOP_ID,
            name=state.get("destination", ""),
            sequence=0,
            nights=day_count,
            arrival_date=start_date,
            departure_date=start_date + timedelta(days=max(0, day_count - 1)),
        )
        allocations = [
            DayAllocation(
                day_index=index,
                date=start_date + timedelta(days=index),
                stop_id=SINGLE_STOP_ID,
                is_checkin_day=index == 0,
                is_checkout_day=index == day_count - 1,
            )
            for index in range(day_count)
        ]
        return RoutePlan(stops=[single_stop], allocations=allocations, is_multi_stop=False)

    def _derive_allocations(self, stops: list[TripStop], start_date: date) -> list[DayAllocation]:
        """Fallback day allocation when route discovery produced no ``stops_by_day``."""
        allocations: list[DayAllocation] = []
        day_index = 0
        for stop in stops:
            nights = max(1, stop.nights)
            for night in range(nights):
                anchor = stop.arrival_date or start_date + timedelta(days=day_index - night)
                allocations.append(
                    DayAllocation(
                        day_index=day_index,
                        date=anchor + timedelta(days=night),
                        stop_id=stop.stop_id,
                        is_checkin_day=night == 0,
                        is_checkout_day=night == nights - 1,
                    )
                )
                day_index += 1
        return allocations

    # ── Candidate pools ──────────────────────────────────────────────────────

    def experiences_for_stop(self, state: dict[str, Any], stop_id: str) -> list[Experience]:
        """Return the verified experiences found for this stop (or the single-stop fallback)."""
        by_stop: dict[str, list[Experience]] = state.get("experiences_raw_by_stop", {}) or {}
        return by_stop.get(stop_id) or (state.get("experiences_raw", []) if not by_stop else [])

    def food_pool_for_stop(self, state: dict[str, Any], stop_id: str) -> dict[str, FoodVenue]:
        """Flatten this stop's discovered food venues into a name-keyed pool."""
        by_stop: dict[str, dict[str, list[Any]]] = (
            state.get("food_recommendations_by_stop", {}) or {}
        )
        food_by_date = by_stop.get(stop_id) or (
            state.get("food_recommendations", {}) if not by_stop else {}
        )
        pool: dict[str, FoodVenue] = {}
        for options in food_by_date.values():
            for food_opt in options:
                venues = (
                    food_opt.get("options", []) if isinstance(food_opt, dict) else food_opt.options
                )
                for venue in venues or []:
                    venue_obj = venue if isinstance(venue, FoodVenue) else FoodVenue(**venue)
                    pool.setdefault(venue_obj.name, venue_obj)
        return pool

    def build_day_candidates(
        self,
        allocations: list[DayAllocation],
        clusters: list[dict[str, Any]],
        closed_names: set[str],
    ) -> list[dict[str, Any]]:
        """Build the per-day candidate-name lists shown to the LLM (closed venues excluded)."""
        return [
            {
                "day_number": allocations[index].day_index + 1,
                "experiences": [
                    exp.get("name")
                    for exp in cluster.get("experiences", [])
                    if exp.get("name") not in closed_names
                ],
            }
            for index, cluster in enumerate(clusters[: len(allocations)])
        ]

    def count_unverified_picks(
        self,
        plan: DayPlan,
        experience_pool: dict[str, Experience],
        food_pool: dict[str, FoodVenue],
    ) -> int:
        """Count LLM picks naming something no upstream agent found."""
        unknown_activities = sum(
            1 for pick in plan.activities if pick.experience_name not in experience_pool
        )
        unknown_venues = sum(1 for pick in plan.food if pick.venue_name not in food_pool)
        return unknown_activities + unknown_venues

    # ── Assembly ──────────────────────────────────────────────────────────────

    def assemble_trip_days(
        self,
        stop: TripStop,
        allocations: list[DayAllocation],
        plan: DayPlan,
        experience_pool: dict[str, Experience],
        food_pool: dict[str, FoodVenue],
        stop_id: str | None,
        route_version: int | None,
    ) -> list[TripDays]:
        """Lay the LLM's picks onto the route's days, copying every fact from the pools."""
        return [
            self._assemble_one_day(
                stop, alloc, plan, experience_pool, food_pool, stop_id, route_version
            )
            for alloc in allocations
        ]

    def _assemble_one_day(
        self,
        stop: TripStop,
        alloc: DayAllocation,
        plan: DayPlan,
        experience_pool: dict[str, Experience],
        food_pool: dict[str, FoodVenue],
        stop_id: str | None,
        route_version: int | None,
    ) -> TripDays:
        day_number = alloc.day_index + 1
        slots = self._pick_activities(plan, experience_pool, day_number)
        food_options = [
            FoodOptions(
                meal_type=meal_type,
                options=[venue]
                if (venue := self._pick_venue(plan, food_pool, day_number, meal_type))
                else [],
            )
            for meal_type in MEAL_TYPES
        ]
        return TripDays(
            day_number=day_number,
            date=alloc.date,
            location=stop.name,
            morning=TimeSlotOptions(slot="morning", options=slots["morning"]),
            afternoon=TimeSlotOptions(slot="afternoon", options=slots["afternoon"]),
            evening=TimeSlotOptions(slot="evening", options=slots["evening"]),
            food_options=food_options,
            permits_required=list(stop.permits_required),
            altitude_meters=stop.altitude_meters,
            drive_notes=stop.notes,
            stop_id=stop_id,
            route_version=route_version,
            is_travel_day=alloc.is_travel_day,
            is_checkin_day=alloc.is_checkin_day,
            is_checkout_day=alloc.is_checkout_day,
        )

    def _pick_activities(
        self, plan: DayPlan, experience_pool: dict[str, Experience], day_number: int
    ) -> dict[str, list[ActivityOption]]:
        slots: dict[str, list[ActivityOption]] = {slot: [] for slot in SLOT_NAMES}
        for pick in plan.activities:
            if pick.day_number != day_number or pick.slot not in slots:
                continue
            experience = experience_pool.get(pick.experience_name)
            if not experience:
                continue  # deterministic guard — drop names not in the verified pool
            slots[pick.slot].append(
                self._activity_option_from_experience(experience, len(slots[pick.slot]) + 1, pick)
            )
        return slots

    def _activity_option_from_experience(
        self, experience: Experience, rank: int, pick: ActivityPick
    ) -> ActivityOption:
        query = quote_plus(f"{experience.name} {experience.address or ''}".strip())
        place = Place(
            name=experience.name,
            description=experience.description,
            category=experience.type,
            duration_minutes=max(0, int(experience.duration_hours * 60)),
            price_range=experience.price_range,
            lat=experience.lat,
            lng=experience.lng,
            address=experience.address or "",
            photos=experience.photos,
            google_maps_url=experience.google_maps_url,
            more_images_url=f"https://www.google.com/search?tbm=isch&q={query}",
            youtube_search_url=f"https://www.youtube.com/results?search_query={query}",
            opening_hours=experience.opening_hours,
            rating=experience.rating,
            review_count=experience.review_count,
        )
        return ActivityOption(
            place=place,
            rank=rank,
            recommendation_reason=pick.recommendation_reason,
            best_for=pick.best_for,
            estimated_duration_minutes=max(0, int(experience.duration_hours * 60)),
            source=experience.source,
        )

    def _pick_venue(
        self, plan: DayPlan, food_pool: dict[str, FoodVenue], day_number: int, meal_type: str
    ) -> FoodVenue | None:
        return next(
            (
                food_pool[pick.venue_name]
                for pick in plan.food
                if pick.day_number == day_number
                and pick.meal_type == meal_type
                and pick.venue_name in food_pool
            ),
            None,
        )

    def build_stub_days(self, destination: str, allocations: list[DayAllocation]) -> list[TripDays]:
        """Minimal empty days so a failed compile still returns a well-formed trip."""
        return [
            TripDays(day_number=a.day_index + 1, date=a.date, location=destination)
            for a in allocations
        ]

    # ── Quality gate (pure parts — the agent owns the tool-calling loop) ────

    def extract_scheduled_activities(self, days: list[TripDays]) -> list[dict[str, Any]]:
        """Flatten every scheduled activity with its slot, for the opening-hours gate."""
        return [
            {
                "name": option.place.name,
                "assigned_slot": slot.slot,
                "opening_hours": (
                    option.place.opening_hours.model_dump() if option.place.opening_hours else None
                ),
            }
            for day in days
            for slot in (day.morning, day.afternoon, day.evening)
            for option in slot.options
        ]

    def extract_day_slots(self, days: list[TripDays]) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """Per-day, per-slot duration summary, for the day-duration gate."""
        return {
            day.date.isoformat(): {
                slot.slot: [
                    {
                        "duration_hours": option.estimated_duration_minutes / 60.0,
                        "name": option.place.name,
                    }
                    for option in slot.options
                ]
                for slot in (day.morning, day.afternoon, day.evening)
            }
            for day in days
        }

    def resolve_conflicts(
        self,
        days: list[TripDays],
        conflict_names: set[str],
        duration_flags: list[dict[str, Any]],
    ) -> list[TripDays]:
        """Deterministically fix opening-hours conflicts and over-packed slots."""
        flagged_slots: set[tuple[str, str]] = {
            (flag["day"], flag.get("slot", ""))
            for flag in duration_flags
            if flag.get("slot") in SLOT_NAMES
        }
        return _map_days(
            days, lambda day: self._resolve_day_conflicts(day, conflict_names, flagged_slots)
        )

    def _resolve_day_conflicts(
        self, day: TripDays, conflict_names: set[str], flagged_slots: set[tuple[str, str]]
    ) -> TripDays:
        day_key = day.date.isoformat()
        new_slots: dict[str, TimeSlotOptions] = {}
        for slot in (day.morning, day.afternoon, day.evening):
            clean_options = [o for o in slot.options if o.place.name not in conflict_names]
            if (day_key, slot.slot) in flagged_slots:
                clean_options = clean_options[: settings.itinerary_max_activities_per_slot]
            unresolved_note = (
                "Some activities could not be scheduled at this time — please verify availability."
                if len(clean_options) < len(slot.options)
                else slot.unresolved_note
            )
            new_slots[slot.slot] = slot.model_copy(
                update={"options": clean_options, "unresolved_note": unresolved_note}
            )
        return day.model_copy(update=new_slots)

    # ── Enrichment — every value below is copied verbatim from upstream state ─

    def inject_stays(self, days: list[TripDays], state: dict[str, Any]) -> list[TripDays]:
        """Attach each day's accommodation options, repeated across multi-night stays."""
        shortlist_by_stop: dict[str, list[StayOption]] = (
            state.get("stays_shortlist_by_stop", {}) or {}
        )
        pick_by_stop: dict[str, StayOption] = state.get("stays_pick_by_stop", {}) or {}
        fallback_options: list[StayOption] = (
            state.get("stays_shortlist") or state.get("stays_raw") or []
        )
        fallback_pick: StayOption | None = state.get("stays_pick")
        nights_by_stop = Counter(day.stop_id for day in days)

        def _attach(day: TripDays) -> TripDays | None:
            options = (
                shortlist_by_stop.get(day.stop_id) if day.stop_id is not None else None
            ) or fallback_options
            if not options:
                return None
            recommended = (
                pick_by_stop.get(day.stop_id) if day.stop_id is not None else None
            ) or fallback_pick
            reference = recommended or options[0]
            return day.model_copy(
                update={
                    "stay_options": StayOptions(
                        location=day.location,
                        options=list(options),
                        recommended=recommended,
                        notes=f"{len(options)} budget-filtered option(s) in {day.location}.",
                        stop_id=day.stop_id,
                        nights_at_location=nights_by_stop[day.stop_id],
                        is_checkin_day=day.is_checkin_day,
                        is_checkout_day=day.is_checkout_day,
                        check_in=reference.check_in,
                        check_out=reference.check_out,
                    )
                }
            )

        return _map_days(days, _attach)

    def inject_transport(
        self, days: list[TripDays], state: dict[str, Any]
    ) -> tuple[TransportSection | None, list[TripDays]]:
        """Build the trip-level transport view and attach each leg to the day it departs."""
        recommended: TransportRecommendation | None = state.get("transport_recommendation")
        alternatives: list[TransportRecommendation] = state.get("transport_alternatives", []) or []
        by_leg: dict[str, TransportRecommendation] = (
            state.get("transport_recommendation_by_leg", {}) or {}
        )
        route_legs: dict[str, RouteLegPlan] = state.get("route_legs", {}) or {}
        stops: dict[str, TripStop] = state.get("stops", {}) or {}
        source: str = state.get("source", "")

        section = (
            TransportSection(
                recommended=recommended, alternatives=list(alternatives), by_leg=dict(by_leg)
            )
            if recommended or by_leg
            else None
        )
        by_day = self._transport_options_by_day(
            days, route_legs, by_leg, stops, source, recommended, alternatives
        )

        def _attach(day: TripDays) -> TripDays | None:
            day_legs = by_day[day.day_number]
            if not day_legs and not day.is_travel_day:
                return None
            return day.model_copy(
                update={
                    "transport_options": day_legs,
                    "leg_id": day_legs[0].leg_id if day_legs else day.leg_id,
                    "is_travel_day": day.is_travel_day or bool(day_legs),
                }
            )

        return section, _map_days(days, _attach)

    def _transport_options_by_day(
        self,
        days: list[TripDays],
        route_legs: dict[str, RouteLegPlan],
        by_leg: dict[str, TransportRecommendation],
        stops: dict[str, TripStop],
        source: str,
        recommended: TransportRecommendation | None,
        alternatives: list[TransportRecommendation],
    ) -> dict[int, list[TransportOptions]]:
        by_day: dict[int, list[TransportOptions]] = defaultdict(list)
        for leg in sorted(route_legs.values(), key=lambda leg: leg.sequence):
            leg_rec = by_leg.get(leg.leg_id)
            by_day[leg.travel_day_index + 1].append(
                TransportOptions(
                    origin=stop_display_name(leg.origin_stop_id, stops, source),
                    destination=stop_display_name(leg.destination_stop_id, stops, source),
                    leg_id=leg.leg_id,
                    leg_type=leg.leg_type,
                    departure_date=leg.planned_departure_date,
                    recommended=leg_rec,
                    mode_downgraded=leg.policy.mode_downgraded
                    or (leg_rec.mode_downgraded if leg_rec else False),
                    no_result=leg_rec.no_result if leg_rec else True,
                )
            )

        # Single-destination trips have no route_legs — the aggregate recommendation
        # is the only transfer, and it departs on the first day.
        if not route_legs and recommended and days:
            by_day[days[0].day_number].append(
                TransportOptions(
                    origin=source,
                    destination=days[0].location,
                    departure_date=days[0].date,
                    recommended=recommended,
                    alternatives=list(alternatives),
                    mode_downgraded=recommended.mode_downgraded,
                    no_result=recommended.no_result,
                )
            )
        return by_day

    def inject_safety(
        self,
        days: list[TripDays],
        safety_report: SafetyReport | None,
        stops_by_id: dict[str, TripStop],
    ) -> list[TripDays]:
        """Copy the safety report onto every day, with a per-day altitude warning."""
        if not safety_report:
            return days
        summary = self.render_safety_briefing(safety_report)

        def _attach(day: TripDays) -> TripDays:
            stop = stops_by_id.get(day.stop_id) if day.stop_id is not None else None
            altitude = (
                (stop.altitude_meters if stop else None)
                or day.altitude_meters
                or safety_report.altitude_meters
            )
            warning = self._altitude_warning(altitude, day, safety_report)
            return day.model_copy(
                update={
                    "safety_briefing": DaySafetyBriefing(
                        summary=summary,
                        advisory_level=safety_report.advisory_level,
                        seasonal_weather_summary=safety_report.seasonal_weather_summary,
                        crowd_level=safety_report.crowd_level,
                        seasonal_risks=list(safety_report.seasonal_risks),
                        altitude_meters=altitude,
                        altitude_warning=warning,
                        acclimatization_advice=safety_report.acclimatization_advice,
                        top_scams=list(safety_report.top_scams),
                        emergency_contacts=dict(safety_report.emergency_contacts),
                        women_safety_notes=safety_report.women_safety_notes,
                        medical_facilities=safety_report.medical_facilities,
                    ),
                    "altitude_meters": altitude,
                    "altitude_warning": warning,
                }
            )

        return _map_days(days, _attach)

    def _altitude_warning(
        self, altitude: int | None, day: TripDays, safety_report: SafetyReport
    ) -> str | None:
        if not altitude or altitude < settings.high_altitude_warning_meters:
            return None
        if not (day.is_checkin_day or day.is_travel_day):
            return None
        return (
            safety_report.acclimatization_advice
            or f"Arriving at {altitude} m — keep the first hours light and hydrate."
        )

    def render_safety_briefing(self, report: SafetyReport) -> str:
        """Deterministic prose summary of a ``SafetyReport`` — never LLM-authored."""
        parts = [f"Advisory: {report.advisory_level}."]
        if report.seasonal_weather_summary:
            parts.append(report.seasonal_weather_summary)
        if report.crowd_level:
            parts.append(f"Crowds: {report.crowd_level}.")
        if report.top_scams:
            scam_names = ", ".join(
                s.name for s in report.top_scams[: settings.itinerary_max_scams_in_briefing]
            )
            parts.append(f"Watch out for: {scam_names}.")
        if report.acclimatization_advice:
            parts.append(report.acclimatization_advice)
        return " ".join(parts)

    def inject_budget(
        self, days: list[TripDays], budget_report: BudgetReport | None
    ) -> list[TripDays]:
        """Copy each day's estimated cost from ``BudgetReport.per_day_breakdown``."""
        if not budget_report or not budget_report.per_day_breakdown:
            return days
        per_day = budget_report.per_day_breakdown

        def _attach(day: TripDays) -> TripDays | None:
            index = day.day_number - 1
            if index >= len(per_day):
                return None
            return day.model_copy(
                update={
                    "estimated_cost": per_day[index],
                    "currency_code": budget_report.currency_code,
                }
            )

        return _map_days(days, _attach)

    def inject_reviews(
        self, days: list[TripDays], reviews_summary: dict[str, Any]
    ) -> list[TripDays]:
        """Attach reviews for the places actually scheduled on each day."""
        if not reviews_summary:
            return days
        reviews = list(reviews_summary.values())

        def _attach(day: TripDays) -> TripDays | None:
            scheduled = {
                option.place.name
                for slot in (day.morning, day.afternoon, day.evening)
                for option in slot.options
            }
            scheduled |= {venue.name for food in day.food_options for venue in food.options}
            if day.stay_options:
                scheduled |= {stay.name for stay in day.stay_options.options}

            matched = [
                review
                for review in reviews
                if review.place_name in scheduled
                and (review.stop_id is None or review.stop_id == day.stop_id)
            ]
            return day.model_copy(update={"review_highlights": matched}) if matched else None

        return _map_days(days, _attach)

    def build_reality_banner(
        self, safety_report: SafetyReport | None, budget_report: BudgetReport | None
    ) -> str | None:
        """Templated from upstream verdicts — never LLM prose."""
        parts: list[str] = []
        if safety_report:
            if safety_report.season_label:
                parts.append(f"{safety_report.season_label} season")
            if safety_report.crowd_level:
                parts.append(f"{safety_report.crowd_level.lower()} crowds")
            if safety_report.seasonal_weather_summary:
                parts.append(safety_report.seasonal_weather_summary.rstrip("."))
        if budget_report:
            parts.append(
                f"estimated {budget_report.total_estimated_cost:,.0f} "
                f"{budget_report.currency_code} ({budget_report.vs_budget_verdict})"
            )
        return " · ".join(parts) if parts else None

    # ── Narrative ─────────────────────────────────────────────────────────────

    def build_narrative_context(self, state: dict[str, Any], days: list[TripDays]) -> str:
        """Digest of what is already scheduled — the only material the narrator may use."""
        dates = state.get("dates")
        route = " → ".join(dict.fromkeys(day.location for day in days))
        parts: list[str] = [
            f"Trip: {state.get('travelers', 1)} traveler(s), {len(days)} days",
            f"Route: {state.get('source', '')} → {route}",
        ]
        if dates:
            parts.append(f"Start date: {dates.departure}")

        safety_report = state.get("safety_report")
        if safety_report:
            parts.append(
                f"Season: {safety_report.season_label}, crowds: {safety_report.crowd_level}, "
                f"weather: {safety_report.seasonal_weather_summary}, "
                f"altitude: {safety_report.altitude_meters} m, "
                f"seasonal risks: {', '.join(safety_report.seasonal_risks)}"
            )

        user_profile = state.get("user_profile")
        if user_profile and user_profile.interests:
            parts.append(f"Traveller interests: {', '.join(user_profile.interests)}")

        parts.extend(self._describe_day(day) for day in days)
        return "\n".join(parts)

    def _describe_day(self, day: TripDays) -> str:
        activities = ", ".join(
            option.place.name
            for slot in (day.morning, day.afternoon, day.evening)
            for option in slot.options
        )
        meals = ", ".join(food.options[0].name for food in day.food_options if food.options)
        travel_marker = " — travel day" if day.is_travel_day else ""
        return (
            f"Day {day.day_number} ({day.date}) in {day.location}{travel_marker}: "
            f"activities=[{activities}] meals=[{meals}]"
        )

    def apply_narrative(self, days: list[TripDays], narrative: TripNarrative) -> list[TripDays]:
        """Attach the LLM's per-day summaries — the only free-text the LLM contributes."""
        summaries = {s.day_number: s.summary for s in narrative.day_summaries}
        return _map_days(
            days,
            lambda day: (
                day.model_copy(update={"summary": summaries[day.day_number]})
                if day.day_number in summaries
                else None
            ),
        )

    # ── Final assembly ────────────────────────────────────────────────────────

    def build_itinerary(
        self,
        state: dict[str, Any],
        route: RoutePlan,
        days: list[TripDays],
        transport_section: TransportSection | None,
        narrative: TripNarrative,
    ) -> Itinerary:
        destination: str = state.get("destination", "")
        destination_names = [s.name for s in route.stops] if route.is_multi_stop else [destination]
        safety_report: SafetyReport | None = state.get("safety_report")
        budget_report: BudgetReport | None = state.get("budget_report")
        route_legs: dict[str, RouteLegPlan] = state.get("route_legs", {}) or {}

        default_title = f"{len(days)} Days: {' → '.join(destination_names)}"
        title = (narrative.title or default_title)[: settings.itinerary_max_title_length]

        return Itinerary(
            title=title,
            source=state.get("source", ""),
            destination=route.stops[-1].name
            if route.is_multi_stop and route.stops
            else destination,
            destinations=destination_names,
            dates=state.get("dates"),
            travelers=state.get("travelers", 1),
            trip_days=days,
            stops=list(route.stops) if route.is_multi_stop else [],
            route_legs=sorted(route_legs.values(), key=lambda leg: leg.sequence),
            route_version=state.get("route_version") if route.is_multi_stop else None,
            route_discovery_status=state.get("route_discovery_status"),
            transport_section=transport_section,
            safety_section=safety_report,
            safety_briefing=self.render_safety_briefing(safety_report) if safety_report else None,
            visa_section=state.get("visa_report"),
            self_drive_section=state.get("self_drive_report"),
            budget_breakdown=budget_report,
            reality_banner=self.build_reality_banner(safety_report, budget_report),
            packing_tips=narrative.packing_tips,
            permits_required=list(
                dict.fromkeys(permit for day in days for permit in day.permits_required)
            ),
            source_query=state.get("query", ""),
        )

    # Upstream state keys paired with the check that they reached the itinerary.
    _UPSTREAM_ABSORPTION_CHECKS: dict[str, Callable[[Itinerary], bool]] = {
        "safety_report": lambda it: it.safety_section is not None,
        "visa_report": lambda it: it.visa_section is not None,
        "budget_report": lambda it: it.budget_breakdown is not None,
        "self_drive_report": lambda it: it.self_drive_section is not None,
        "transport_recommendation": lambda it: it.transport_section is not None,
        "transport_recommendation_by_leg": lambda it: bool(
            it.transport_section and it.transport_section.by_leg
        ),
        "route_legs": lambda it: bool(it.route_legs),
        "stays_shortlist": lambda it: any(d.stay_options for d in it.trip_days),
        "stays_shortlist_by_stop": lambda it: any(d.stay_options for d in it.trip_days),
        "reviews_summary": lambda it: any(d.review_highlights for d in it.trip_days),
    }

    def assert_upstream_absorbed(self, itinerary: Itinerary, state: dict[str, Any]) -> list[str]:
        """Return the upstream state keys that produced data but never reached the itinerary."""
        return [
            key
            for key, reached in self._UPSTREAM_ABSORPTION_CHECKS.items()
            if state.get(key) and not reached(itinerary)
        ]


def _map_days(
    days: list[TripDays], transform: Callable[[TripDays], TripDays | None]
) -> list[TripDays]:
    """Apply ``transform`` to each day; a ``None`` result keeps the original day unchanged."""
    return [transform(day) or day for day in days]
