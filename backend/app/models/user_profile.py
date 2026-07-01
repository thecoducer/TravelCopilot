"""User profile and trip date models."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class BudgetTier(StrEnum):
    budget = "budget"
    mid = "mid"
    luxury = "luxury"


class HotelStyle(StrEnum):
    hostel = "hostel"
    budget = "budget"
    boutique = "boutique"
    business = "business"
    luxury = "luxury"


class TripDates(BaseModel):
    departure: date
    return_date: date | None = None
    flexibility_days: int = 0  # ±N days flexible departure window
    night_travel_ok: bool = True  # whether overnight trains / buses are acceptable

    @property
    def trip_days(self) -> int:
        if self.return_date:
            return max(1, (self.return_date - self.departure).days)
        return 1


class BudgetPreference(BaseModel):
    tier: BudgetTier = BudgetTier.mid
    total_budget_inr: float | None = Field(default=None, ge=0)
    per_day_budget_inr: float | None = Field(default=None, ge=0)


class UserProfile(BaseModel):
    user_id: str
    display_name: str | None = None
    home_city: str | None = None
    nationality: str | None = None
    passport_country: str | None = None
    preferred_currency: str = "INR"
    dietary_restrictions: list[str] = Field(default_factory=list)
    accessibility_needs: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    preferred_airlines: list[str] = Field(default_factory=list)
    preferred_hotel_chains: list[str] = Field(default_factory=list)
    hotel_style: HotelStyle | None = None
    budget_tier: BudgetTier = BudgetTier.mid
    travel_style: str | None = None  # "adventure"|"cultural"|"luxury"|"backpacker"|"family"
    fitness_level: str | None = None  # "low"|"moderate"|"high" — affects activity recommendations
    altitude_experience: bool | None = None  # True = has previously travelled above 3,000 m
