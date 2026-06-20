"""Transport and accommodation models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RouteWaypoint(BaseModel):
    label: str  # e.g. "KOL", "DEL"
    name: str  # e.g. "Kolkata Netaji Subhas Chandra Bose International Airport"
    lat: float
    lng: float


class RouteLeg(BaseModel):
    mode: str  # "flight" | "train" | "bus"
    operator: str  # e.g. "IndiGo", "Rajdhani Express"
    origin: str
    destination: str
    departure_time: str | None = None  # ISO-8601 or HH:MM
    arrival_time: str | None = None
    duration_minutes: int = Field(ge=0)
    cost: float = Field(ge=0)
    currency_code: str  # ISO 4217
    booking_url: str | None = None
    seat_class: str | None = None  # "economy" | "business" | "first" | "sleeper"
    flight_number: str | None = None  # e.g. "6E-503"; None for non-flight modes
    stops: int = Field(default=0, ge=0)  # number of layovers / intermediate stops
    layover_at: str | None = None  # IATA code of layover airport, if stops == 1
    price_cached_at: datetime
    price_disclaimer: str  # e.g. "Price captured 3h ago — verify before booking"
    baggage_allowance: str | None = None  # e.g. "15 kg checked + 7 kg cabin"
    cancellation_policy: str | None = None  # e.g. "Non-refundable" | "Flexible up to 24h"


class TransportRecommendation(BaseModel):
    recommended_legs: list[RouteLeg] = Field(default_factory=list)
    total_cost: float = Field(ge=0)
    total_duration_minutes: int = Field(ge=0)
    currency_code: str
    rationale: str
    personalization_reason: str
    non_obvious_insight: str | None = None
    route_waypoints: list[RouteWaypoint] = Field(default_factory=list)
    route_label: str | None = None  # e.g. "Via DEL (1 stop)" — shown in alternatives list


class StayOption(BaseModel):
    name: str
    address: str
    city: str
    price_per_night: float = Field(ge=0)
    currency_code: str
    rating: float = Field(ge=0, le=5)
    review_count: int = Field(ge=0)
    amenities: list[str] = Field(default_factory=list)
    photos: list[str] = Field(default_factory=list)
    google_maps_url: str | None = None
    booking_url: str | None = None
    hotel_style: str | None = None  # matches HotelStyle values
    price_tier: str | None = None  # "budget" | "mid" | "luxury"
    personalization_reason: str | None = None
    price_disclaimer: str | None = None
    lat: float | None = None
    lng: float | None = None
    check_in: str | None = None  # e.g. "2:00 PM"
    check_out: str | None = None  # e.g. "11:00 AM"
    free_cancellation_until: str | None = None  # ISO date string, if applicable
    # INR-normalised price for cross-currency budget comparison
    price_per_night_inr: float | None = None
