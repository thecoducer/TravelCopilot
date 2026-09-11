"""VisaAgent — Layer 1: visa requirements + embassy + application centre.

Only activates for international trips (``state["is_international"] == True``).

Grounding rules (G):
  - ``sources[]`` is populated from Tavily result URLs.
    - The LLM evaluates source provenance and sets ``confidence`` accordingly.
  - ``visa_required`` is never asserted without at least one source.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import get_llm
from app.logging import get_agent_logger
from app.models.reports import VisaReport, VisaSource
from app.tools.factory import ToolFactory

_SYSTEM_PROMPT = """\
You are an expert visa and immigration adviser. Based on the search results below,
produce a complete visa report.

Critical rules:
- ``application_process`` must be a numbered ordered list of concrete steps.
- Include ``disclaimer`` reminding travellers to verify with the official consulate.
- If search results are insufficient, lean conservative: flag uncertainty in
  ``validity_notes``.
- Decide which cited sources are official based on their content and provenance,
    not a fixed domain allowlist. Set ``confidence`` to "high" only when at least
    one source is official, "medium" when sources exist but none are official,
    and "low" when no reliable source supports the report.
"""


class VisaAgent:
    """Layer 1 — Visa requirements, embassy, and application centre details."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: Any | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._tavily = factory.get("tavily_search")
        self._visa_centre = factory.get("visa_centre_search")
        self._embassy = factory.get("embassy_search")
        self._llm = llm or get_llm("visa")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        if not state.get("is_international", False):
            return {"visa_report": None}

        destination: str = state.get("destination", "")
        session_id: str = state.get("session_id", "")
        user_profile = state.get("user_profile")
        passport_country = (user_profile.passport_country if user_profile else None) or "Unknown"
        home_city = (user_profile.home_city if user_profile else None) or "Unknown"
        destination_country = destination

        log = get_agent_logger("visa", session_id, destination=destination)
        log.info("agent_start", passport=passport_country)

        import asyncio

        tavily_task = self._tavily.run(
            query=(
                f"{passport_country} passport visa requirements {destination} this year "
                "official embassy application centre"
            ),
            destination=destination,
        )
        centre_task = self._visa_centre.run(
            passport_country=passport_country,
            destination_country=destination_country,
            home_city=home_city,
        )
        embassy_task = self._embassy.run(
            passport_country=passport_country,
            destination_country=destination_country,
            home_city=home_city,
        )

        tavily_result: dict[str, Any] | BaseException
        centre_result: dict[str, Any] | BaseException
        embassy_result: dict[str, Any] | BaseException
        tavily_result, centre_result, embassy_result = await asyncio.gather(
            tavily_task, centre_task, embassy_task, return_exceptions=True
        )

        # ── Grounding (G) ────────────────────────────────────────────────
        raw_results: list[dict[str, Any]] = []
        if not isinstance(tavily_result, BaseException):
            raw_results = tavily_result.get("results", [])

        sources: list[VisaSource] = [
            VisaSource(
                title=item.get("title", ""),
                url=item.get("url", ""),
                published_or_fetched_date=item.get("published_date"),
            )
            for item in raw_results
            if item.get("url")
        ]

        # Fixture / tool sources (visa_centre tool returns its own sources)
        if not isinstance(centre_result, BaseException):
            for src in centre_result.get("sources", []):
                if isinstance(src, dict) and src.get("url"):
                    sources.append(
                        VisaSource(
                            title=src.get("title", "Visa centre source"),
                            url=src["url"],
                            published_or_fetched_date=centre_result.get("last_verified_at"),
                        )
                    )

        # Build LLM context
        snippets: list[str] = []
        if not isinstance(tavily_result, BaseException):
            if tavily_result.get("answer"):
                snippets.append(f"Summary: {tavily_result['answer']}")
            for item in raw_results[:5]:
                snippets.append(
                    f"• {item.get('title', '')} ({item.get('url', '')}): "
                    f"{item.get('content', '')[:400]}"
                )
        if not isinstance(centre_result, BaseException) and centre_result.get("application_centre"):
            c = centre_result["application_centre"]
            snippets.append(
                f"Application centre: {c.get('name', '')} — {c.get('address', '')} "
                f"| Booking: {c.get('booking_url', 'N/A')}"
            )
        if not isinstance(embassy_result, BaseException) and embassy_result.get("embassy"):
            e = embassy_result["embassy"]
            snippets.append(
                f"Embassy: {e.get('name', '')} — {e.get('address', '')}"
                f" | Phone: {e.get('phone', 'N/A')}"
            )

        context = "\n".join(snippets) if snippets else "No visa information found."

        # (G) Never assert visa_required without at least one source
        if not sources:
            log.warning("no_visa_sources", forcing_confidence_low=True)
            return {
                "visa_report": VisaReport(
                    passport_country=passport_country,
                    destination_country=destination_country,
                    visa_required=True,
                    confidence="low",
                    validity_notes=(
                        "No grounded sources found — verify directly with consulate before booking."
                    ),
                )
            }

        chain = self._llm.with_structured_output(VisaReport)
        try:
            report: VisaReport = await chain.ainvoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Passport country: {passport_country}\n"
                            f"Destination country: {destination_country}\n\n"
                            f"Search results:\n{context}"
                        )
                    ),
                ]
            )
            report = report.model_copy(
                update={
                    "sources": sources,
                    "last_verified_at": datetime.now(tz=UTC),
                    "passport_country": passport_country,
                    "destination_country": destination_country,
                }
            )
        except Exception as exc:
            log.error("llm_failed", error=str(exc))
            report = VisaReport(
                passport_country=passport_country,
                destination_country=destination_country,
                visa_required=True,
                confidence="low",
                sources=sources,
                last_verified_at=datetime.now(tz=UTC),
            )

        log.info(
            "agent_done",
            visa_required=report.visa_required,
            confidence=report.confidence,
            sources=len(report.sources),
        )
        return {"visa_report": report}
