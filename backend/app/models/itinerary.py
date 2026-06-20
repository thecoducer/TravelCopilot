"""Itinerary and experience models — the core output of the planning graph.

Design principle: every user-facing choice (activity, food, stay) is presented as
2-3 ranked *options* rather than a single fixed pick.  The AI explains why each option
aligns with the traveller's stated preferences via ``recommendation_reason`` and
``best_for`` tags.  When the AI lacks enough context to make a confident suggestion it
emits a ``ClarificationRequest`` instead of guessing.

Multi-stop trips (e.g. Leh → Nubra → Pangong → Hanle) are modelled as a list of
``TripSegment`` objects — one per location — each carrying its own days and
``StayOptions``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

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
    """Raw experience from Layer 2 — before geo-clustering."""

    name: str
    type: str  # "tourist_attraction" | "museum" | "art_gallery" | "park" | ...
    description: str
    duration_hours: float = Field(ge=0)
    price_range: str
    lat: float
    lng: float
    photos: list[str] = Field(default_factory=list)
    google_maps_url: str | None = None
    opening_hours: OpeningHours | None = None
    best_time_to_visit: str | None = None
    source: str  # "google_places" | "tavily"
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = None
    address: str | None = None  # carried through from Places API for compiler use


# ── Options containers ────────────────────────────────────────────────────────


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


class TimeSlotOptions(BaseModel):
    """2-3 ranked activity options for a morning / afternoon / evening slot."""

    slot: str  # "morning" | "afternoon" | "evening"
    options: list[ActivityOption] = Field(default_factory=list)
    notes: str | None = None
    unresolved_note: str | None = None  # set when the compiler cannot resolve a conflict


class FoodOptions(BaseModel):
    """2-3 food venue options for a specific meal type at a location."""

    meal_type: str  # "breakfast" | "lunch" | "dinner" | "snack"
    options: list[FoodVenue] = Field(default_factory=list)
    notes: str | None = None  # e.g. "Limited options in Hanle — carry packed food"


class StayOptions(BaseModel):
    """2-3 ranked accommodation options for a trip segment / location."""

    location: str
    options: list[Any] = Field(default_factory=list)  # list[StayOption], ranked best-first
    notes: str | None = None  # e.g. "Book early for Jul–Aug; tented camps fill quickly"


# ── Day + segment structure ───────────────────────────────────────────────────


class Day(BaseModel):
    date: date
    day_number: int = Field(ge=1)
    location: str  # e.g. "Leh" | "Nubra Valley" | "Pangong" | "Hanle"
    morning: TimeSlotOptions = Field(default_factory=lambda: TimeSlotOptions(slot="morning"))
    afternoon: TimeSlotOptions = Field(default_factory=lambda: TimeSlotOptions(slot="afternoon"))
    evening: TimeSlotOptions = Field(default_factory=lambda: TimeSlotOptions(slot="evening"))
    food: list[FoodOptions] = Field(default_factory=list)  # one FoodOptions entry per meal type
    altitude_warning: str | None = None  # e.g. "Acclimatization day — avoid strenuous activity"


class TripSegment(BaseModel):
    """Consecutive days at one location.

    Groups related days together and carries the shared accommodation options for
    that location (you pick once per segment, not once per day).
    """

    location: str
    days: list[Day] = Field(default_factory=list)
    stay_options: StayOptions | None = None
    drive_notes: str | None = None  # road conditions, approx drive duration
    # e.g. ["Inner Line Permit", "Protected Area Permit"]
    permits_required: list[str] = Field(default_factory=list)
    altitude_meters: int | None = None  # elevation of this location in metres
    # e.g. "No BSNL signal beyond Diskit. Download offline maps."
    connectivity: str | None = None


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
    recommended: Any | None = None  # TransportRecommendation
    alternatives: list[Any] = Field(default_factory=list)


class Itinerary(BaseModel):
    id: str | None = None
    title: str
    source: str
    destination: str  # primary / final destination label
    destinations: list[str] = Field(default_factory=list)  # all stops in visit order
    dates: Any | None = None  # TripDates
    travelers: int = Field(default=1, ge=1)
    reality_banner: str | None = None
    segments: list[TripSegment] = Field(default_factory=list)  # one per location stop
    transport_section: TransportSection | None = None
    safety_briefing: str | None = None
    # generated by agents; especially relevant for high-altitude / adventure trips
    packing_tips: list[str] = Field(default_factory=list)
    # e.g. "No mobile signal beyond Diskit. Download offline maps."
    connectivity_summary: str | None = None
    # original natural-language query that triggered this itinerary
    source_query: str | None = None
    visa_section: Any | None = None  # VisaReport
    self_drive_section: Any | None = None  # SelfDriveReport
    budget_breakdown: Any | None = None  # BudgetReport
    clarifications_needed: list[ClarificationRequest] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 1  # incremented on each user-driven refinement
    # e.g. "Basic Hindi useful; English widely spoken in Leh tourist areas"
    language_tips: str | None = None
    # e.g. "Carry cash — ATMs rare beyond Leh. Exchange before departure."
    currency_tips: str | None = None
