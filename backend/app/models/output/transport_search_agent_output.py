"""Structured route-combination output models owned by transport search."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RouteCombo(BaseModel):
    origin: str
    destination: str
    mode: str = Field(pattern="^(flight|train|bus|cab|taxi|ferry|other)$")
    via_hub: str | None = None


class HubResult(BaseModel):
    route_combinations: list[RouteCombo] = Field(default_factory=list)
