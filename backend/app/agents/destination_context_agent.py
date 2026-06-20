"""DestinationContextAgent — Layer 1: seasonality, crowd, cost, risks.

Uses Tavily web search to gather real-time destination intelligence and
synthesises a ``DestinationContextReport`` via LLM structured output.
"""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import get_llm
from app.models.reports import DestinationContextReport
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a travel intelligence analyst. Based on the search results below, produce a
structured destination context report for the given destination and travel month.

Estimate ``real_daily_cost`` in the destination's local currency based on the search
results; include food, local transport, and one paid attraction per day.  Set
``currency_code`` to the correct ISO 4217 code.

``crowd_level`` must be exactly one of: Low, Moderate, High, Extreme.
``altitude_meters`` should only be set for destinations above 1500 m (mountain destinations).
``seasonal_risks`` should list concrete risks, e.g. "Typhoon season", "Flash floods".
"""


class DestinationContextAgent:
    """Layer 1 — Destination seasonality, crowd, practical costs, and local risks."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: object | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._tavily = factory.get("tavily_search")
        self._llm = llm or get_llm("destination_context")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        destination: str = state.get("destination", "")
        dates = state.get("dates")
        session_id: str = state.get("session_id", "")

        month = dates.departure.strftime("%B") if dates else "June"
        year = dates.departure.year if dates else 2026

        log = logger.bind(agent="destination_context", destination=destination, session_id=session_id)
        log.info("agent_start")

        # Run 3 Tavily searches in parallel
        import asyncio

        queries = [
            f"{destination} crowded {month} {year} tourist season",
            f"average daily cost {destination} backpacker mid-range {year}",
            f"{destination} seasonal risks weather {month} travel advisory",
        ]
        results = await asyncio.gather(
            *[
                self._tavily.run(query=q, destination=destination)
                for q in queries
            ],
            return_exceptions=True,
        )

        # Concatenate search result snippets
        snippets: list[str] = []
        for r in results:
            if isinstance(r, Exception):
                log.warning("tavily_error", error=str(r))
                continue
            for item in r.get("results", []):
                snippets.append(f"• {item.get('title', '')}: {item.get('content', '')[:300]}")

        context = "\n".join(snippets) if snippets else "No search results available."

        chain = self._llm.with_structured_output(DestinationContextReport)  # type: ignore[union-attr]
        try:
            report: DestinationContextReport = chain.invoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Destination: {destination}\n"
                            f"Travel month: {month} {year}\n\n"
                            f"Search results:\n{context}"
                        )
                    ),
                ]
            )
        except Exception as exc:
            log.error("llm_failed", error=str(exc))
            # Return a minimal fallback report so downstream agents are not blocked
            report = DestinationContextReport(
                destination=destination,
                travel_month=month,
                is_peak_season=False,
                season_label="Unknown",
                season_reason="Could not retrieve data",
                crowd_level="Moderate",
                crowd_notes="Data unavailable",
                real_daily_cost=0.0,
                currency_code="USD",
                seasonal_weather_summary="Data unavailable",
            )

        log.info("agent_done", crowd_level=report.crowd_level)
        return {"destination_context_report": report}
