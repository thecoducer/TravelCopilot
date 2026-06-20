"""ItineraryCompilerAgent — Layer 5: geo-cluster → compile → deterministic gate → finalise.

Pipeline:
  1. Geo-cluster ``experiences_raw`` by proximity into ``trip_days`` groups.
  2. Pre-gate: run ``EnforceOpeningHoursTool`` (A) + ``ValidateDayDurationTool`` (B)
     on clustered experiences; resolve conflicts deterministically before LLM sees them.
  3. First LLM call: compile full ``Itinerary`` with ``personalization_reason`` per
     activity option, stay option, and transport option (C).
  4. Second LLM call (soft self-critique): reorder/swap for awkward gaps, rain
     days, and pacing — never adds new places.
  5. Deterministic final gate (I): re-run (A) + (B) on compiled itinerary.
     Auto-resolve conflicts (swap slot / trim / mark unresolved) up to 3 iterations.
  6. Stamp metadata and return.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm import get_llm
from app.models.itinerary import (
    Day,
    Itinerary,
    StayOptions,
    TimeSlotOptions,
    TransportSection,
    TripSegment,
)
from app.models.transport import StayOption
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)

_COMPILE_PROMPT = """\
You are an expert itinerary planner. Compile a complete itinerary from the data below.

Rules:
- ``title``: evocative, mentions destination + duration.
- ``reality_banner``: 1–2 sentence crowd/weather/cost summary.
- Each ``Day`` must have morning/afternoon/evening ``TimeSlotOptions``, each with 2–3
  ranked ``ActivityOption`` objects.  Rank 1 = top pick; ranks 2–3 = swap alternatives.
- ``ActivityOption.recommendation_reason``: why this place matches the traveller's interests (C).
- ``ActivityOption.best_for``: list of tags, e.g. ["photography", "families"].
- ``food``: list of 3 ``FoodOptions`` entries per day — breakfast/lunch/dinner.
- ``safety_briefing``: 2–3 sentence summary from scam report.
- Do NOT invent places not in the provided experience list.
- Populate ``itinerary.transport_section`` from the transport data.
- Populate each segment's ``stay_options`` from the shortlisted hotels.
"""

_CRITIQUE_PROMPT = """\
Review this itinerary for soft quality issues only.

Check:
1. Awkward schedule gaps (> 2h between activities in same area)?
2. Outdoor activities on days with severe weather risk mentioned in the destination context?
3. Pace too aggressive for the traveller count or trip length?

Return:
{{
  "has_issues": true/false,
  "suggestions": ["short suggestion 1", ...]
}}
Keep suggestions brief and actionable. If no issues, return {{"has_issues": false, "suggestions": []}}.
"""

_MAX_GATE_ITERATIONS = 3
_SLOT_NAMES = ["morning", "afternoon", "evening"]


class _CritiqueSuggestions(BaseModel):
    has_issues: bool = False
    suggestions: list[str] = Field(default_factory=list)


class ItineraryCompilerAgent:
    """Layer 5 — Full itinerary compilation with deterministic quality gates."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: object | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._cluster_tool = factory.get("cluster_by_proximity")
        self._opening_hours_tool = factory.get("enforce_opening_hours")
        self._duration_tool = factory.get("validate_day_duration")
        self._llm = llm or get_llm("itinerary_compiler")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        destination: str = state.get("destination", "")
        source: str = state.get("source", "")
        dates = state.get("dates")
        travelers: int = state.get("travelers", 1)
        session_id: str = state.get("session_id", "")

        experiences_raw = state.get("experiences_raw", [])
        transport_rec = state.get("transport_recommendation")
        transport_alts = state.get("transport_alternatives", [])
        stays_shortlist: list[StayOption] = state.get("stays_shortlist", [])
        destination_ctx = state.get("destination_context_report")
        scam_report = state.get("scam_safety_report")
        visa_report = state.get("visa_report")
        self_drive_report = state.get("self_drive_report")
        budget_report = state.get("budget_report")
        reviews_summary = state.get("reviews_summary", {})
        restaurant_recs = state.get("restaurant_recommendations", {})
        user_profile = state.get("user_profile")

        log = logger.bind(agent="itinerary_compiler", destination=destination, session_id=session_id)
        log.info("agent_start", experiences=len(experiences_raw), stays=len(stays_shortlist))

        trip_days = dates.trip_days if dates else 3
        start_date = dates.departure if dates else date.today()

        # ── Step 1: Geo-cluster experiences ──────────────────────────────────
        exp_dicts = [
            {
                "name": e.name,
                "type": e.type,
                "description": e.description,
                "lat": e.lat,
                "lng": e.lng,
                "duration_hours": e.duration_hours,
                "rating": e.rating,
                "google_maps_url": e.google_maps_url,
                "address": e.address,
                "opening_hours": e.opening_hours.model_dump() if e.opening_hours else None,
            }
            for e in experiences_raw
        ]
        cluster_result = await self._cluster_tool.run(
            experiences=exp_dicts, num_clusters=trip_days
        )
        clusters: list[dict[str, Any]] = cluster_result.get("clusters", [])

        # ── Step 2: Pre-gate — resolve opening-hours + duration issues ────────
        # Assign each experience its intended slot for pre-check
        slotted_exps: list[dict[str, Any]] = []
        for ci, cluster in enumerate(clusters[:trip_days]):
            cluster_exps = cluster.get("experiences", [])
            for ei, exp in enumerate(cluster_exps):
                slot = _SLOT_NAMES[ei % 3]
                slotted_exps.append({**exp, "assigned_slot": slot, "day_index": ci})

        hours_pre = await self._opening_hours_tool.run(
            experiences=slotted_exps, travel_dates=dates
        )
        closed_names: set[str] = {c["name"] for c in hours_pre.get("conflicts", [])}

        # Build day_slots for duration check
        day_slots: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for ci, cluster in enumerate(clusters[:trip_days]):
            day_key = (start_date + timedelta(days=ci)).isoformat()
            cluster_exps = cluster.get("experiences", [])
            slots: dict[str, list[dict[str, Any]]] = {s: [] for s in _SLOT_NAMES}
            for ei, exp in enumerate(cluster_exps):
                if exp.get("name") not in closed_names:
                    slots[_SLOT_NAMES[ei % 3]].append(exp)
            day_slots[day_key] = slots

        duration_pre = await self._duration_tool.run(day_slots=day_slots)
        # Trim over-packed slots pre-LLM
        for flag in duration_pre.get("flags", []):
            day = flag["day"]
            slot = flag.get("slot")
            if slot in _SLOT_NAMES and day in day_slots:
                excess = flag.get("excess_activities", 1)
                while excess > 0 and day_slots[day][slot]:
                    day_slots[day][slot].pop()
                    excess -= 1

        # Clean clusters removing closed venues
        clean_clusters = []
        for ci, cluster in enumerate(clusters[:trip_days]):
            clean_exps = [e for e in cluster.get("experiences", []) if e.get("name") not in closed_names]
            clean_clusters.append({**cluster, "experiences": clean_exps})

        # ── Step 3: LLM compile ───────────────────────────────────────────────
        context = _build_context(
            source=source, destination=destination, trip_days=trip_days,
            start_date=str(start_date), travelers=travelers,
            clusters=clean_clusters, transport_rec=transport_rec, transport_alts=transport_alts,
            stays_shortlist=stays_shortlist, destination_ctx=destination_ctx,
            scam_report=scam_report, visa_report=visa_report,
            self_drive_report=self_drive_report, budget_report=budget_report,
            reviews_summary=reviews_summary, restaurant_recs=restaurant_recs,
            user_profile=user_profile,
        )

        chain = self._llm.with_structured_output(Itinerary)  # type: ignore[union-attr]
        try:
            itinerary: Itinerary = chain.invoke(
                [SystemMessage(content=_COMPILE_PROMPT), HumanMessage(content=context)]
            )
        except Exception as exc:
            log.error("compile_failed", error=str(exc))
            itinerary = _build_stub(source, destination, start_date, trip_days, travelers)

        # ── Step 4: Self-critique (soft qualities only) ───────────────────────
        try:
            crit_chain = self._llm.with_structured_output(_CritiqueSuggestions)  # type: ignore[union-attr]
            critique: _CritiqueSuggestions = crit_chain.invoke(
                [
                    SystemMessage(content=_CRITIQUE_PROMPT),
                    HumanMessage(content=itinerary.model_dump_json(indent=2)[:3000]),
                ]
            )
            if critique.has_issues and critique.suggestions:
                note = " | ".join(critique.suggestions[:3])
                itinerary = itinerary.model_copy(
                    update={"reality_banner": (itinerary.reality_banner or "") + f"\n\n📝 {note}"}
                )
        except Exception as exc:
            log.warning("critique_failed", error=str(exc))

        # ── Step 5: Deterministic final gate (I) ──────────────────────────────
        for iteration in range(_MAX_GATE_ITERATIONS):
            final_slotted = _extract_slotted_exps(itinerary)
            final_day_slots = _extract_day_slots(itinerary)

            hours_check = await self._opening_hours_tool.run(
                experiences=final_slotted, travel_dates=dates
            )
            duration_check = await self._duration_tool.run(day_slots=final_day_slots)

            conflicts = hours_check.get("conflicts", [])
            flags = duration_check.get("flags", [])

            if not conflicts and not flags:
                break  # Clean — exit gate loop

            log.info(
                "gate_resolving", iteration=iteration + 1,
                conflicts=len(conflicts), duration_flags=len(flags)
            )
            # Auto-resolve: mark conflicted slots as unresolved rather than pass bad data
            conflict_names = {c["name"] for c in conflicts}
            itinerary = _resolve_conflicts(itinerary, conflict_names, flags)
        else:
            log.warning("gate_max_iterations_reached")

        # ── Step 6: Wire shortlist into segments ──────────────────────────────
        itinerary = _inject_shortlist(itinerary, stays_shortlist, destination)
        itinerary = _inject_transport(itinerary, transport_rec, transport_alts)

        # ── Step 7: Stamp metadata ────────────────────────────────────────────
        itinerary = itinerary.model_copy(
            update={
                "source_query": state.get("query", ""),
                "created_at": datetime.now(tz=UTC),
                "budget_breakdown": budget_report,
                "visa_section": visa_report,
                "self_drive_section": self_drive_report,
            }
        )

        log.info("agent_done", title=itinerary.title, segments=len(itinerary.segments))
        return {"itinerary": itinerary}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_context(**kwargs: Any) -> str:
    parts: list[str] = [
        f"Trip: {kwargs['travelers']} traveler(s), {kwargs['trip_days']} days",
        f"Route: {kwargs['source']} → {kwargs['destination']}",
        f"Start date: {kwargs['start_date']}",
    ]
    if kwargs.get("destination_ctx"):
        ctx = kwargs["destination_ctx"]
        parts.append(
            f"Destination context: {ctx.season_label}, crowd={ctx.crowd_level}, "
            f"daily_cost={ctx.real_daily_cost} {ctx.currency_code}"
        )
    if kwargs.get("transport_rec"):
        tr = kwargs["transport_rec"]
        parts.append(f"Recommended transport: {tr.rationale[:100]}")
    if kwargs.get("transport_alts"):
        alts_str = "; ".join(
            getattr(a, "route_label", "") or "alternative" for a in kwargs["transport_alts"]
        )
        parts.append(f"Transport alternatives: {alts_str}")
    if kwargs.get("stays_shortlist"):
        stays_str = " | ".join(
            f"{s.name} (★{s.rating}, {s.price_per_night}/night)" for s in kwargs["stays_shortlist"][:4]
        )
        parts.append(f"Accommodation shortlist (all options): {stays_str}")
    if kwargs.get("scam_report"):
        sc = kwargs["scam_report"]
        scams = ", ".join(e.name for e in sc.top_scams[:3])
        parts.append(f"Safety: {sc.advisory_level}. Scams: {scams}")
    if kwargs.get("budget_report"):
        br = kwargs["budget_report"]
        parts.append(f"Budget: {br.total_estimated_cost} {br.currency_code} ({br.vs_budget_verdict})")
    if kwargs.get("user_profile"):
        up = kwargs["user_profile"]
        if up.interests:
            parts.append(f"User interests: {', '.join(up.interests)}")
        if up.dietary_restrictions:
            parts.append(f"Dietary restrictions: {', '.join(up.dietary_restrictions)}")

    for i, cluster in enumerate(kwargs.get("clusters", [])[:7]):
        exps = cluster.get("experiences", [])[:6]
        names = ", ".join(e.get("name", "") for e in exps)
        parts.append(f"Day {i + 1} experiences: {names}")

    recs = kwargs.get("restaurant_recs", {})
    if recs:
        parts.append(f"Restaurant data available for {len(recs)} days")

    reviews = kwargs.get("reviews_summary", {})
    if reviews:
        parts.append(f"Reviews available for: {', '.join(list(reviews)[:5])}")

    return "\n".join(parts)


def _extract_slotted_exps(itinerary: Itinerary) -> list[dict[str, Any]]:
    """Extract all activities from compiled itinerary with assigned_slot for gate check."""
    result: list[dict[str, Any]] = []
    for seg in itinerary.segments:
        for day in seg.days:
            for slot_obj in [day.morning, day.afternoon, day.evening]:
                for opt in slot_obj.options:
                    result.append(
                        {
                            "name": opt.place.name,
                            "assigned_slot": slot_obj.slot,
                            "opening_hours": opt.place.opening_hours.model_dump()
                            if opt.place.opening_hours
                            else None,
                        }
                    )
    return result


def _extract_day_slots(itinerary: Itinerary) -> dict[str, dict[str, list[dict[str, Any]]]]:
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for seg in itinerary.segments:
        for day in seg.days:
            key = day.date.isoformat()
            result[key] = {
                "morning": [
                    {"duration_hours": o.estimated_duration_minutes / 60.0, "name": o.place.name}
                    for o in day.morning.options
                ],
                "afternoon": [
                    {"duration_hours": o.estimated_duration_minutes / 60.0, "name": o.place.name}
                    for o in day.afternoon.options
                ],
                "evening": [
                    {"duration_hours": o.estimated_duration_minutes / 60.0, "name": o.place.name}
                    for o in day.evening.options
                ],
            }
    return result


def _resolve_conflicts(
    itinerary: Itinerary,
    conflict_names: set[str],
    duration_flags: list[dict[str, Any]],
) -> Itinerary:
    """Deterministically fix opening-hours conflicts and over-packed slots."""
    flagged_slots: set[tuple[str, str]] = {
        (f["day"], f.get("slot", "")) for f in duration_flags if f.get("slot") in _SLOT_NAMES
    }

    new_segments: list[TripSegment] = []
    for seg in itinerary.segments:
        new_days: list[Day] = []
        for day in seg.days:
            day_key = day.date.isoformat()
            new_slots: dict[str, TimeSlotOptions] = {}
            for slot_obj in [day.morning, day.afternoon, day.evening]:
                clean_opts = [
                    o for o in slot_obj.options if o.place.name not in conflict_names
                ]
                # Trim over-packed slots
                if (day_key, slot_obj.slot) in flagged_slots:
                    clean_opts = clean_opts[:2]  # keep at most 2 options
                unresolved_note = (
                    "Some activities could not be scheduled at this time — "
                    "please verify availability."
                    if len(clean_opts) < len(slot_obj.options)
                    else slot_obj.unresolved_note
                )
                new_slots[slot_obj.slot] = slot_obj.model_copy(
                    update={"options": clean_opts, "unresolved_note": unresolved_note}
                )
            new_days.append(
                day.model_copy(
                    update={
                        "morning": new_slots.get("morning", day.morning),
                        "afternoon": new_slots.get("afternoon", day.afternoon),
                        "evening": new_slots.get("evening", day.evening),
                    }
                )
            )
        new_segments.append(seg.model_copy(update={"days": new_days}))
    return itinerary.model_copy(update={"segments": new_segments})


def _inject_shortlist(
    itinerary: Itinerary, stays_shortlist: list[StayOption], destination: str
) -> Itinerary:
    """Wire the accommodation shortlist into segment stay_options."""
    if not stays_shortlist or not itinerary.segments:
        return itinerary
    stay_opts = StayOptions(
        location=destination,
        options=[s.model_dump() for s in stays_shortlist],
        notes=f"{len(stays_shortlist)} options available — all budget-filtered.",
    )
    new_segs = [
        seg.model_copy(update={"stay_options": stay_opts}) for seg in itinerary.segments
    ]
    return itinerary.model_copy(update={"segments": new_segs})


def _inject_transport(
    itinerary: Itinerary,
    transport_rec: Any,
    transport_alts: list[Any],
) -> Itinerary:
    """Wire transport recommendation + alternatives into itinerary.transport_section."""
    if not transport_rec:
        return itinerary
    ts = TransportSection(recommended=transport_rec, alternatives=transport_alts)
    return itinerary.model_copy(update={"transport_section": ts})


def _build_stub(
    source: str, destination: str, start_date: date, trip_days: int, travelers: int
) -> Itinerary:
    days = [
        Day(
            date=start_date + timedelta(days=i),
            day_number=i + 1,
            location=destination,
            morning=TimeSlotOptions(slot="morning"),
            afternoon=TimeSlotOptions(slot="afternoon"),
            evening=TimeSlotOptions(slot="evening"),
        )
        for i in range(trip_days)
    ]
    return Itinerary(
        title=f"{trip_days} Days in {destination}",
        source=source,
        destination=destination,
        destinations=[destination],
        travelers=travelers,
        segments=[TripSegment(location=destination, days=days)],
    )

