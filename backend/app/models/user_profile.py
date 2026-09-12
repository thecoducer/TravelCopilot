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
    preferred_cuisines: list[str] = Field(default_factory=list)
    # Distinguishes an explicit "no dietary restrictions" answer from unset preferences.
    food_preferences_configured: bool = False
    accessibility_needs: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    preferred_airlines: list[str] = Field(default_factory=list)
    preferred_hotel_chains: list[str] = Field(default_factory=list)
    hotel_style: HotelStyle | None = None
    budget_tier: BudgetTier = BudgetTier.mid
    travel_style: str | None = None  # "adventure"|"cultural"|"luxury"|"backpacker"|"family"
    fitness_level: str | None = None  # "low"|"moderate"|"high" — affects activity recommendations
    altitude_experience: bool | None = None  # True = has previously travelled above 3,000 m


def budget_to_state(budget: BudgetPreference | None) -> dict[str, str | float | None]:
    """Serialize BudgetPreference to a checkpoint-safe primitive dict."""
    if budget is None:
        return {"tier": "mid", "total_budget_inr": None, "per_day_budget_inr": None}
    return {
        "tier": str(budget.tier),
        "total_budget_inr": budget.total_budget_inr,
        "per_day_budget_inr": budget.per_day_budget_inr,
    }


def budget_from_state(value: object) -> BudgetPreference:
    """Deserialize budget state value to BudgetPreference safely.

    Accepts both the new primitive dict format and legacy BudgetPreference
    objects from older checkpoints.
    """
    if isinstance(value, BudgetPreference):
        return value

    if not isinstance(value, dict):
        return BudgetPreference()

    tier_raw = str(value.get("tier", "mid") or "mid").lower()
    tier = BudgetTier.mid
    if tier_raw in {"budget", "mid", "luxury"}:
        tier = BudgetTier(tier_raw)

    total_budget_inr = value.get("total_budget_inr")
    per_day_budget_inr = value.get("per_day_budget_inr")

    return BudgetPreference(
        tier=tier,
        total_budget_inr=(float(total_budget_inr) if total_budget_inr is not None else None),
        per_day_budget_inr=(float(per_day_budget_inr) if per_day_budget_inr is not None else None),
    )
