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

from app.agents.base import AgentClarificationMixin
from app.agents.structured_output import StructuredOutputError, invoke_structured
from app.llm import get_llm
from app.logging import get_agent_logger
from app.models.enums import AgentName, LogEvent, Sentiment
from app.models.reports import ReviewSummary
from app.services.cache_service import TTL_PLACES, cache_service
from app.tools.factory import ToolFactory

# Keep review synthesis bounded so one slow provider call cannot stall the full graph.
_REVIEW_SUMMARY_TIMEOUT_SECONDS = 60

# Sentiments the model may choose from; UNKNOWN is reserved for "no evidence".
_JUDGEABLE_SENTIMENTS = (Sentiment.POSITIVE, Sentiment.MIXED, Sentiment.NEGATIVE)

_SYSTEM_PROMPT = f"""\
You are a travel reviewer. Given the raw place details and reviews below, synthesise a
concise reviewer summary for a traveller.

Rules:
- ``pros`` should list 2–4 concrete positives mentioned by multiple reviewers.
- ``cons`` should list 1–3 genuine negatives (skip if the place has near-perfect reviews).
- ``sentiment`` must be one of: {" | ".join(_JUDGEABLE_SENTIMENTS)}.
- Keep each pro/con to a single short sentence.
"""


class _PlaceSummary(BaseModel):
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    sentiment: Sentiment = Sentiment.UNKNOWN


# Returned whenever no review text reached the model, so downstream consumers can
# tell "no evidence" apart from "reviewers were positive".
_NO_EVIDENCE_SUMMARY = _PlaceSummary(pros=[], cons=[], sentiment=Sentiment.UNKNOWN)


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


def _photo_urls(value: object) -> list[str]:
    """Keep only renderable http(s) URLs; drop Google Places photo resource dicts."""
    if not isinstance(value, list):
        return []
    return [
        item.strip() for item in value if isinstance(item, str) and item.strip().startswith("http")
    ]


def _review_key(route_version: int, target: _ReviewTarget) -> str:
    """``{route_version}:{stop_id}:{place_id}`` — see Core concepts, downstream contracts."""
    place_key = target.place_id or _fallback_place_key(target.name, target.lat, target.lng)
    return f"{route_version}:{target.stop_id or 'unknown'}:{place_key}"


class ReviewsAgent(AgentClarificationMixin):
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
            LogEvent.AGENT_START,
            targets=len(targets),
            mode="multi_stop_provisional" if multi_stop else "single_destination",
        )
        if not targets:
            return {"reviews_summary": {}}

        # Two targets can be the same physical place (e.g. a landmark revisited on a
        # later stop) — fetch/summarise each unique place once and reuse the result
        # for every occurrence instead of duplicating the place_details + LLM calls.
        physical_keys = {
            id(target): target.place_id or _fallback_place_key(target.name, target.lat, target.lng)
            for target in targets
        }
        place_tasks: dict[str, asyncio.Task[Any]] = {}
        for target in targets:
            physical_key = physical_keys[id(target)]
            if physical_key not in place_tasks:
                place_tasks[physical_key] = asyncio.create_task(
                    self._fetch_and_summarise_place(target, log)
                )

        results = await asyncio.gather(
            *[
                self._build_review_summary(
                    target,
                    place_tasks[physical_keys[id(target)]],
                    route_version if multi_stop else None,
                )
                for target in targets
            ],
            return_exceptions=True,
        )

        reviews_summary: dict[str, ReviewSummary] = {}
        for r in results:
            if isinstance(r, BaseException):
                log.warning(LogEvent.TOOL_CALL_FAILED, tool="place_details", error=str(r))
                continue
            key, summary = r
            reviews_summary[key] = summary

        evidenced = sum(1 for s in reviews_summary.values() if s.sentiment != Sentiment.UNKNOWN)
        log.info(
            LogEvent.AGENT_DONE,
            reviewed=len(reviews_summary),
            evidenced=evidenced,
            without_evidence=len(reviews_summary) - evidenced,
        )
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

    async def _fetch_and_summarise_place(
        self, target: _ReviewTarget, log: Any
    ) -> tuple[dict[str, Any], _PlaceSummary]:
        """Network + LLM work for one physical place, independent of how many stops visit it."""
        physical_key = target.place_id or _fallback_place_key(target.name, target.lat, target.lng)
        details = await cache_service.get_or_set(
            cache_service.place_key(physical_key),
            TTL_PLACES,
            lambda: self._place_details.run(place_id=target.place_id, name=target.name),
        )
        reviews_text = "\n".join(
            f"- {r.get('author', 'Guest')} ({r.get('rating', '?')}★): {r.get('text', '')}"
            for r in details.get("reviews", [])[:5]
        )
        if not reviews_text:
            log.info(
                LogEvent.SECTION_UNAVAILABLE,
                section="reviews",
                place=target.name,
                place_id=target.place_id or None,
                reason="no_review_text_from_provider",
            )
            return details, _NO_EVIDENCE_SUMMARY

        try:
            summary: _PlaceSummary = await asyncio.wait_for(
                invoke_structured(
                    self._llm,
                    _PlaceSummary,
                    [
                        SystemMessage(content=_SYSTEM_PROMPT),
                        HumanMessage(
                            content=(
                                f"Place: {target.name}\n"
                                f"Rating: {details.get('rating')}/5"
                                f" ({details.get('review_count')} reviews)\n\n"
                                f"Reviews:\n{reviews_text}"
                            )
                        ),
                    ],
                    agent=AgentName.REVIEWS,
                    log=log,
                ),
                timeout=_REVIEW_SUMMARY_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            log.warning(
                LogEvent.AGENT_DEGRADED,
                reason="llm_timeout",
                place=target.name,
                timeout_seconds=_REVIEW_SUMMARY_TIMEOUT_SECONDS,
            )
            summary = _NO_EVIDENCE_SUMMARY
        except StructuredOutputError as exc:
            log.warning(LogEvent.AGENT_DEGRADED, reason=str(exc), place=target.name)
            summary = _NO_EVIDENCE_SUMMARY
        return details, summary

    async def _build_review_summary(
        self,
        target: _ReviewTarget,
        place_task: asyncio.Task[Any],
        route_version: int | None,
    ) -> tuple[str, ReviewSummary]:
        """Assemble this target's (per-stop) keyed summary from the shared place fetch."""
        details, summary = await place_task
        photos = _photo_urls(details.get("photos", []))
        key = _review_key(route_version, target) if route_version is not None else target.name
        stop_id = target.stop_id if route_version is not None else None
        return key, ReviewSummary(
            place_name=target.name,
            rating=details.get("rating"),
            review_count=details.get("review_count"),
            pros=summary.pros,
            cons=summary.cons,
            sentiment=summary.sentiment,
            photos=photos,
            google_maps_url=details.get("google_maps_url"),
            stop_id=stop_id,
            place_id=target.place_id or details.get("place_id") or None,
            review_key=key if route_version is not None else None,
            route_version=route_version,
        )
