"""Itinerary models — the core output of the planning graph.

Design principles
-----------------
1. **Day-wise.** A trip is a flat ``list[TripDays]`` — one entry per calendar day.
   A 5-day trip has exactly 5 entries. There is no location-grouping layer: each
   day independently carries its own stay, transport, safety, food and activity
   options, so it can be rendered standalone. Multi-night stays repeat the full
   objects on every day they cover.

2. **Options, not verdicts.** Every user-facing choice is presented as 2-3 ranked
   *options*. ``recommendation_reason`` and ``best_for`` explain the alignment with
   the traveller's stated preferences. When the planner lacks context it emits a
   ``ClarificationRequest`` instead of guessing.

3. **Synthesis, never invention.** The compiler absorbs upstream agent output
   verbatim. Factual fields here are copies of ``SafetyReport``, ``VisaReport``,
   ``BudgetReport``, ``StayOption``, ``TransportRecommendation`` and ``Experience``
   objects produced by earlier agents — the LLM only selects, orders and explains.

Multi-stop routes (e.g. Leh → Nubra → Pangong → Hanle) are expressed through each
day's ``stop_id`` / ``leg_id``, resolved against ``Itinerary.stops`` and
``Itinerary.route_legs``. A revisited place yields distinct ``stop_id`` values.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.reports import (
    BudgetReport,
    ReviewSummary,
    SafetyReport,
    SelfDriveReport,
    VisaReport,
)
from app.models.stops import LegType, RouteLegPlan, TripStop
from app.models.transport import StayOption, TransportRecommendation
from app.models.user_profile import TripDates

# ── Domain vocabulary ─────────────────────────────────────────────────────────
# The legal values of TimeSlotOptions.slot and FoodOptions.meal_type, shared by
# every layer that schedules a day (compiler, service, quality-gate tools).
SLOT_NAMES: tuple[str, str, str] = ("morning", "afternoon", "evening")
MEAL_TYPES: tuple[str, str, str] = ("breakfast", "lunch", "dinner")

# ── Base place / venue models ─────────────────────────────────────────────────


class OpeningHours(BaseModel):
    open: str  # e.g. "09:00"
    close: str  # e.g. "17:00"
    days: list[str] = Field(default_factory=list)  # e.g. ["Mon", "Tue", ...]
    notes: str | None = None


class Place(BaseModel):
    """A single activity/attraction."""

    name: str
    description: str
    category: str  # e.g. "Museum", "Temple", "Park"
    duration_minutes: int = Field(ge=0)
    price_range: str  # e.g. "₹200-400" or "Free"
    lat: float
    lng: float
    address: str
    photos: list[str] = Field(default_factory=list)
    google_maps_url: str | None = None
    more_images_url: str | None = None
    youtube_search_url: str | None = None
    opening_hours: OpeningHours | None = None
    reviews_summary: str | None = None
    geotag: str | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = None


class FoodVenue(BaseModel):
    """A restaurant, cafe, street-food stall, or takeaway."""

    name: str
    category: str  # "restaurant" | "cafe" | "street_food" | "takeaway"
    cuisine: str
    price_range: str
    rating: float = Field(ge=0, le=5)
    address: str
    lat: float | None = None
    lng: float | None = None
    google_maps_url: str | None = None
    photos: list[str] = Field(default_factory=list)
    meal_types: list[str] = Field(default_factory=list)  # "breakfast"|"lunch"|"dinner"|"snack"
    dietary_tags: list[str] = Field(default_factory=list)  # "vegetarian", "vegan", "halal", ...
    neighbourhood: str | None = None
    review_count: int | None = None
    booking_url: str | None = None  # e.g. Zomato / EazyDiner reservation link


class Experience(BaseModel):
    """An attraction, activity, tour, or cultural experience."""

    name: str = Field(description="Name of the attraction, activity, or viewpoint.")
    type: str = Field(
        default="tourist_attraction",
        description=(
            "Category type (e.g., historical_landmark, museum, park, viewpoint, "
            "temple, art_gallery, outdoor_adventure)."
        ),
    )
    description: str = Field(
        description="Engaging 1-2 sentence description explaining why it's worth visiting."
    )
    duration_hours: float = Field(default=2.0, ge=0.0, description="Estimated duration in hours.")
    price_range: str = Field(
        default="Moderate",
        description="Price tier: 'Free', 'Inexpensive', 'Moderate', 'Expensive', or fee estimate.",
    )
    lat: float = Field(
        default=0.0,
        description="Latitude coordinate if known, or 0.0 to be geocoded.",
    )
    lng: float = Field(
        default=0.0,
        description="Longitude coordinate if known, or 0.0 to be geocoded.",
    )
    photos: list[str] = Field(default_factory=list)
    google_maps_url: str | None = None
    opening_hours: OpeningHours | None = None
    best_time_to_visit: str | None = Field(
        default=None,
        description=(
            "Recommended time of day or conditions (e.g., 'Morning', 'Late Afternoon', 'Sunset')."
        ),
    )
    source: str = Field(
        default="llm",
        description="Source of this experience (e.g. 'llm', 'google_places', 'tavily').",
    )
    rating: float | None = Field(
        default=None, ge=0.0, le=5.0, description="Visitor rating out of 5."
    )
    review_count: int | None = Field(
        default=None, ge=0, description="Approximate number of reviews."
    )
    address: str | None = Field(
        default=None, description="Neighbourhood, address, or geographic area."
    )
    # Owning stop occurrence for multi-stop routes; unset for single_destination trips.
    stop_id: str | None = None
    route_version: int | None = None


class ExperiencesOutput(BaseModel):
    """Structured LLM output container for curated experiences."""

    experiences: list[Experience] = Field(
        default_factory=list,
        description="List of 6 to 12 curated experiences and attractions.",
    )


# ── Day-scoped option containers ──────────────────────────────────────────────


class ActivityOption(BaseModel):
    """One ranked activity choice within a time slot, with preference-alignment context."""

    place: Place
    rank: int = Field(ge=1)  # 1 = top recommendation
    recommendation_reason: str  # e.g. "Matches your interest in photography"
    best_for: list[str] = Field(default_factory=list)  # e.g. ["sunrise", "photography", "families"]
    estimated_duration_minutes: int = Field(ge=0)
    best_time: str | None = None  # e.g. "Sunrise" or "After 4 pm when crowds thin"
    crowd_warning: str | None = None  # e.g. "Very crowded at sunrise — arrive 45 min early"
    booking_url: str | None = None  # pre-booking link if required or strongly recommended
    # Provenance carried through from ``Experience.source`` so unverified
    # (LLM-sourced) suggestions can be flagged in the UI.
    source: str = "llm"


class TimeSlotOptions(BaseModel):
    """2-3 ranked activity options for a morning / afternoon / evening slot."""

    slot: str  # "morning" | "afternoon" | "evening"
    options: list[ActivityOption] = Field(default_factory=list)
    notes: str | None = None
    unresolved_note: str | None = None  # set when the compiler cannot resolve a conflict


class FoodOptions(BaseModel):
    """2-3 food venue options for a specific meal on a specific day."""

    meal_type: str  # "breakfast" | "lunch" | "dinner" | "snack"
    options: list[FoodVenue] = Field(default_factory=list)
    notes: str | None = None  # e.g. "Limited options in Hanle — carry packed food"


class StayOptions(BaseModel):
    """Ranked accommodation options covering one night of the trip.

    Repeated in full on every day of a multi-night stay so each day renders
    standalone; ``is_checkin_day`` / ``is_checkout_day`` mark the boundaries.
    """

    location: str
    options: list[StayOption] = Field(default_factory=list)  # ranked best-first
    recommended: StayOption | None = None  # the stay analyst's pick for this stop
    notes: str | None = None  # e.g. "Book early for Jul–Aug; tented camps fill quickly"
    stop_id: str | None = None
    nights_at_location: int = Field(default=1, ge=0)
    is_checkin_day: bool = False
    is_checkout_day: bool = False
    check_in: str | None = None  # e.g. "2:00 PM"
    check_out: str | None = None  # e.g. "11:00 AM"


class TransportOptions(BaseModel):
    """One transfer taking place on a given day, with its ranked options.

    A day may have zero (in-place day), one, or several transfers.
    """

    origin: str
    destination: str
    leg_id: str | None = None
    leg_type: LegType | None = None
    departure_date: date | None = None
    recommended: TransportRecommendation | None = None
    alternatives: list[TransportRecommendation] = Field(default_factory=list)
    notes: str | None = None
    mode_downgraded: bool = False  # a preferred mode was unavailable on this leg
    no_result: bool = False  # search returned nothing bookable


# ── The day ───────────────────────────────────────────────────────────────────


class TripDays(BaseModel):
    """One calendar day of the trip, complete and self-describing.

    Carries everything the upstream agents found for this date: what to do, where
    to eat, where to sleep, how to travel, what to watch out for, and what it costs.
    """

    day_number: int = Field(ge=1)  # 1-based, continuous across the whole trip
    date: date
    location: str  # e.g. "Leh" | "Nubra Valley" | "Pangong" | "Hanle"
    summary: str | None = None  # one-line headline for the day

    morning: TimeSlotOptions = Field(default_factory=lambda: TimeSlotOptions(slot="morning"))
    afternoon: TimeSlotOptions = Field(default_factory=lambda: TimeSlotOptions(slot="afternoon"))
    evening: TimeSlotOptions = Field(default_factory=lambda: TimeSlotOptions(slot="evening"))

    food_options: list[FoodOptions] = Field(default_factory=list)  # one entry per meal type
    stay_options: StayOptions | None = None
    transport_options: list[TransportOptions] = Field(default_factory=list)
    review_highlights: list[ReviewSummary] = Field(default_factory=list)

    permits_required: list[str] = Field(default_factory=list)  # e.g. ["Inner Line Permit"]
    altitude_meters: int | None = None
    connectivity: str | None = None  # e.g. "No BSNL signal beyond Diskit"
    drive_notes: str | None = None  # road conditions, approx drive duration

    estimated_cost: float | None = Field(default=None, ge=0)  # BudgetReport.per_day_breakdown
    currency_code: str | None = None

    # Route metadata — unset for single_destination trips; populated from stops_by_day
    # for multi-stop routes (see specs/stops-discovery-agent-spec.md).
    stop_id: str | None = None
    leg_id: str | None = None  # inbound route leg reaching this day's location, if any
    route_version: int | None = None
    is_travel_day: bool = False
    is_checkin_day: bool = False
    is_checkout_day: bool = False


# ── AI clarification ──────────────────────────────────────────────────────────


class ClarificationRequest(BaseModel):
    """Emitted when the AI needs more user input before completing or improving the itinerary.

    If ``required`` is True the itinerary is incomplete until the user answers.
    If False the planner has proceeded with sensible defaults and the question is
    advisory (the user can refine later).
    """

    field: str  # aspect needing clarity: "dates"|"budget"|"interests"|"accommodation_style"|...
    question: str  # question shown verbatim to the user
    context: str  # internal reason — why this is needed to improve the suggestion
    suggested_options: list[str] = Field(default_factory=list)  # pre-filled answer choices
    required: bool = True


# ── Top-level transport / itinerary ──────────────────────────────────────────


class TransportSection(BaseModel):
    """Trip-level transport view: the headline route plus every resolved leg."""

    recommended: TransportRecommendation | None = None
    alternatives: list[TransportRecommendation] = Field(default_factory=list)
    by_leg: dict[str, TransportRecommendation] = Field(default_factory=dict)  # keyed by leg_id


class Itinerary(BaseModel):
    """The complete trip plan — a flat run of days plus trip-wide context."""

    id: str | None = None
    title: str
    source: str = Field(description="Origin or departure city for the trip")
    dates: TripDates | None = None
    travelers: int = Field(default=1, ge=1)

    # The trip itself — one entry per calendar day, in order.
    trip_days: list[TripDays] = Field(default_factory=list)

    # Route contract from StopsDiscoveryAgent; empty for single_destination trips.
    stops: list[TripStop] = Field(default_factory=list)  # in visit order
    route_legs: list[RouteLegPlan] = Field(default_factory=list)  # in travel order
    route_version: int | None = None
    route_discovery_status: str | None = None

    # Trip-wide sections, copied from the agents that produced them.
    transport_section: TransportSection | None = None
    safety_section: SafetyReport | None = None
    safety_briefing: str | None = None  # deterministic prose render of safety_section
    visa_section: VisaReport | None = None
    self_drive_section: SelfDriveReport | None = None
    budget_breakdown: BudgetReport | None = None

    reality_banner: str | None = None
    # generated by agents; especially relevant for high-altitude / adventure trips
    packing_tips: list[str] = Field(default_factory=list)
    permits_required: list[str] = Field(default_factory=list)  # union across all days
    # e.g. "No mobile signal beyond Diskit. Download offline maps."
    connectivity_summary: str | None = None
    # e.g. "Basic Hindi useful; English widely spoken in Leh tourist areas"
    language_tips: str | None = None
    # e.g. "Carry cash — ATMs rare beyond Leh. Exchange before departure."
    currency_tips: str | None = None

    clarifications_needed: list[ClarificationRequest] = Field(default_factory=list)

    # original natural-language query that triggered this itinerary
    source_query: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 1  # incremented on each user-driven refinement


Itinerary.model_rebuild()
