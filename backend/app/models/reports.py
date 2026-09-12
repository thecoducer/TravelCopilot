"""Report models produced by destination-intelligence and enrichment agents."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ── Shared building blocks ──────────────────────────────────────────────────


class VisaSource(BaseModel):
    """A grounding URL for visa information."""

    title: str
    url: str
    published_or_fetched_date: str | None = None


class ApplicationCentre(BaseModel):
    """Visa application centre or embassy office."""

    name: str
    address: str
    phone: str | None = None
    opening_hours: str | None = None
    booking_url: str | None = None
    google_maps_url: str | None = None


# ── Layer 1 reports ─────────────────────────────────────────────────────────


class ScamEntry(BaseModel):
    name: str
    description: str
    how_to_avoid: str


class SafetyReport(BaseModel):
    destination: str
    advisory_level: str  # e.g. "Exercise normal caution"
    travel_month: str | None = None
    is_peak_season: bool | None = None
    season_label: str | None = None
    season_reason: str | None = None
    crowd_level: str | None = None
    crowd_notes: str | None = None
    seasonal_weather_summary: str | None = None
    seasonal_risks: list[str] = Field(default_factory=list)
    altitude_meters: int | None = None
    acclimatization_advice: str | None = None
    top_scams: list[ScamEntry] = Field(default_factory=list)
    safe_areas: list[str] = Field(default_factory=list)
    emergency_contacts: dict[str, str] = Field(default_factory=dict)
    women_safety_notes: str | None = None
    # e.g. "SNM Hospital, Leh — nearest facility with altitude sickness treatment"
    medical_facilities: str | None = None
    # e.g. "Strongly recommended — high-altitude rescue can cost ₹50,000+"
    insurance_recommendation: str | None = None


class VisaReport(BaseModel):
    """Output of VisaAgent — requirements, process, and grounding sources (G)."""

    passport_country: str
    destination_country: str
    visa_required: bool
    visa_type: str | None = None  # "tourist" | "e-visa" | "on_arrival" | "visa_free"
    application_process: list[str] = Field(default_factory=list)
    documents_required: list[str] = Field(default_factory=list)
    processing_timeline: str | None = None
    fees: str | None = None
    dos_and_donts: list[str] = Field(default_factory=list)
    nearest_embassy: ApplicationCentre | None = None
    application_centre: ApplicationCentre | None = None
    apply_online_url: str | None = None
    validity_notes: str | None = None
    # (G) Grounding & confidence
    sources: list[VisaSource] = Field(default_factory=list)
    last_verified_at: datetime | None = None
    confidence: str = "medium"  # "high" | "medium" | "low"
    disclaimer: str = (
        "Visa rules change frequently and depend on your exact nationality and "
        "circumstances. This is guidance only — always confirm with the official "
        "consulate or embassy before booking travel."
    )


# ── Layer 3 conditional report ───────────────────────────────────────────────


class SelfDriveReport(BaseModel):
    destination: str
    rental_options: list[dict[str, Any]] = Field(default_factory=list)
    recommended_vehicle: str | None = None
    total_km_estimate: float | None = None
    fuel_cost_estimate: float | None = None
    toll_estimate: float | None = None
    road_condition_notes: str | None = None
    local_driving_tips: list[str] = Field(default_factory=list)
    permits_required: list[str] = Field(default_factory=list)  # e.g. ["ILP Leh", "PAP Hanle"]
    altitude_passes: list[str] = Field(default_factory=list)  # e.g. ["Khardung La (5,359 m)"]
    seasonal_restrictions: list[str] = Field(default_factory=list)  # e.g. ["Pangong Nov–Apr"]


# ── Layer 4 reports ─────────────────────────────────────────────────────────


class FxRateEntry(BaseModel):
    """A single FX rate snapshot used in BudgetReport. (H)"""

    rate: float
    fetched_at: datetime


class BudgetReport(BaseModel):
    """Output of BudgetPlannerAgent — FX-normalised totals and breakdown. (H)"""

    currency_code: str  # ISO 4217 — destination currency
    total_estimated_cost: float = Field(ge=0)
    total_in_source_currency: float | None = None
    fx_rates_used: dict[str, FxRateEntry] = Field(default_factory=dict)
    fx_disclaimer: str | None = None
    per_category_breakdown: dict[str, float] = Field(default_factory=dict)
    per_day_breakdown: list[float] = Field(default_factory=list)
    vs_budget_verdict: str  # "on-budget" | "over" | "under"
    cost_saving_tips: list[str] = Field(default_factory=list)
    per_person_cost: float | None = None  # total_estimated_cost / number of travelers
    permit_costs: float | None = None  # ILP, PAP, park fees etc. broken out separately
    # Accommodation cost per stop_id (nights × stop's chosen stay × travelers) for
    # multi-stop routes; unset for single_destination trips. See
    # specs/stops-discovery-agent-spec.md — budget aggregation must never multiply
    # one stay's price by the whole trip's day count.
    per_stop_accommodation_breakdown: dict[str, float] = Field(default_factory=dict)


class ReviewSummary(BaseModel):
    place_name: str
    rating: float | None = None
    review_count: int | None = None
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    sentiment: str | None = None  # "positive" | "mixed" | "negative"
    photos: list[str] = Field(default_factory=list)
    google_maps_url: str | None = None
    # Multi-stop identity — unset for single_destination trips. ``review_key`` is
    # the dict key used in ``reviews_summary`` for multi-stop routes, formatted
    # ``{route_version}:{stop_id}:{place_id_or_fallback}`` so identical venue
    # names at different stop occurrences never overwrite one another.
    stop_id: str | None = None
    place_id: str | None = None
    review_key: str | None = None
    route_version: int | None = None


# ── Observability ────────────────────────────────────────────────────────────


class AgentTokenUsage(BaseModel):
    agent_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
