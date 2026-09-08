"""FastAPI trip planning router -- Phase 3 endpoints.

POST /api/trip/plan                 -- SSE stream, runs full LangGraph
POST /api/trip/{session_id}/clarify -- resume a paused graph after clarification
GET  /api/trip/{session_id}         -- full itinerary JSON (from DB)
PUT  /api/trip/{id}/itinerary       -- persist drag-drop reorder
GET  /api/trip/{id}/usage           -- token + cost breakdown
GET  /api/trip/public/{slug}        -- public shareable itinerary
POST /api/trip/{id}/pdf             -- WeasyPrint PDF
POST /api/trip/{id}/feedback        -- Langfuse user score

SSE event types:
  agent_start | agent_done | needs_clarification | complete | usage_summary | error
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.graph.graph import get_compiled_graph
from app.graph.state import initial_state

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/trip", tags=["trip"])


# ── Request / Response models ────────────────────────────────────────────────


class PlanRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    session_id: str | None = None


class ItineraryUpdateRequest(BaseModel):
    segments: list[dict[str, Any]] = Field(default_factory=list)


class ClarifyRequest(BaseModel):
    """Structured answers to the clarification prompts.

    Keys correspond to the ``field`` values from the ``needs_clarification`` SSE event.
    Example: ``{"question": "answer"}``
    """

    answers: dict[str, str]


class FeedbackRequest(BaseModel):
    rating: int = Field(description="1 = positive, -1 = negative")
    comment: str | None = None


# ── SSE helpers ───────────────────────────────────────────────────────────────


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _preview(agent_name: str, output: dict[str, Any]) -> str:
    try:
        m: dict[str, Any] = {
            "orchestrator": lambda o: f"{o.get('source', '')} → {o.get('destination', '')}",
            "safety": lambda o: (
                f"{len(getattr(o.get('safety_report'), 'top_scams', []))} scams found"
            ),
            "visa": lambda o: (
                f"Visa required: {getattr(o.get('visa_report'), 'visa_required', 'N/A')}"
            ),
            "transport_search": lambda o: f"{len(o.get('transport_legs_raw', {}))} route legs",
            "stay_search": lambda o: f"{len(o.get('stays_raw', []))} hotels",
            "local_experiences": lambda o: f"{len(o.get('experiences_raw', []))} experiences",
            "stay_analyst": lambda o: f"{len(o.get('stays_shortlist', []))} shortlisted hotels",
            "transport_optimizer": lambda o: (
                getattr(o.get("transport_recommendation"), "rationale", "")[:80] or "Done"
            ),
            "budget_planner": lambda o: (
                f"{getattr(o.get('budget_report'), 'total_estimated_cost', '?')} "
                f"({getattr(o.get('budget_report'), 'vs_budget_verdict', '?')})"
            ),
            "itinerary_compiler": lambda o: getattr(o.get("itinerary"), "title", "Done"),
        }
        fn = m.get(agent_name)
        return fn(output) if fn else "Done"
    except Exception:
        return "Done"


_AGENT_LAYERS: dict[str, int] = {
    "orchestrator": 0,
    "safety": 4,
    "visa": 1,
    "transport_search": 2,
    "stay_search": 2,
    "local_experiences": 2,
    "transport_optimizer": 3,
    "stay_analyst": 3,
    "self_drive_search": 3,
    "reviews": 4,
    "food_discovery": 4,
    "budget_planner": 4,
    "itinerary_compiler": 5,
}


async def _stream_graph(
    query: str,
    session_id: str,
    trip_id: str,
) -> AsyncGenerator[str, None]:
    from app.llm import reset_active_llm_session_id, set_active_llm_session_id
    from app.observability.langfuse import get_langfuse_handler

    llm_session_token = set_active_llm_session_id(session_id)

    try:
        yield _sse("agent_start", {"agent": "orchestrator", "session_id": session_id})

        compiled = await get_compiled_graph()
        state = initial_state(query=query, session_id=session_id)

        # Persist a stub row immediately so session_id is stored even if the
        # graph pauses for clarification or fails before completion.
        await _persist_trip(
            session_id=session_id,
            trip_id=trip_id,
            query=query,
            state=state,
            itinerary=None,
        )

        langfuse_handler = get_langfuse_handler(session_id=session_id)
        config: dict[str, Any] = {"configurable": {"thread_id": session_id}}
        if langfuse_handler:
            config["callbacks"] = [langfuse_handler]

        async for chunk in compiled.astream(state, stream_mode="updates", config=config):
            # Detect interrupt() from OrchestratorAgent — graph is paused
            if "__interrupt__" in chunk:
                interrupt_val = chunk["__interrupt__"][0]
                payload = interrupt_val.value if hasattr(interrupt_val, "value") else interrupt_val
                yield _sse(
                    "needs_clarification",
                    {
                        "session_id": session_id,
                        "prompts": payload.get("prompts", []),
                        "round": payload.get("round", 0),
                    },
                )
                return  # stream closes; client POSTs to /{session_id}/clarify

            for node_name, node_output in chunk.items():
                yield _sse(
                    "agent_done",
                    {
                        "agent": node_name,
                        "layer": _AGENT_LAYERS.get(node_name, -1),
                        "session_id": session_id,
                        "preview": _preview(node_name, node_output),
                    },
                )

        # Graph completed — get final state from checkpoint
        snapshot = await compiled.aget_state(config)
        final_state: dict[str, Any] = snapshot.values if snapshot else {}

        async for event in _emit_completion_events(
            final_state=final_state,
            session_id=session_id,
            trip_id=trip_id,
            query=query,
            compiled=compiled,
            config=config,
        ):
            yield event

    except Exception as exc:
        logger.exception("stream_graph_error", session_id=session_id, error=str(exc))
        yield _sse("error", {"message": str(exc), "session_id": session_id})
    finally:
        reset_active_llm_session_id(llm_session_token)


async def _stream_resumed_graph(
    session_id: str,
    trip_id: str,
    answers: dict[str, str],
    query: str,
) -> AsyncGenerator[str, None]:
    """Resume a paused graph after the user answers clarification prompts."""
    from app.llm import reset_active_llm_session_id, set_active_llm_session_id
    from app.observability.langfuse import get_langfuse_handler

    llm_session_token = set_active_llm_session_id(session_id)

    try:
        compiled = await get_compiled_graph()

        langfuse_handler = get_langfuse_handler(session_id=session_id)
        config: dict[str, Any] = {"configurable": {"thread_id": session_id}}
        if langfuse_handler:
            config["callbacks"] = [langfuse_handler]

        async for chunk in compiled.astream(
            Command(resume=answers), stream_mode="updates", config=config
        ):
            if "__interrupt__" in chunk:
                # Another round of clarification needed
                interrupt_val = chunk["__interrupt__"][0]
                payload = interrupt_val.value if hasattr(interrupt_val, "value") else interrupt_val
                yield _sse(
                    "needs_clarification",
                    {
                        "session_id": session_id,
                        "prompts": payload.get("prompts", []),
                        "round": payload.get("round", 0),
                    },
                )
                return

            for node_name, node_output in chunk.items():
                yield _sse(
                    "agent_done",
                    {
                        "agent": node_name,
                        "layer": _AGENT_LAYERS.get(node_name, -1),
                        "session_id": session_id,
                        "preview": _preview(node_name, node_output),
                    },
                )

        snapshot = await compiled.aget_state(config)
        final_state: dict[str, Any] = snapshot.values if snapshot else {}

        async for event in _emit_completion_events(
            final_state=final_state,
            session_id=session_id,
            trip_id=trip_id,
            query=query,
            compiled=compiled,
            config=config,
        ):
            yield event

    except Exception as exc:
        logger.exception("stream_resumed_error", session_id=session_id, error=str(exc))
        yield _sse("error", {"message": str(exc), "session_id": session_id})
    finally:
        reset_active_llm_session_id(llm_session_token)


async def _emit_completion_events(
    final_state: dict[str, Any],
    session_id: str,
    trip_id: str,
    query: str,
    compiled: Any,
    config: dict[str, Any],
) -> AsyncGenerator[str, None]:
    """Emit ``complete`` and ``usage_summary`` SSE events after the graph finishes."""
    itinerary = final_state.get("itinerary")
    if itinerary and hasattr(itinerary, "model_copy"):
        itinerary = itinerary.model_copy(update={"id": trip_id})

    usage_summary = await _build_usage_summary(final_state=final_state, session_id=session_id)

    await _persist_trip(
        session_id=session_id,
        trip_id=trip_id,
        query=query,
        state=final_state,
        itinerary=itinerary,
        usage_summary=usage_summary,
    )

    yield _sse(
        "complete",
        {
            "itinerary_id": trip_id,
            "session_id": session_id,
            "itinerary": itinerary.model_dump() if itinerary else None,
        },
    )
    yield _sse(
        "usage_summary",
        {
            "session_id": session_id,
            "total_tokens": usage_summary["total_tokens"],
            "total_cost_usd": usage_summary["total_cost_usd"],
            "headroom": {
                "total_tokens_saved": usage_summary["headroom_tokens_saved"],
                "avg_compression_ratio": usage_summary["headroom_avg_compression_ratio"],
            },
            "per_agent": usage_summary["per_agent"],
        },
    )


async def _build_usage_summary(final_state: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Build usage summary from Redis usage cache; fallback to graph state when absent."""
    per_agent: dict[str, dict[str, Any]] = {}
    total_tokens = 0
    total_cost_usd = 0.0
    headroom_tokens_saved = 0
    headroom_ratio_sum = 0.0
    headroom_ratio_count = 0

    # Preferred source: live per-agent cache written by UsageLogger callbacks.
    try:
        from app.services.cache_service import CacheService

        cache = CacheService()
        for attempt in range(4):
            per_agent = {}
            total_tokens = 0
            total_cost_usd = 0.0
            headroom_tokens_saved = 0
            headroom_ratio_sum = 0.0
            headroom_ratio_count = 0

            for agent in _AGENT_LAYERS:
                row = await cache.get(CacheService.usage_key(session_id, agent))
                if not row:
                    continue

                prompt_tokens = int(row.get("prompt_tokens", 0) or 0)
                completion_tokens = int(row.get("completion_tokens", 0) or 0)
                agent_total = int(row.get("total_tokens", prompt_tokens + completion_tokens) or 0)
                cost_usd = float(row.get("cost_usd", 0.0) or 0.0)
                hr_saved = int(row.get("headroom_tokens_saved", 0) or 0)
                hr_applied = int(row.get("headroom_applied_calls", 0) or 0)
                hr_calls = int(row.get("headroom_calls", 0) or 0)
                hr_ratio_sum = float(row.get("headroom_ratio_sum", 0.0) or 0.0)
                hr_ratio_count = int(row.get("headroom_ratio_count", 0) or 0)
                hr_avg = (hr_ratio_sum / hr_ratio_count) if hr_ratio_count > 0 else None

                per_agent[agent] = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": agent_total,
                    "cost_usd": cost_usd,
                    "headroom": {
                        "calls": hr_calls,
                        "applied_calls": hr_applied,
                        "tokens_saved": hr_saved,
                        "avg_compression_ratio": hr_avg,
                    },
                }
                total_tokens += agent_total
                total_cost_usd += cost_usd
                headroom_tokens_saved += hr_saved
                headroom_ratio_sum += hr_ratio_sum
                headroom_ratio_count += hr_ratio_count

            if per_agent or attempt == 3:
                break
            await asyncio.sleep(0.1)
    except Exception as exc:
        logger.warning("usage_cache_read_failed", session_id=session_id, error=str(exc))

    # Fallback source: token_usage reducer in graph state.
    if not per_agent:
        token_usage = final_state.get("token_usage", {}) or {}
        for name, usage in token_usage.items():
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            agent_total = int(
                getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0
            )
            cost_usd = float(getattr(usage, "cost_usd", 0.0) or 0.0)
            per_agent[name] = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": agent_total,
                "cost_usd": cost_usd,
                "headroom": {
                    "calls": 0,
                    "applied_calls": 0,
                    "tokens_saved": 0,
                    "avg_compression_ratio": None,
                },
            }
            total_tokens += agent_total
            total_cost_usd += cost_usd

    return {
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost_usd,
        "headroom_tokens_saved": headroom_tokens_saved,
        "headroom_avg_compression_ratio": (
            headroom_ratio_sum / headroom_ratio_count if headroom_ratio_count > 0 else None
        ),
        "per_agent": per_agent,
    }


async def _persist_trip(
    session_id: str,
    trip_id: str,
    query: str,
    state: dict[str, Any],
    itinerary: Any,
    usage_summary: dict[str, Any] | None = None,
) -> None:
    """Persist the completed trip to the database.  Best-effort — never blocks SSE."""
    try:
        from sqlalchemy import text

        from app.db import AsyncSessionLocal

        itinerary_json = itinerary.model_dump_json() if itinerary else None
        is_intl = state.get("is_international", False)
        reality_score = None
        ctx = state.get("safety_report")
        if ctx and hasattr(ctx, "crowd_level"):
            # Map crowd level to a simple score for indexing
            reality_score = {"Low": 85, "Moderate": 65, "High": 45, "Extreme": 20}.get(
                ctx.crowd_level, 50
            )

        # Serialise per-agent token/headroom usage so GET /{id}/usage can read it back
        if usage_summary and usage_summary.get("per_agent"):
            token_usage_json = json.dumps(usage_summary, default=str)
        else:
            token_usage = state.get("token_usage", {}) or {}
            token_usage_json = json.dumps(
                {
                    name: (u.model_dump() if hasattr(u, "model_dump") else u)
                    for name, u in token_usage.items()
                },
                default=str,
            )

        async with AsyncSessionLocal() as session:
            await session.execute(
                text("""
                    INSERT INTO trips
                        (id, session_id, query, is_international, itinerary_json,
                         reality_score, token_usage_json)
                    VALUES
                        (:id, :session_id, :query, :is_international,
                         CAST(:itinerary AS jsonb), :reality_score,
                         CAST(:token_usage AS jsonb))
                    ON CONFLICT (id) DO UPDATE
                    SET itinerary_json = CAST(EXCLUDED.itinerary_json AS jsonb),
                        token_usage_json = CAST(EXCLUDED.token_usage_json AS jsonb),
                        updated_at = NOW()
                """),
                {
                    "id": trip_id,
                    "session_id": session_id,
                    "query": query[:2000],
                    "is_international": is_intl,
                    "itinerary": itinerary_json,
                    "reality_score": reality_score,
                    "token_usage": token_usage_json,
                },
            )
            await session.commit()
    except Exception as exc:
        logger.warning("trip_persist_failed", error=str(exc), session_id=session_id)


async def _get_latest_trip_id(session_id: str) -> str | None:
    """Return the most recent trip id for a session, or None if absent."""
    try:
        from sqlalchemy import text

        from app.db import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            row = await db.execute(
                text(
                    "SELECT id FROM trips WHERE session_id = :sid ORDER BY created_at DESC LIMIT 1"
                ),
                {"sid": session_id},
            )
            result = row.fetchone()
            return str(result.id) if result else None
    except Exception as exc:
        logger.warning("get_latest_trip_id_failed", error=str(exc), session_id=session_id)
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/plan")
async def plan_trip(request: PlanRequest) -> StreamingResponse:
    """Start a planning session and stream SSE events."""
    session_id = request.session_id or str(uuid.uuid4())
    trip_id = str(uuid.uuid4())

    logger.info("plan_trip_start", session_id=session_id, query=request.query[:80])

    return StreamingResponse(
        _stream_graph(
            query=request.query,
            session_id=session_id,
            trip_id=trip_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{session_id}/clarify")
async def clarify_trip(session_id: str, request: ClarifyRequest) -> StreamingResponse:
    """Resume a paused planning graph with the user's clarification answers.

    Called after a ``needs_clarification`` SSE event.  The ``answers`` dict
    should map each prompted ``question`` to the user's response string, e.g.::

        {"question": "answer"}
    """
    logger.info(
        "clarify_trip_resume",
        session_id=session_id,
        questions=list(request.answers.keys()),
    )

    # Retrieve the original query from the checkpoint so _persist_trip can record it
    try:
        compiled = await get_compiled_graph()
        config = {"configurable": {"thread_id": session_id}}
        snapshot = await compiled.aget_state(config)
        query = (snapshot.values or {}).get("query", "") if snapshot else ""
    except Exception:
        query = ""

    # Continue updating the same trip row started in /plan.
    trip_id = await _get_latest_trip_id(session_id) or str(uuid.uuid4())

    return StreamingResponse(
        _stream_resumed_graph(
            session_id=session_id,
            trip_id=trip_id,
            answers=request.answers,
            query=query,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{session_id}")
async def get_itinerary(session_id: str) -> dict[str, Any]:
    """Return the latest itinerary for a session from the database."""
    try:
        from sqlalchemy import text

        from app.db import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            row = await db.execute(
                text(
                    "SELECT id, itinerary_json, created_at "
                    "FROM trips WHERE session_id = :sid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"sid": session_id},
            )
            result = row.fetchone()
            if not result:
                raise HTTPException(status_code=404, detail="No itinerary found for this session")
            return {
                "id": str(result.id),
                "itinerary": result.itinerary_json,
                "created_at": str(result.created_at),
            }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("get_itinerary_db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.put("/{trip_id}/itinerary")
async def update_itinerary(trip_id: str, payload: ItineraryUpdateRequest) -> dict[str, Any]:
    """Persist drag-drop segment reorders from the frontend."""
    try:
        import json as _json

        from sqlalchemy import text

        from app.db import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "UPDATE trips"
                    " SET itinerary_json = itinerary_json || :patch, updated_at = NOW()"
                    " WHERE id = :id"
                ),
                {"id": trip_id, "patch": _json.dumps({"segments": payload.segments})},
            )
            await db.commit()
    except Exception as exc:
        logger.warning("update_itinerary_db_error", error=str(exc))
    return {"status": "ok", "trip_id": trip_id}


@router.get("/{trip_id}/usage")
async def get_usage(trip_id: str) -> dict[str, Any]:
    """Return per-agent token and cost breakdown from the database."""
    try:
        from sqlalchemy import text

        from app.db import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            row = await db.execute(
                text("SELECT token_usage_json FROM trips WHERE id = :id"),
                {"id": trip_id},
            )
            result = row.fetchone()
            if not result:
                raise HTTPException(status_code=404, detail="Trip not found")
            return {"trip_id": trip_id, "usage": result.token_usage_json or {}}
    except HTTPException:
        raise
    except Exception:
        return {"trip_id": trip_id, "message": "Usage data unavailable — check Langfuse dashboard"}


@router.get("/public/{slug}")
async def get_public_itinerary(slug: str) -> dict[str, Any]:
    """Return a public shared itinerary by slug."""
    try:
        from sqlalchemy import text

        from app.db import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            row = await db.execute(
                text("SELECT id, itinerary_json FROM trips WHERE slug = :slug AND public = TRUE"),
                {"slug": slug},
            )
            result = row.fetchone()
            if not result:
                raise HTTPException(status_code=404, detail="Public itinerary not found")
            return {"id": str(result.id), "itinerary": result.itinerary_json}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.post("/{trip_id}/pdf")
async def generate_pdf(trip_id: str) -> Response:
    """Generate a PDF of the itinerary using WeasyPrint."""
    # Fetch itinerary
    try:
        from sqlalchemy import text

        from app.db import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            row = await db.execute(
                text("SELECT itinerary_json FROM trips WHERE id = :id"),
                {"id": trip_id},
            )
            result = row.fetchone()
            if not result or not result.itinerary_json:
                raise HTTPException(status_code=404, detail="Itinerary not found")
            itinerary_data = result.itinerary_json
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("pdf_db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    # Render PDF
    try:
        from app.services.pdf_service import render_pdf

        pdf_bytes = await render_pdf(itinerary_data)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="itinerary-{trip_id[:8]}.pdf"'},
        )
    except Exception as exc:
        logger.error("pdf_render_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}") from exc


@router.post("/{trip_id}/feedback")
async def submit_feedback(trip_id: str, payload: FeedbackRequest) -> dict[str, Any]:
    """Record user feedback score in Langfuse and DB."""
    from app.observability.langfuse import score_trip

    await score_trip(
        trip_id=trip_id,
        session_id="",
        rating=payload.rating,
        comment=payload.comment or "",
    )
    logger.info("feedback_recorded", trip_id=trip_id, rating=payload.rating)
    return {"status": "ok", "trip_id": trip_id}
