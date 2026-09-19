"""Transport and accommodation models."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field

from app.config import settings

# Google Routes returns durations as a protobuf duration string ("18543s").
_SECONDS_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*s\s*$", re.IGNORECASE)


def _coerce_minutes(value: Any) -> Any:
    """Accept "18543s", 90.02 or 90 for a minutes field.

    Models routinely echo back the float they were shown; rejecting it discards
    an otherwise-correct answer for a purely representational mismatch.
    """
    if isinstance(value, str):
        match = _SECONDS_PATTERN.match(value)
        if match:
            return round(float(match.group(1)) / 60.0)
    if isinstance(value, float):
        return round(value)
    return value


def _coerce_waypoint(value: Any) -> Any:
    """Accept a bare label string where a waypoint object is expected."""
    if isinstance(value, str):
        return {"label": value, "name": value}
    return value


DurationMinutes = Annotated[int, BeforeValidator(_coerce_minutes)]


class RouteWaypoint(BaseModel):
    label: str  # e.g. "KOL", "DEL"
    name: str  # e.g. "Kolkata Netaji Subhas Chandra Bose International Airport"
    # Unknown coordinates are common for city-level waypoints; 0.0 would be a
    # valid-looking point in the Atlantic.
    lat: float | None = None
    lng: float | None = None


class RouteLeg(BaseModel):
    mode: str  # "flight" | "train" | "bus"
    operator: str = ""  # e.g. "IndiGo", "Rajdhani Express"
    origin: str
    destination: str
    departure_time: str | None = None  # ISO-8601 or HH:MM
    arrival_time: str | None = None
    duration_minutes: DurationMinutes = Field(ge=0)
    cost: float = Field(default=0.0, ge=0)
    # Ground providers return no fare; distinguish that from a genuinely free leg.
    price_unknown: bool = False
    currency_code: str = Field(default_factory=lambda: settings.default_currency)
    booking_url: str | None = None
    seat_class: str | None = None  # "economy" | "business" | "first" | "sleeper"
    flight_number: str | None = None  # e.g. "6E-503"; None for non-flight modes
    stops: int = Field(default=0, ge=0)  # number of layovers / intermediate stops
    layover_at: str | None = None  # IATA code of layover airport, if stops == 1
    # Back-filled by the optimiser after validation, so requiring them here would
    # reject the response before it can be patched.
    price_cached_at: datetime | None = None
    price_disclaimer: str = ""  # e.g. "Price captured 3h ago — verify before booking"
    baggage_allowance: str | None = None  # e.g. "15 kg checked + 7 kg cabin"
    cancellation_policy: str | None = None  # e.g. "Non-refundable" | "Flexible up to 24h"


class TransportRecommendation(BaseModel):
    recommended_legs: list[RouteLeg] = Field(default_factory=list)
    total_cost: float = Field(default=0.0, ge=0)
    total_duration_minutes: DurationMinutes = Field(default=0, ge=0)
    currency_code: str = Field(default_factory=lambda: settings.default_currency)
    rationale: str = ""
    personalization_reason: str = ""
    non_obvious_insight: str | None = None
    route_waypoints: list[Annotated[RouteWaypoint, BeforeValidator(_coerce_waypoint)]] = Field(
        default_factory=list
    )
    route_label: str | None = None  # e.g. "Via DEL (1 stop)" — shown in alternatives list
    # Route metadata — set when this recommendation answers one route_legs entry
    # for a multi-stop route; unset for the single_destination/aggregate recommendation.
    leg_id: str | None = None
    route_version: int | None = None
    mode_downgraded: bool = False
    no_result: bool = False


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
    # Owning stop occurrence for multi-stop routes; unset for single_destination trips.
    stop_id: str | None = None
    route_version: int | None = None
