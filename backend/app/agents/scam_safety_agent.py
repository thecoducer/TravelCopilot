"""ScamSafetyAgent — Layer 1: safety advisories, scam warnings, emergency contacts.

Uses Tavily to search for destination-specific safety information and
synthesises a ``ScamSafetyReport`` via LLM.
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
You are a travel safety analyst. Based on the search results below, produce a structured
safety report for travellers visiting the given destination.

Rules:
- ``advisory_level`` should reflect official government guidance: "Exercise normal caution" |
  "Exercise increased caution" | "Reconsider travel" | "Do not travel".
- ``top_scams`` should include 2–5 specific, actionable scam entries with how-to-avoid advice.
- ``safe_areas`` should name specific neighbourhoods or districts travellers can rely on.
- ``emergency_contacts`` must include police, ambulance, and tourist helpline numbers if available.
- ``women_safety_notes`` and ``medical_facilities`` should only be populated with concrete, useful
  information — leave null if nothing specific is known.
"""


class ScamSafetyAgent:
    """Layer 1 — Scam warnings, safety advisories, and emergency contacts."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: object | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._tavily = factory.get("tavily_search")
        self._llm = llm or get_llm("scam_safety")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        destination: str = state.get("destination", "")
        session_id: str = state.get("session_id", "")

        log = logger.bind(agent="scam_safety", destination=destination, session_id=session_id)
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
            # Include the Tavily answer summary if present
            if r.get("answer"):
                snippets.append(f"Summary: {r['answer']}")
            for item in r.get("results", []):
                snippets.append(f"• {item.get('title', '')}: {item.get('content', '')[:400]}")

        context = "\n".join(snippets) if snippets else "No search results available."

        chain = self._llm.with_structured_output(ScamSafetyReport)  # type: ignore[union-attr]
        try:
            report: ScamSafetyReport = chain.invoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(
                        content=f"Destination: {destination}\n\nSearch results:\n{context}"
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
