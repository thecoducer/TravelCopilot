"""ReviewsAgent — Layer 4: Google Places reviews + photos for stays and experiences.

Fetches place details for the chosen hotel and top experiences, then uses LLM
to synthesise concise pros/cons per place.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm import get_llm
from app.models.reports import ReviewSummary
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a travel reviewer. Given the raw place details and reviews below, synthesise a
concise reviewer summary for a traveller.

Rules:
- ``pros`` should list 2–4 concrete positives mentioned by multiple reviewers.
- ``cons`` should list 1–3 genuine negatives (skip if the place has near-perfect reviews).
- ``sentiment`` must be one of: "positive" | "mixed" | "negative".
- Keep each pro/con to a single short sentence.
"""


class _PlaceSummary(BaseModel):
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    sentiment: str = "positive"


class ReviewsAgent:
    """Layer 4 — Reviews and photos for selected accommodation and experiences."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: object | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._place_details = factory.get("place_details")
        self._llm = llm or get_llm("reviews")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        stays_shortlist: list[Any] = state.get("stays_shortlist", [])
        experiences_raw = state.get("experiences_raw", [])
        session_id: str = state.get("session_id", "")

        log = logger.bind(agent="reviews", session_id=session_id)
        log.info(
            "agent_start",
            hotels=len(stays_shortlist),
            experiences=len(experiences_raw),
        )

        # Fetch for ALL shortlisted hotels + top 8 experiences by rating
        targets: list[tuple[str, str]] = []  # (name, place_id)
        for stay in stays_shortlist:
            targets.append((stay.name, ""))
        for exp in sorted(
            experiences_raw, key=lambda e: e.rating or 0, reverse=True
        )[:8]:
            targets.append((exp.name, ""))

        if not targets:
            return {"reviews_summary": {}}

        async def _fetch_and_summarise(name: str, place_id: str) -> tuple[str, ReviewSummary]:
            details = await self._place_details.run(place_id=place_id, name=name)

            reviews_text = "\n".join(
                f"- {r.get('author', 'Guest')} ({r.get('rating', '?')}★): {r.get('text', '')}"
                for r in details.get("reviews", [])[:5]
            )
            photos = details.get("photos", [])
            maps_url = details.get("google_maps_url")
            rating = details.get("rating")
            review_count = details.get("review_count")

            if not reviews_text:
                return name, ReviewSummary(
                    place_name=name,
                    rating=rating,
                    review_count=review_count,
                    photos=photos,
                    google_maps_url=maps_url,
                    sentiment="positive",
                )

            chain = self._llm.with_structured_output(_PlaceSummary)  # type: ignore[union-attr]
            try:
                summary: _PlaceSummary = chain.invoke(
                    [
                        SystemMessage(content=_SYSTEM_PROMPT),
                        HumanMessage(
                            content=(
                                f"Place: {name}\n"
                                f"Rating: {rating}/5 ({review_count} reviews)\n\n"
                                f"Reviews:\n{reviews_text}"
                            )
                        ),
                    ]
                )
            except Exception as exc:
                log.warning("llm_failed", place=name, error=str(exc))
                summary = _PlaceSummary(pros=[], cons=[], sentiment="positive")

            return name, ReviewSummary(
                place_name=name,
                rating=rating,
                review_count=review_count,
                pros=summary.pros,
                cons=summary.cons,
                sentiment=summary.sentiment,
                photos=photos,
                google_maps_url=maps_url,
            )

        results = await asyncio.gather(
            *[_fetch_and_summarise(name, pid) for name, pid in targets],
            return_exceptions=True,
        )

        reviews_summary: dict[str, ReviewSummary] = {}
        for r in results:
            if isinstance(r, Exception):
                log.warning("review_fetch_failed", error=str(r))
                continue
            name, summary = r
            reviews_summary[name] = summary

        log.info("agent_done", reviewed=len(reviews_summary))
        return {"reviews_summary": reviews_summary}
