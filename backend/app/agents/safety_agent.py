"""SafetyAgent — Layer 4: venue-aware safety advisories and scam warnings.

Runs after FoodDiscoveryAgent so it has the actual experience spots, restaurants,
and neighbourhoods in state.  This allows the report to cross-reference specific
venues rather than issuing only generic destination-level warnings.

Inputs consumed from state:
  - ``destination``        — for Tavily queries
  - ``experiences_raw``    — attraction / activity names and areas
  - ``food_recommendations`` — restaurant / cafe names per day
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.agents.base import AgentClarificationMixin
from app.llm import StructuredOutputError, get_llm, invoke_structured
from app.logging import get_agent_logger
from app.models.enums import AgentName, LogEvent, SectionStatus
from app.models.reports import SafetyReport
from app.prompts.safety_agent_prompts import SAFETY_REPORT_PROMPT
from app.services.cache_service import TTL_TAVILY, cache_service
from app.tools.factory import ToolFactory


class SafetyAgent(AgentClarificationMixin):
    """Layer 4 — Destination context, scam warnings, and emergency contacts.

    Runs after FoodDiscoveryAgent so ``experiences_raw`` and ``food_recommendations``
    are already populated in state, enabling venue-specific warnings.
    """

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: Any | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._tavily = factory.get("tavily_search")
        self._llm = llm or get_llm("safety")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        destination: str = state.get("destination", "")
        session_id: str = state.get("session_id", "")
        dates = state.get("dates")
        month = dates.departure.strftime("%B") if dates else "June"
        year = dates.departure.year if dates else 2026

        log = get_agent_logger("safety", session_id, destination=destination)
        log.info("agent_start")

        import asyncio

        # Two broad queries instead of five narrow ones: the LLM extracts each
        # sub-topic (scams, crowds, altitude, seasonal) from the combined results.
        queries = [
            f"tourist scams and safety tips {destination} travel advisory 2026",
            f"{destination} {month} {year} crowd levels altitude elevation risks"
            " seasonal weather travel advisory",
        ]
        results = await asyncio.gather(
            *[self._cached_tavily_search(q, destination, month) for q in queries],
            return_exceptions=True,
        )

        snippets: list[str] = []
        for r in results:
            if isinstance(r, BaseException):
                log.warning("tavily_error", error=str(r))
                continue
            if r.get("answer"):
                snippets.append(f"Summary: {r['answer']}")
            for item in r.get("results", []):
                snippets.append(f"• {item.get('title', '')}: {item.get('content', '')[:400]}")

        context = "\n".join(snippets) if snippets else "No search results available."

        # ── Build venue context from state ────────────────────────────────────
        experiences_raw: list[Any] = state.get("experiences_raw", [])
        food_recommendations: dict[str, list[Any]] = state.get("food_recommendations", {})

        experience_names: list[str] = [
            e.name if hasattr(e, "name") else e.get("name", "") for e in experiences_raw if e
        ]
        food_names: list[str] = [
            v.name if hasattr(v, "name") else v.get("name", "")
            for day_venues in food_recommendations.values()
            for v in day_venues
            if v
        ]
        venue_section = ""
        if experience_names or food_names:
            venue_section = "\n\nVenues in this traveller's itinerary:\n"
            if experience_names:
                venue_section += "Experiences: " + ", ".join(experience_names[:20]) + "\n"
            if food_names:
                venue_section += "Food outlets: " + ", ".join(food_names[:20]) + "\n"

        try:
            report = await invoke_structured(
                self._llm,
                SafetyReport,
                SAFETY_REPORT_PROMPT.format_messages(
                    destination=destination,
                    context=context,
                    venue_section=venue_section,
                ),
                agent=AgentName.SAFETY,
                session_id=session_id,
                log=log,
            )
            report = report.model_copy(update={"status": SectionStatus.POPULATED})
        except StructuredOutputError as exc:
            log.error(
                LogEvent.AGENT_DEGRADED,
                section="safety",
                truncated=exc.truncated,
                error=str(exc),
            )
            # No placeholder prose: a caller must be able to tell this section apart
            # from one that genuinely had nothing to report.
            report = SafetyReport(
                destination=destination,
                travel_month=month,
                status=SectionStatus.UNAVAILABLE,
            )

        log.info(LogEvent.AGENT_DONE, scams_found=len(report.top_scams), status=report.status)
        return {"safety_report": report}

    async def _cached_tavily_search(self, query: str, destination: str, month: str) -> Any:
        """Tavily results rarely change within a day — cache by destination/month/query."""
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        key = cache_service.tavily_key(destination, month, query_hash)
        return await cache_service.get_or_set(
            key, TTL_TAVILY, lambda: self._tavily.run(query=query, destination=destination)
        )
