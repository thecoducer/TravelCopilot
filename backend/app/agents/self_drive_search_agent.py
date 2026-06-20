"""SelfDriveSearchAgent — Layer 3: vehicle rental + fuel estimate (conditional).

Only activates when ``state["self_drive_intent"] == True``.
Returns ``self_drive_report=None`` immediately for trips without self-drive.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import get_llm
from app.models.reports import SelfDriveReport
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a self-drive trip planning expert. Based on the rental options and trip details,
produce a self-drive report for the traveller.

Rules:
- ``recommended_vehicle`` should be a specific vehicle type (e.g. "Royal Enfield 350cc").
- ``total_km_estimate`` should be a realistic estimate for the trip itinerary.
- ``fuel_cost_estimate`` = total_km / mileage × fuel_price (use given mileage constants).
- ``toll_estimate`` = 10–15% of fuel_cost for highway-heavy routes; 0 for mountain roads.
- ``local_driving_tips`` should include altitude, road condition, permit, and traffic tips.
- ``permits_required`` should list specific permit names with fees if known.
- Mileage constants: scooter 40 km/L, motorcycle 30 km/L, hatchback 15 km/L, SUV 12 km/L.
"""

# Typical mileage in km/L by vehicle category
_MILEAGE: dict[str, float] = {
    "scooter": 40.0,
    "motorcycle": 30.0,
    "motorbike": 30.0,
    "hatchback": 15.0,
    "sedan": 13.0,
    "suv": 12.0,
    "jeep": 10.0,
}


class SelfDriveSearchAgent:
    """Layer 3 — Conditional: rental options + fuel estimate for self-drive trips."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: object | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._rental_tool = factory.get("rental_search")
        self._fuel_tool = factory.get("fuel_price")
        self._distance_tool = factory.get("distance_matrix")
        self._llm = llm or get_llm("self_drive_search")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        if not state.get("self_drive_intent", False):
            return {"self_drive_report": None}

        destination: str = state.get("destination", "")
        dates = state.get("dates")
        session_id: str = state.get("session_id", "")

        log = logger.bind(agent="self_drive_search", destination=destination, session_id=session_id)
        log.info("agent_start")

        trip_days = dates.trip_days if dates else 3

        import asyncio

        rentals_result, fuel_result = await asyncio.gather(
            self._rental_tool.run(destination=destination),
            self._fuel_tool.run(destination=destination),
            return_exceptions=True,
        )

        rentals: list[dict[str, Any]] = []
        if not isinstance(rentals_result, Exception):
            rentals = rentals_result.get("rentals", [])

        fuel_price = 104.0  # INR/L fallback
        if not isinstance(fuel_result, Exception):
            fuel_price = float(fuel_result.get("price_per_litre", 104.0))

        # Rough distance estimate: 80 km/day in a hilly destination
        estimated_km_per_day = 80.0
        total_km = estimated_km_per_day * trip_days

        chain = self._llm.with_structured_output(SelfDriveReport)  # type: ignore[union-attr]
        try:
            report: SelfDriveReport = chain.invoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Destination: {destination}\n"
                            f"Trip days: {trip_days}\n"
                            f"Fuel price: ₹{fuel_price}/L\n"
                            f"Estimated total km: {total_km}\n\n"
                            f"Available rentals (JSON):\n{json.dumps(rentals[:6], indent=2)}"
                        )
                    ),
                ]
            )
        except Exception as exc:
            log.error("llm_failed", error=str(exc))
            report = SelfDriveReport(
                destination=destination,
                rental_options=rentals[:6],
                total_km_estimate=total_km,
                fuel_cost_estimate=round(total_km / 30.0 * fuel_price, 2),
            )

        log.info("agent_done", vehicle=report.recommended_vehicle, km=report.total_km_estimate)
        return {"self_drive_report": report}
