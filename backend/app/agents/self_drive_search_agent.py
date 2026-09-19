"""SelfDriveSearchAgent — Layer 3: vehicle rental + fuel estimate (conditional).

Only activates when ``state["self_drive_intent"] == True``.
Returns ``self_drive_report=None`` immediately for trips without self-drive.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any

from app.agents.base import AgentClarificationMixin
from app.llm import StructuredOutputError, get_llm, invoke_structured
from app.logging import get_agent_logger
from app.models.enums import AgentName, LogEvent
from app.models.reports import SelfDriveReport
from app.prompts.self_drive_search_agent_prompts import SELF_DRIVE_REPORT_PROMPT
from app.tools.factory import ToolFactory


class SelfDriveSearchAgent(AgentClarificationMixin):
    """Layer 3 — Conditional: rental options + fuel estimate for self-drive trips."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: Any | None = None,
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

        log = get_agent_logger("self_drive_search", session_id, destination=destination)
        log.info("agent_start")

        trip_days = dates.trip_days if dates else 3

        rentals_result: dict[str, Any] | BaseException
        fuel_result: dict[str, Any] | BaseException
        rentals_result, fuel_result = await asyncio.gather(
            self._rental_tool.run(destination=destination),
            self._fuel_tool.run(destination=destination),
            return_exceptions=True,
        )

        rentals: list[dict[str, Any]] = []
        if not isinstance(rentals_result, BaseException):
            rentals = rentals_result.get("rentals", [])

        fuel_price = 104.0  # INR/L fallback
        if not isinstance(fuel_result, BaseException):
            raw_fuel_price = fuel_result.get("price_per_litre")
            if raw_fuel_price is not None:
                with suppress(TypeError, ValueError):
                    fuel_price = float(raw_fuel_price)

        # Rough distance estimate: 80 km/day in a hilly destination
        estimated_km_per_day = 80.0
        total_km = estimated_km_per_day * trip_days

        try:
            report = await invoke_structured(
                self._llm,
                SelfDriveReport,
                SELF_DRIVE_REPORT_PROMPT.format_messages(
                    destination=destination,
                    trip_days=trip_days,
                    fuel_price=fuel_price,
                    total_km=total_km,
                    rentals=json.dumps(rentals[:6], indent=2),
                ),
                agent=AgentName.SELF_DRIVE_SEARCH,
                log=log,
            )
        except StructuredOutputError as exc:
            log.error(LogEvent.AGENT_DEGRADED, section="self_drive", error=str(exc))
            report = SelfDriveReport(
                destination=destination,
                rental_options=rentals[:6],
                total_km_estimate=total_km,
                fuel_cost_estimate=round(total_km / 30.0 * fuel_price, 2),
            )

        log.info("agent_done", vehicle=report.recommended_vehicle, km=report.total_km_estimate)
        return {"self_drive_report": report}
