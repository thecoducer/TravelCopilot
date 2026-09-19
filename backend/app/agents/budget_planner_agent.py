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

from pydantic import BaseModel, Field

from app.agents.base import AgentClarificationMixin
from app.config import settings
from app.graph.state import TripStateModel
from app.llm import StructuredOutputError, get_llm, invoke_structured
from app.logging import get_agent_logger
from app.models.enums import AgentName, BudgetVerdict, LogEvent
from app.models.reports import BudgetReport
from app.models.transport import TransportRecommendation
from app.models.user_profile import budget_from_state
from app.prompts.budget_planner_agent_prompts import COST_ESTIMATE_PROMPT, COST_SAVING_TIPS_PROMPT
from app.services.currency_service import resolve_trip_currency
from app.services.fx_converter_service import FxConverter
from app.tools.factory import ToolFactory


def _all_legs_unpriced(by_leg: dict[str, TransportRecommendation]) -> bool:
    """True when every discovered leg came back with no usable option."""
    if not by_leg:
        return False
    return all(rec.no_result or rec.total_cost <= 0 for rec in by_leg.values())


def _per_day_breakdown(
    *, trip_days: int, accommodation: float, recurring: float, one_off: float
) -> list[float]:
    """Spread costs across days by how they are actually incurred.

    Accommodation is paid per night (one fewer than the day count), day-to-day
    spending is even, and one-off costs land on the first day. A flat
    ``total / trip_days`` would report a hotel charge on the checkout day and an
    identical figure for a travel day and a full sightseeing day.
    """
    if trip_days <= 0:
        return []
    nights = max(1, trip_days - 1)
    per_night = accommodation / nights
    per_day_recurring = recurring / trip_days
    return [
        round(
            per_day_recurring
            + (per_night if day < nights else 0.0)
            + (one_off if day == 0 else 0.0),
            2,
        )
        for day in range(trip_days)
    ]


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


class BudgetPlannerAgent(AgentClarificationMixin):
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

            def extract_name(item: Any) -> str:
                name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
                return name if isinstance(name, str) else ""

            # Extract sample venue names if available from state
            food_names: list[str] = []
            if isinstance(food_recs, list):
                food_names = [extract_name(item) for item in food_recs[:5]]
            elif isinstance(food_recs, dict):
                for item in list(food_recs.values())[:5]:
                    if isinstance(item, list) and item:
                        food_names.append(extract_name(item[0]))

            exp_names: list[str] = []
            if isinstance(experiences, list):
                exp_names = [extract_name(item) for item in experiences[:5]]

            res = await invoke_structured(
                self._llm,
                DestinationCostEstimate,
                COST_ESTIMATE_PROMPT.format_messages(
                    destination=destination,
                    dest_currency=dest_currency,
                    tier=tier,
                    travelers=travelers,
                    trip_days=trip_days,
                    food_names=", ".join(food_names) if food_names else "",
                    exp_names=", ".join(exp_names) if exp_names else "",
                ),
                agent=AgentName.BUDGET_PLANNER,
                log=log,
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
        except StructuredOutputError as exc:
            log.warning(
                LogEvent.AGENT_DEGRADED,
                section="cost_estimate",
                truncated=exc.truncated,
                error=str(exc),
            )

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
        preferred_currency = resolve_trip_currency(user_profile, log=log)
        dest_currency = (
            (transport_rec and transport_rec.currency_code)
            or (stays_pick and stays_pick.currency_code)
            or preferred_currency
        )

        # ── Cost components ───────────────────────────────────────────────
        transport_cost = transport_rec.total_cost if transport_rec else 0.0
        transport_currency = transport_rec.currency_code if transport_rec else dest_currency
        # A route whose legs all came back empty contributes zero cost, which would
        # otherwise read as a genuinely free journey and skew the verdict.
        transport_priced = bool(transport_rec) and not _all_legs_unpriced(
            s.transport_recommendation_by_leg
        )

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
        per_day = _per_day_breakdown(
            trip_days=trip_days,
            accommodation=per_category["accommodation"],
            recurring=per_category["food"] + per_category["activities"],
            one_off=per_category["transport"] + per_category["visa"] + per_category["self_drive"],
        )

        # Compare against stated budget
        stated_budget = budget.total_budget_inr if budget and budget.total_budget_inr else None
        if not transport_priced:
            verdict = BudgetVerdict.INCOMPLETE
            log.warning(
                LogEvent.SECTION_UNAVAILABLE,
                section="transport_cost",
                reason="no_priced_transport_options",
            )
        elif stated_budget:
            budget_in_dest = await fx_converter.convert(stated_budget, preferred_currency)
            if total > budget_in_dest * settings.budget_over_threshold_multiplier:
                verdict = BudgetVerdict.OVER_BUDGET
            elif total < budget_in_dest * settings.budget_under_threshold_multiplier:
                verdict = BudgetVerdict.UNDER_BUDGET
            else:
                verdict = BudgetVerdict.ON_BUDGET
        else:
            verdict = BudgetVerdict.ON_BUDGET  # no budget specified

        # LLM generates cost-saving tips if over budget
        cost_saving_tips: list[str] = []
        if verdict == BudgetVerdict.OVER_BUDGET:
            try:
                tips_result = await invoke_structured(
                    self._llm,
                    _CostSavingTips,
                    COST_SAVING_TIPS_PROMPT.format_messages(
                        destination=destination,
                        trip_days=trip_days,
                        travelers=travelers,
                        tier=tier,
                        cost_breakdown=json.dumps(per_category),
                    ),
                    agent=AgentName.BUDGET_PLANNER,
                    log=log,
                )
                cost_saving_tips = tips_result.tips
            except StructuredOutputError as exc:
                log.warning(LogEvent.AGENT_DEGRADED, section="cost_saving_tips", error=str(exc))

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
