"""BudgetPlannerAgent — Layer 4: cost aggregation + FX normalisation + verdict.

Aggregates costs from all previous layers into a ``BudgetReport`` with:
  - Per-category breakdown (transport, stay, food, activities, visa, self-drive)
  - Per-day breakdown
  - FX-normalised totals (destination currency → user's preferred currency)
  - vs-budget verdict and cost-saving tips if over budget
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.graph.state import TripStateModel
from app.llm import get_llm
from app.logging import get_agent_logger
from app.models.reports import BudgetReport
from app.models.user_profile import budget_from_state
from app.services.fx_converter_service import FxConverter
from app.tools.factory import ToolFactory

_SYSTEM_PROMPT = """\
You are a travel budget analyst and cost estimator with deep knowledge of global pricing.
Given a travel destination, budget tier, and trip parameters, estimate realistic daily food and \
activity costs.

Rules:
- Estimates MUST be in the destination's local currency.
- ``daily_food_per_person``: Average daily spending per person for meals, drinks, and dining.
- ``daily_activity_per_person``: Average daily spending per person for entry fees and tours.
"""


class DestinationCostEstimate(BaseModel):
    """LLM-estimated daily per-person cost for food and activities in destination local currency."""

    daily_food_per_person: float = Field(
        default=0.0,
        description="Estimated daily food/dining cost per person in local currency.",
    )
    daily_activity_per_person: float = Field(
        default=0.0,
        description="Estimated daily activity/sightseeing cost per person in local currency.",
    )
    rationale: str = Field(
        default="",
        description="Brief explanation of estimate based on destination pricing and budget tier.",
    )


class _CostSavingTips(BaseModel):
    """Structured output schema for cost-saving tips."""

    tips: list[str] = Field(default_factory=list)


class BudgetPlannerAgent:
    """Layer 4 — Cost aggregation, FX conversion, and budget verdict."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: Any | None = None,
        fx_converter: FxConverter | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._tool_factory = factory
        self._fx_tool = factory.get("currency_convert")
        self._fx_converter = fx_converter
        self._llm = llm or get_llm("budget_planner")

    async def _estimate_food_and_activities(
        self,
        destination: str,
        dest_currency: str,
        tier: str,
        trip_days: int,
        travelers: int,
        food_recs: list[Any] | dict[str, Any],
        experiences: list[Any] | dict[str, Any],
        log: Any,
    ) -> tuple[float, float]:
        """Estimate food and activity totals in `dest_currency` using LLM world knowledge."""
        try:
            # Extract sample venue names if available from state
            food_names: list[str] = []
            if isinstance(food_recs, list):
                food_names = [
                    f.get("name") if isinstance(f, dict) else getattr(f, "name", str(f))
                    for f in food_recs[:5]
                ]
            elif isinstance(food_recs, dict):
                for item in list(food_recs.values())[:5]:
                    if isinstance(item, list) and item:
                        first = item[0]
                        food_names.append(
                            first.get("name")
                            if isinstance(first, dict)
                            else getattr(first, "name", str(first))
                        )

            exp_names: list[str] = []
            if isinstance(experiences, list):
                exp_names = [
                    e.get("name") if isinstance(e, dict) else getattr(e, "name", str(e))
                    for e in experiences[:5]
                ]

            prompt = (
                f"Destination: {destination}\n"
                f"Destination Currency: {dest_currency}\n"
                f"Budget Tier: {tier}\n"
                f"Travelers: {travelers}, Trip Duration: {trip_days} days\n"
            )
            if food_names:
                prompt += f"Discovered Food Venues: {', '.join(food_names)}\n"
            if exp_names:
                prompt += f"Discovered Activities: {', '.join(exp_names)}\n"

            prompt += (
                f"Estimate realistic daily per-person food and activity costs for "
                f"{destination} in {dest_currency} matching the '{tier}' budget tier."
            )

            chain = self._llm.with_structured_output(DestinationCostEstimate)
            res = await chain.ainvoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )

            daily_food = float(getattr(res, "daily_food_per_person", 0.0) or 0.0)
            daily_activity = float(getattr(res, "daily_activity_per_person", 0.0) or 0.0)

            if daily_food > 0 and daily_activity > 0:
                food_total = daily_food * trip_days * travelers
                activities_total = daily_activity * trip_days * travelers
                log.info(
                    "llm_cost_estimation_success",
                    daily_food=daily_food,
                    daily_activity=daily_activity,
                    currency=dest_currency,
                )
                return round(food_total, 2), round(activities_total, 2)
        except Exception as exc:
            log.warning("llm_cost_estimation_failed", error=str(exc))

        # Safe fallback baseline if LLM call is unavailable or unparseable
        fallback_daily_activity = settings.fallback_daily_activity_costs.get(
            tier, settings.fallback_daily_activity_cost_mid
        )
        fallback_daily_food = fallback_daily_activity * settings.fallback_daily_food_ratio
        return (
            round(fallback_daily_food * trip_days * travelers, 2),
            round(fallback_daily_activity * trip_days * travelers, 2),
        )

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        s = TripStateModel.from_state(state)
        destination = s.destination
        travelers = s.travelers
        dates = s.dates
        budget = budget_from_state(s.budget)
        user_profile = s.user_profile
        session_id = s.session_id

        transport_rec = s.transport_recommendation
        stays_pick = s.stays_pick
        stays_pick_by_stop = s.stays_pick_by_stop
        stops = s.stops
        route_discovery_status = s.route_discovery_status
        visa_report = s.visa_report
        self_drive_report = s.self_drive_report

        log = get_agent_logger("budget_planner", session_id, destination=destination)
        log.info("agent_start")

        trip_days = dates.trip_days if dates else settings.default_trip_days
        preferred_currency = (
            user_profile and user_profile.preferred_currency
        ) or settings.default_currency
        dest_currency = (
            (transport_rec and transport_rec.currency_code)
            or (stays_pick and stays_pick.currency_code)
            or settings.default_currency
        )

        # ── Cost components ───────────────────────────────────────────────
        transport_cost = transport_rec.total_cost if transport_rec else 0.0
        transport_currency = transport_rec.currency_code if transport_rec else dest_currency

        # Food & Activities: LLM world-knowledge destination cost estimation
        tier = budget.tier if budget else settings.default_budget_tier
        food_recs = s.food_recommendations_by_stop or s.food_recommendations
        experiences = s.experiences_raw_by_stop or s.experiences_raw

        food_total, activities_total = await self._estimate_food_and_activities(
            destination=destination,
            dest_currency=dest_currency,
            tier=tier,
            trip_days=trip_days,
            travelers=travelers,
            food_recs=food_recs,
            experiences=experiences,
            log=log,
        )

        visa_cost = 0.0
        if visa_report and visa_report.fees:
            with contextlib.suppress(ValueError):
                # Fees are stored as a string like "₹4,000" or "USD 160"
                visa_cost = float("".join(c for c in visa_report.fees if c.isdigit() or c == "."))

        self_drive_cost = 0.0
        if self_drive_report:
            self_drive_cost = (self_drive_report.fuel_cost_estimate or 0.0) + (
                self_drive_report.toll_estimate or 0.0
            )

        # ── FX normalisation to destination currency ──────────────────────
        fx_converter = self._fx_converter or FxConverter(
            target_currency=dest_currency,
            fx_tool=self._fx_tool,
            tool_factory=self._tool_factory,
        )
        fx_converter.target_currency = dest_currency

        transport_converted = await fx_converter.convert(transport_cost, transport_currency)

        # Accommodation is price_per_night × stop.nights × travelers — never one
        # stay multiplied by the whole trip's day count (see
        # specs/stops-discovery-agent-spec.md budget aggregation contract).
        per_stop_accommodation: dict[str, float] = {}
        if route_discovery_status == "multi_stop_provisional" and stays_pick_by_stop:
            stay_converted = 0.0
            for stop_id, stay in stays_pick_by_stop.items():
                stop = stops.get(stop_id)
                nights = stop.nights if stop else 1
                raw_cost = stay.price_per_night * nights * travelers
                converted_cost = await fx_converter.convert(raw_cost, stay.currency_code)
                per_stop_accommodation[stop_id] = round(converted_cost, 2)
                stay_converted += converted_cost
        else:
            stay_cost_per_night = stays_pick.price_per_night if stays_pick else 0.0
            stay_currency = stays_pick.currency_code if stays_pick else dest_currency
            stay_total = stay_cost_per_night * trip_days * travelers
            stay_converted = await fx_converter.convert(stay_total, stay_currency)

        per_category: dict[str, float] = {
            "transport": round(transport_converted, 2),
            "accommodation": round(stay_converted, 2),
            "food": round(food_total, 2),
            "activities": round(activities_total, 2),
            "visa": round(visa_cost, 2),
            "self_drive": round(self_drive_cost, 2),
        }

        total = sum(per_category.values())
        per_day = [round(total / trip_days, 2)] * trip_days if trip_days else []

        # Compare against stated budget
        stated_budget = budget.total_budget_inr if budget and budget.total_budget_inr else None
        if stated_budget:
            budget_in_dest = await fx_converter.convert(stated_budget, preferred_currency)
            if total > budget_in_dest * settings.budget_over_threshold_multiplier:
                verdict = "over"
            elif total < budget_in_dest * settings.budget_under_threshold_multiplier:
                verdict = "under"
            else:
                verdict = "on-budget"
        else:
            verdict = "on-budget"  # no budget specified

        # LLM generates cost-saving tips if over budget
        cost_saving_tips: list[str] = []
        if verdict == "over":
            try:
                chain = self._llm.with_structured_output(_CostSavingTips)
                tips_result: _CostSavingTips = await chain.ainvoke(
                    [
                        SystemMessage(content="You are a budget travel advisor."),
                        HumanMessage(
                            content=(
                                f"Trip to {destination}, {trip_days} days, {travelers} travelers.\n"
                                f"Budget tier: {tier}. Currently over budget.\n"
                                f"Cost breakdown: {json.dumps(per_category)}\n\n"
                                "Provide 3–5 specific, actionable cost-saving tips."
                            )
                        ),
                    ]
                )
                cost_saving_tips = tips_result.tips
            except Exception as exc:
                log.warning("tips_llm_failed", error=str(exc))

        report = BudgetReport(
            currency_code=dest_currency,
            total_estimated_cost=round(total, 2),
            fx_rates_used=fx_converter.fx_rates_used,
            fx_disclaimer=fx_converter.fx_disclaimer,
            per_category_breakdown=per_category,
            per_day_breakdown=per_day,
            vs_budget_verdict=verdict,
            cost_saving_tips=cost_saving_tips,
            per_person_cost=round(total / travelers, 2) if travelers else total,
            per_stop_accommodation_breakdown=per_stop_accommodation,
        )

        log.info("agent_done", total=total, verdict=verdict, currency=dest_currency)
        return {"budget_report": report}
