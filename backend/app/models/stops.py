"""Route/stop models — the provisional multi-stop route contract.

Produced by ``StopsDiscoveryAgent`` and consumed by every downstream Layer
2-5 agent. See ``specs/stops-discovery-agent-spec.md`` for the full contract.

Terminology (see spec "Core concepts" before changing anything here):
  - A ``TripStop`` is an *occurrence*, not a place — a route that revisits a
    place gets one ``TripStop`` per visit, each with its own ``stop_id``.
  - Everything here is **provisional** until Phase 6 external verification
    lands. Never call route/stop output "canonical" or "authoritative".
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

RouteDiscoveryStatus = Literal["single_destination", "multi_stop_provisional", "discovery_failed"]
RouteVerificationStatus = Literal["provisional", "verified"]
StopKind = Literal["overnight", "gateway_transit"]

# Sentinel origin/destination stop_id for legs anchored at the user's source —
# the source is a plain string label (from TripState), never a routed TripStop.
SOURCE_STOP_ID = "source"


class LegType(StrEnum):
    """See spec "Core concepts" for the exact semantics of each value."""

    SOURCE_TO_GATEWAY = "source_to_gateway"
    GATEWAY_TO_STOP = "gateway_to_stop"
    INTERNAL_TRANSFER = "internal_transfer"
    STOP_TO_GATEWAY = "stop_to_gateway"
    GATEWAY_TO_SOURCE = "gateway_to_source"
    COUNTRY_TRANSFER = "country_transfer"


# Transport-mode policy defaults per leg_type (Core concepts: precedence tier 3).
# Generic mode vocabulary — TransportSearchAgent maps these to concrete tools.
_LEG_TYPE_DEFAULT_MODES: dict[LegType, list[str]] = {
    LegType.SOURCE_TO_GATEWAY: ["flight", "train", "intercity_bus"],
    LegType.GATEWAY_TO_SOURCE: ["flight", "train", "intercity_bus"],
    LegType.COUNTRY_TRANSFER: ["flight", "train", "intercity_bus"],
    LegType.GATEWAY_TO_STOP: ["road", "taxi", "rental", "local_transit"],
    LegType.STOP_TO_GATEWAY: ["road", "taxi", "rental", "local_transit"],
    LegType.INTERNAL_TRANSFER: ["road", "private_car", "local_transit"],
}

# Self-drive intent (precedence tier 2) forces road/rental modes for internal legs.
_SELF_DRIVE_LOCAL_MODES = ["rental", "private_car", "road"]


def default_allowed_modes(leg_type: LegType, self_drive_intent: bool) -> list[str]:
    """Resolve a leg's default allowed transport modes.

    Applies precedence tiers 2-3 from the spec's "Transport search policy
    precedence" (explicit user preference — tier 1 — is not yet a modelled
    field anywhere upstream, so it is not resolved here).
    """
    if self_drive_intent and leg_type in {
        LegType.GATEWAY_TO_STOP,
        LegType.STOP_TO_GATEWAY,
        LegType.INTERNAL_TRANSFER,
    }:
        return list(_SELF_DRIVE_LOCAL_MODES)
    return list(_LEG_TYPE_DEFAULT_MODES.get(leg_type, ["road"]))


class TripStop(BaseModel):
    """One ordered occurrence of an overnight stay or gateway transit point."""

    stop_id: str
    name: str
    country: str | None = None
    lat: float | None = None
    lng: float | None = None
    stop_kind: StopKind = "overnight"
    sequence: int = Field(ge=0)
    nights: int = Field(default=0, ge=0)
    arrival_date: date | None = None
    departure_date: date | None = None
    permits_required: list[str] = Field(default_factory=list)
    altitude_meters: int | None = None
    notes: str | None = None


class TransportSearchPolicy(BaseModel):
    """Resolved transport-mode policy for one route leg."""

    allowed_modes: list[str] = Field(default_factory=list)
    search_scope: Literal["long_distance", "regional"] = "regional"
    requires_public_transport: bool = False
    mode_downgraded: bool = False


class RouteLegPlan(BaseModel):
    """One transfer between two stop occurrences (or the source sentinel)."""

    leg_id: str
    origin_stop_id: str
    destination_stop_id: str
    sequence: int = Field(ge=0)
    leg_type: LegType
    travel_day_index: int = Field(ge=0)
    planned_departure_date: date
    planned_arrival_date: date
    policy: TransportSearchPolicy = Field(default_factory=TransportSearchPolicy)


class GatewayTradeoffs(BaseModel):
    transit_duration_hours: float | None = None
    cost_tier: str | None = None  # "budget" | "mid" | "premium"
    scenic_value: str | None = None
    acclimatization_notes: str | None = None


class GatewayOption(BaseModel):
    """One candidate access-gateway corridor into the destination region."""

    option_id: str
    gateway_name: str
    gateway_stop: TripStop
    entry_legs: list[RouteLegPlan] = Field(default_factory=list)
    exit_legs: list[RouteLegPlan] = Field(default_factory=list)
    tradeoffs: GatewayTradeoffs = Field(default_factory=GatewayTradeoffs)
    is_recommended: bool = False


class DayAllocation(BaseModel):
    """One resolved calendar day — the single source of truth for day counts.

    Downstream agents read this instead of re-deriving day counts from
    ``TripStop.nights`` independently.
    """

    day_index: int = Field(ge=0)
    date: date
    stop_id: str
    is_travel_day: bool = False
    is_checkin_day: bool = False
    is_checkout_day: bool = False


def stop_display_name(stop_id: str, stops: dict[str, TripStop], source: str) -> str:
    """Resolve a leg endpoint's display name, including the source sentinel."""
    if stop_id == SOURCE_STOP_ID:
        return source
    stop = stops.get(stop_id)
    return stop.name if stop else stop_id
