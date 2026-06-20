"""VisaAgent — Layer 1: visa requirements + embassy + application centre.

Only activates for international trips (``state["is_international"] == True``).

Grounding rules (G):
  - ``sources[]`` is populated from Tavily result URLs.
  - Grounding URLs are classified: official if domain ends with ``.gov``,
    ``.gov.in``, ``.mfa.*``, ``.embassy.*``, ``.vfsglobal.com``, etc.
  - ``confidence`` = "high" if ≥1 official-domain source; "medium" if ≥1
    non-official source; "low" if no sources at all.
  - ``visa_required`` is never asserted without at least one source.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import get_llm
from app.models.reports import VisaReport, VisaSource
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)

# ── Official-domain classifier ────────────────────────────────────────────────
_OFFICIAL_DOMAIN_PATTERNS = re.compile(
    r"(\.gov(\.[a-z]{2})?$|\.mfa\.[a-z]+$|embassy\.|consulate\.|"
    r"vfsglobal\.com|blsinternational\.com|tlscontact\.com|"
    r"idata\.com\.tr|mofa\.|moi\.|immigration\.)",
    re.IGNORECASE,
)


def _classify_sources(urls: list[dict[str, Any]]) -> tuple[list[VisaSource], str]:
    """Return (sources_list, confidence_level) based on domain classification."""
    sources: list[VisaSource] = []
    has_official = False

    for item in urls:
        url = item.get("url", "")
        title = item.get("title", "")
        pub_date = item.get("published_date")
        sources.append(VisaSource(title=title, url=url, published_or_fetched_date=pub_date))
        # Extract domain from URL
        domain_match = re.search(r"https?://([^/]+)", url)
        if domain_match:
            domain = domain_match.group(1)
            if _OFFICIAL_DOMAIN_PATTERNS.search(domain):
                has_official = True

    if not sources:
        confidence = "low"
    elif has_official:
        confidence = "high"
    else:
        confidence = "medium"

    return sources, confidence


_SYSTEM_PROMPT = """\
You are an expert visa and immigration adviser. Based on the search results below,
produce a complete visa report.

Critical rules:
- Do NOT assume VFS Global handles all applications — identify the correct company
  from the search results (BLS International, TLScontact, iData, ACSIS, etc.).
- ``visa_type`` must be one of: tourist | e-visa | on_arrival | visa_free | null.
- ``application_process`` must be a numbered ordered list of concrete steps.
- Include ``disclaimer`` reminding travellers to verify with the official consulate.
- If search results are insufficient, lean conservative: flag uncertainty in
  ``validity_notes``.
"""


class VisaAgent:
    """Layer 1 — Visa requirements, embassy, and application centre details."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: object | None = None,
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
        passport_country = (user_profile and user_profile.passport_country) or "India"
        home_city = (user_profile and user_profile.home_city) or "Mumbai"
        destination_country = destination

        log = logger.bind(agent="visa", destination=destination, session_id=session_id)
        log.info("agent_start", passport=passport_country)

        import asyncio

        tavily_task = self._tavily.run(
            query=(
                f"{passport_country} passport visa requirements {destination} 2026 "
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

        tavily_result, centre_result, embassy_result = await asyncio.gather(
            tavily_task, centre_task, embassy_task, return_exceptions=True
        )

        # ── Grounding (G) ────────────────────────────────────────────────
        raw_results: list[dict[str, Any]] = []
        if not isinstance(tavily_result, Exception):
            raw_results = tavily_result.get("results", [])

        sources, confidence = _classify_sources(raw_results)

        # Fixture / tool sources (visa_centre tool returns its own sources)
        if not isinstance(centre_result, Exception):
            for src in centre_result.get("sources", []):
                if isinstance(src, dict) and src.get("url"):
                    sources.append(
                        VisaSource(
                            title=src.get("title", "Visa centre source"),
                            url=src["url"],
                            published_or_fetched_date=centre_result.get("last_verified_at"),
                        )
                    )
                    # Visa centre tool sources are official
                    confidence = max(
                        confidence,
                        "medium",
                        key=lambda c: {"low": 0, "medium": 1, "high": 2}[c],
                    )

        # Build LLM context
        snippets: list[str] = []
        if not isinstance(tavily_result, Exception):
            if tavily_result.get("answer"):
                snippets.append(f"Summary: {tavily_result['answer']}")
            for item in raw_results[:5]:
                snippets.append(f"• {item.get('title', '')}: {item.get('content', '')[:400]}")
        if not isinstance(centre_result, Exception) and centre_result.get("application_centre"):
            c = centre_result["application_centre"]
            snippets.append(
                f"Application centre: {c.get('name', '')} — {c.get('address', '')} "
                f"| Booking: {c.get('booking_url', 'N/A')}"
            )
        if not isinstance(embassy_result, Exception) and embassy_result.get("embassy"):
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

        chain = self._llm.with_structured_output(VisaReport)  # type: ignore[union-attr]
        try:
            report: VisaReport = chain.invoke(
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
                    "confidence": confidence,
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
