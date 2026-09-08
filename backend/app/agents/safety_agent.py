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

from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import get_llm
from app.models.reports import ScamSafetyReport
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a travel safety analyst. Based on the search results and venue list below, produce a
structured safety report for travellers visiting the given destination.

Rules:
- ``advisory_level`` should reflect official government guidance: "Exercise normal caution" |
  "Exercise increased caution" | "Reconsider travel" | "Do not travel".
- ``top_scams`` should include 2–5 specific, actionable scam entries with how-to-avoid advice.
  Where a scam is associated with a venue or neighbourhood listed in the traveller's actual
  itinerary (see Venues section), mention that venue by name so the warning is immediately useful.
- ``safe_areas`` should name specific neighbourhoods or districts travellers can rely on.
- ``emergency_contacts`` must include police, ambulance, and tourist helpline numbers if available.
- ``women_safety_notes`` and ``medical_facilities`` should only be populated with concrete, useful
  information — leave null if nothing specific is known.
"""


class SafetyAgent:
    """Layer 4 — Venue-aware scam warnings, safety advisories, and emergency contacts.

    Runs after FoodDiscoveryAgent so ``experiences_raw`` and ``food_recommendations``
    are already populated in state, enabling venue-specific warnings.
    """

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: object | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._tavily = factory.get("tavily_search")
        self._llm = llm or get_llm("safety")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        destination: str = state.get("destination", "")
        session_id: str = state.get("session_id", "")

        log = logger.bind(agent="safety", destination=destination, session_id=session_id)
        log.info("agent_start")

        import asyncio

        queries = [
            f"tourist scams {destination} 2026 how to avoid",
            f"safety tips {destination} travel advisory",
        ]
        results = await asyncio.gather(
            *[self._tavily.run(query=q, destination=destination) for q in queries],
            return_exceptions=True,
        )

        snippets: list[str] = []
        for r in results:
            if isinstance(r, Exception):
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

        chain = self._llm.with_structured_output(ScamSafetyReport)  # type: ignore[union-attr]
        try:
            report: ScamSafetyReport = chain.invoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Destination: {destination}\n\n"
                            f"Search results:\n{context}"
                            f"{venue_section}"
                        )
                    ),
                ]
            )
        except Exception as exc:
            log.error("llm_failed", error=str(exc))
            report = ScamSafetyReport(
                destination=destination,
                advisory_level="Exercise normal caution",
            )

        log.info("agent_done", scams_found=len(report.top_scams))
        return {"scam_safety_report": report}
