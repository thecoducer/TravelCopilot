"""BudgetPlannerAgent — Layer 4: cost aggregation + FX normalisation + verdict.

Aggregates costs from all previous layers into a ``BudgetReport`` with:
  - Per-category breakdown (transport, stay, food, activities, visa, self-drive)
  - Per-day breakdown
  - FX-normalised totals (destination currency → user's preferred currency)
  - vs-budget verdict and cost-saving tips if over budget
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog

from app.llm import get_llm
from app.models.reports import BudgetReport, FxRateEntry
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a travel budget analyst. Given the cost breakdown below, produce a complete
budget report for the traveller.

Rules:
- ``currency_code`` should be the destination's local currency (ISO 4217).
- ``total_estimated_cost`` is the sum of all per-category costs in the destination currency.
- ``per_day_breakdown`` is a list of per-day cost estimates; length must equal trip_days.
- ``vs_budget_verdict`` must be one of: "on-budget" | "over" | "under".
- ``cost_saving_tips`` must only be populated when ``vs_budget_verdict == "over"``.
- ``per_person_cost`` = total_estimated_cost / travelers.
"""


class BudgetPlannerAgent:
    """Layer 4 — Cost aggregation, FX conversion, and budget verdict."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: object | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._fx_tool = factory.get("currency_convert")
        self._llm = llm or get_llm("budget_planner")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        destination: str = state.get("destination", "")
        travelers: int = state.get("travelers", 1)
        dates = state.get("dates")
        budget = state.get("budget")
        user_profile = state.get("user_profile")
        session_id: str = state.get("session_id", "")

        transport_rec = state.get("transport_recommendation")
        stays_pick = state.get("stays_pick")
        destination_ctx = state.get("destination_context_report")
        visa_report = state.get("visa_report")
        self_drive_report = state.get("self_drive_report")

        log = logger.bind(agent="budget_planner", destination=destination, session_id=session_id)
        log.info("agent_start")

        trip_days = dates.trip_days if dates else 3
        preferred_currency = (user_profile and user_profile.preferred_currency) or "INR"
        dest_currency = (destination_ctx and destination_ctx.currency_code) or "INR"

        # ── Cost components ───────────────────────────────────────────────
        transport_cost = transport_rec.total_cost if transport_rec else 0.0
        transport_currency = transport_rec.currency_code if transport_rec else dest_currency

        stay_cost_per_night = stays_pick.price_per_night if stays_pick else 0.0
        stay_currency = stays_pick.currency_code if stays_pick else dest_currency
        stay_total = stay_cost_per_night * trip_days * travelers

        # Food: ~35% of real_daily_cost estimate
        daily_cost = (destination_ctx and destination_ctx.real_daily_cost) or 0.0
        food_total = daily_cost * 0.35 * trip_days * travelers

        # Activities: rough estimate — ₹500–2000/person/day depending on budget tier
        tier = budget.tier if budget else "mid"
        activity_daily = {"budget": 500.0, "mid": 1500.0, "luxury": 4000.0}.get(tier, 1500.0)
        activities_total = activity_daily * trip_days * travelers

        visa_cost = 0.0
        if visa_report and visa_report.fees:
            try:
                # Fees are stored as a string like "₹4,000" or "USD 160"
                visa_cost = float("".join(c for c in visa_report.fees if c.isdigit() or c == "."))
            except ValueError:
                pass

        self_drive_cost = 0.0
        if self_drive_report:
            self_drive_cost = (self_drive_report.fuel_cost_estimate or 0.0) + (
                self_drive_report.toll_estimate or 0.0
            )

        # ── FX normalisation to destination currency ──────────────────────
        fx_rates_used: dict[str, FxRateEntry] = {}

        async def _convert(amount: float, from_ccy: str) -> float:
            if from_ccy == dest_currency or amount == 0:
                return amount
            try:
                result = await self._fx_tool.run(
                    amount=amount, base=from_ccy, quote=dest_currency
                )
                rate = result.get("rate", 1.0)
                fetched_at_str = result.get("fetched_at", datetime.now(tz=UTC).isoformat())
                fx_rates_used[f"{from_ccy}→{dest_currency}"] = FxRateEntry(
                    rate=rate, fetched_at=datetime.fromisoformat(fetched_at_str.replace("Z", "+00:00"))
                )
                return float(result.get("amount_converted", amount))
            except Exception:
                return amount


        transport_converted = await _convert(transport_cost, transport_currency)
        stay_converted = await _convert(stay_total, stay_currency)

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
            budget_in_dest = await _convert(stated_budget, preferred_currency)
            if total > budget_in_dest * 1.1:
                verdict = "over"
            elif total < budget_in_dest * 0.9:
                verdict = "under"
            else:
                verdict = "on-budget"
        else:
            verdict = "on-budget"  # no budget specified

        # LLM generates cost-saving tips if over budget
        cost_saving_tips: list[str] = []
        if verdict == "over":
            try:
                from langchain_core.messages import HumanMessage as HM
                from langchain_core.messages import SystemMessage as SM
                from pydantic import BaseModel as BM

                class _Tips(BM):
                    tips: list[str]

                chain = self._llm.with_structured_output(_Tips)  # type: ignore[union-attr]
                tips_result: _Tips = chain.invoke(
                    [
                        SM(content="You are a budget travel advisor."),
                        HM(
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

        fx_disclaimer = None
        if fx_rates_used:
            fx_disclaimer = (
                "Exchange rates are indicative and fetched at planning time. "
                "Actual costs may vary with live rates."
            )

        report = BudgetReport(
            currency_code=dest_currency,
            total_estimated_cost=round(total, 2),
            fx_rates_used=fx_rates_used,
            fx_disclaimer=fx_disclaimer,
            per_category_breakdown=per_category,
            per_day_breakdown=per_day,
            vs_budget_verdict=verdict,
            cost_saving_tips=cost_saving_tips,
            per_person_cost=round(total / travelers, 2) if travelers else total,
        )

        log.info("agent_done", total=total, verdict=verdict, currency=dest_currency)
        return {"budget_report": report}
