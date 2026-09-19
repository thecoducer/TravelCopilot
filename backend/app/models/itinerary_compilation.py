"""Reference-only contracts used while compiling an ``Itinerary`` (Layer 5).

These are the ONLY shapes the itinerary-compiler LLM is allowed to return. Every
field is a name, a day number, or short grounded prose — never a nested factual
object (price, rating, coordinate, URL, date). That makes fabricating a factual
value structurally impossible: the compiler service resolves each name against a
verified upstream pool and drops anything that doesn't match.

``RoutePlan`` is the deterministic (non-LLM) counterpart — the resolved route
structure that the compiler lays the LLM's picks onto.
"""

from __future__ import annotations

from functools import cached_property

from pydantic import BaseModel, ConfigDict, Field

from app.models.stops import SINGLE_STOP_ID, DayAllocation, TripStop

__all__ = ["SINGLE_STOP_ID"]


class ActivityPick(BaseModel):
    """One LLM choice: assign a named candidate experience to a (day, slot)."""

    day_number: int = Field(ge=1)
    slot: str  # "morning" | "afternoon" | "evening"
    experience_name: str
    recommendation_reason: str
    best_for: list[str] = Field(default_factory=list)


class FoodPick(BaseModel):
    """One LLM choice: assign a named candidate venue to a (day, meal)."""

    day_number: int = Field(ge=1)
    meal_type: str  # "breakfast" | "lunch" | "dinner"
    venue_name: str


class DayPlan(BaseModel):
    """The itinerary compiler's LLM output: picks only, no facts."""

    activities: list[ActivityPick] = Field(default_factory=list)
    food: list[FoodPick] = Field(default_factory=list)


class DaySummary(BaseModel):
    day_number: int = Field(ge=1)
    summary: str


class TripNarrative(BaseModel):
    """The compiler's narrative-only LLM output: title, day summaries, packing tips."""

    title: str = ""
    day_summaries: list[DaySummary] = Field(default_factory=list)
    packing_tips: list[str] = Field(default_factory=list)


class RoutePlan(BaseModel):
    """The resolved route: ordered stops plus exactly one allocation per calendar day.

    Deterministic — read from ``StopsDiscoveryAgent``'s route contract for multi-stop
    trips, or synthesised as a one-stop route for single-destination trips. Never
    derived from the LLM.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    stops: list[TripStop]
    allocations: list[DayAllocation]
    is_multi_stop: bool

    @cached_property
    def stops_by_id(self) -> dict[str, TripStop]:
        return {stop.stop_id: stop for stop in self.stops}

    def allocations_for(self, stop_id: str) -> list[DayAllocation]:
        return [alloc for alloc in self.allocations if alloc.stop_id == stop_id]
