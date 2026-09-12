"""ReviewsAgent — Layer 4: Google Places reviews + photos for stays and experiences.

Fetches place details for the chosen hotel and top experiences, then uses LLM
to synthesise concise pros/cons per place.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, NamedTuple

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm import get_llm
from app.logging import get_agent_logger
from app.models.reports import ReviewSummary
from app.tools.factory import ToolFactory

# Keep review synthesis bounded so one slow provider call cannot stall the full graph.
_REVIEW_SUMMARY_TIMEOUT_SECONDS = 60

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


class _ReviewTarget(NamedTuple):
    name: str
    place_id: str = ""
    stop_id: str | None = None
    lat: float | None = None
    lng: float | None = None


def _fallback_place_key(name: str, lat: float | None, lng: float | None) -> str:
    """Deterministic place identifier when no provider ``place_id`` is available."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "place"
    if lat is not None and lng is not None:
        return f"{slug}:{lat:.4f}:{lng:.4f}"
    return slug


def _review_key(route_version: int, target: _ReviewTarget) -> str:
    """``{route_version}:{stop_id}:{place_id}`` — see Core concepts, downstream contracts."""
    place_key = target.place_id or _fallback_place_key(target.name, target.lat, target.lng)
    return f"{route_version}:{target.stop_id or 'unknown'}:{place_key}"


class ReviewsAgent:
    """Layer 4 — Reviews and photos for selected accommodation and experiences."""

    def __init__(
        self,
        tool_factory: ToolFactory | None = None,
        llm: Any | None = None,
    ) -> None:
        factory = tool_factory or ToolFactory()
        self._place_details = factory.get("place_details")
        self._llm = llm or get_llm("reviews")

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        stays_shortlist: list[Any] = state.get("stays_shortlist", [])
        experiences_raw = state.get("experiences_raw", [])
        stays_shortlist_by_stop: dict[str, list[Any]] = state.get("stays_shortlist_by_stop", {})
        experiences_raw_by_stop: dict[str, list[Any]] = state.get("experiences_raw_by_stop", {})
        session_id: str = state.get("session_id", "")
        route_version: int = state.get("route_version", 0)

        log = get_agent_logger("reviews", session_id)

        multi_stop = state.get("route_discovery_status") == "multi_stop_provisional" and (
            stays_shortlist_by_stop or experiences_raw_by_stop
        )
        targets = (
            self._multi_stop_targets(stays_shortlist_by_stop, experiences_raw_by_stop)
            if multi_stop
            else self._single_destination_targets(stays_shortlist, experiences_raw)
        )

        log.info(
            "agent_start",
            targets=len(targets),
            mode="multi_stop_provisional" if multi_stop else "single_destination",
        )
        if not targets:
            return {"reviews_summary": {}}

        results = await asyncio.gather(
            *[
                self._fetch_and_summarise(t, route_version if multi_stop else None, log)
                for t in targets
            ],
            return_exceptions=True,
        )

        reviews_summary: dict[str, ReviewSummary] = {}
        for r in results:
            if isinstance(r, BaseException):
                log.warning("review_fetch_failed", error=str(r))
                continue
            key, summary = r
            reviews_summary[key] = summary

        log.info("agent_done", reviewed=len(reviews_summary))
        return {"reviews_summary": reviews_summary}

    @staticmethod
    def _single_destination_targets(
        stays_shortlist: list[Any], experiences_raw: list[Any]
    ) -> list[_ReviewTarget]:
        targets = [_ReviewTarget(name=stay.name) for stay in stays_shortlist]
        targets += [
            _ReviewTarget(name=exp.name)
            for exp in sorted(experiences_raw, key=lambda e: e.rating or 0, reverse=True)[:8]
        ]
        return targets

    @staticmethod
    def _multi_stop_targets(
        stays_shortlist_by_stop: dict[str, list[Any]],
        experiences_raw_by_stop: dict[str, list[Any]],
    ) -> list[_ReviewTarget]:
        """Build review targets keyed by stop occurrence — never by name alone.

        Two occurrences of the same place (e.g. Dirang outbound and return)
        get independent targets and therefore independent review keys.
        """
        targets: list[_ReviewTarget] = []
        for stop_id, stays in stays_shortlist_by_stop.items():
            targets += [
                _ReviewTarget(name=stay.name, stop_id=stop_id, lat=stay.lat, lng=stay.lng)
                for stay in stays
            ]
        for stop_id, experiences in experiences_raw_by_stop.items():
            top_experiences = sorted(experiences, key=lambda e: e.rating or 0, reverse=True)[:8]
            targets += [
                _ReviewTarget(name=exp.name, stop_id=stop_id, lat=exp.lat, lng=exp.lng)
                for exp in top_experiences
            ]
        return targets

    async def _fetch_and_summarise(
        self, target: _ReviewTarget, route_version: int | None, log: Any
    ) -> tuple[str, ReviewSummary]:
        details = await self._place_details.run(place_id=target.place_id, name=target.name)

        reviews_text = "\n".join(
            f"- {r.get('author', 'Guest')} ({r.get('rating', '?')}★): {r.get('text', '')}"
            for r in details.get("reviews", [])[:5]
        )
        photos = details.get("photos", [])
        maps_url = details.get("google_maps_url")
        rating = details.get("rating")
        review_count = details.get("review_count")

        key = _review_key(route_version, target) if route_version is not None else target.name
        stop_id = target.stop_id if route_version is not None else None

        if not reviews_text:
            return key, ReviewSummary(
                place_name=target.name,
                rating=rating,
                review_count=review_count,
                photos=photos,
                google_maps_url=maps_url,
                sentiment="positive",
                stop_id=stop_id,
                review_key=key if route_version is not None else None,
                route_version=route_version,
            )

        chain = self._llm.with_structured_output(_PlaceSummary)
        try:
            summary: _PlaceSummary = await asyncio.wait_for(
                chain.ainvoke(
                    [
                        SystemMessage(content=_SYSTEM_PROMPT),
                        HumanMessage(
                            content=(
                                f"Place: {target.name}\n"
                                f"Rating: {rating}/5 ({review_count} reviews)\n\n"
                                f"Reviews:\n{reviews_text}"
                            )
                        ),
                    ]
                ),
                timeout=_REVIEW_SUMMARY_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            log.warning(
                "llm_timeout", place=target.name, timeout_seconds=_REVIEW_SUMMARY_TIMEOUT_SECONDS
            )
            summary = _PlaceSummary(pros=[], cons=[], sentiment="positive")
        except Exception as exc:
            log.warning("llm_failed", place=target.name, error=str(exc))
            summary = _PlaceSummary(pros=[], cons=[], sentiment="positive")

        return key, ReviewSummary(
            place_name=target.name,
            rating=rating,
            review_count=review_count,
            pros=summary.pros,
            cons=summary.cons,
            sentiment=summary.sentiment,
            photos=photos,
            google_maps_url=maps_url,
            stop_id=stop_id,
            review_key=key if route_version is not None else None,
            route_version=route_version,
        )
