"""Structured route-discovery output models owned by the stops agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StopDiscoveryStop(BaseModel):
    name: str
    stop_kind: Literal["overnight", "gateway_transit"] = "overnight"
    nights_hint: int = Field(default=1, ge=0)
    country: str | None = None
    permits_required: list[str] = Field(default_factory=list)
    altitude_meters: int | None = None
    notes: str | None = None


class StopDiscoveryGatewayOption(BaseModel):
    option_id: str
    gateway_name: str
    gateway_stop: StopDiscoveryStop
    transit_duration_hours: float | None = None
    cost_tier: str | None = None
    scenic_value: str | None = None
    acclimatization_notes: str | None = None
    is_recommended: bool = False


class StopDiscoveryRoute(BaseModel):
    route_discovery_status: Literal["single_destination", "multi_stop_provisional"]
    overnight_stops: list[StopDiscoveryStop] = Field(default_factory=list)
    gateway_options: list[StopDiscoveryGatewayOption] = Field(default_factory=list)
