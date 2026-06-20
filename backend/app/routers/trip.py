"""FastAPI trip planning router -- Phase 3 endpoints.

POST /api/trip/plan              -- SSE stream, runs full LangGraph
GET  /api/trip/{session_id}      -- full itinerary JSON (from DB)
PUT  /api/trip/{id}/itinerary    -- persist drag-drop reorder
GET  /api/trip/{id}/usage        -- token + cost breakdown
GET  /api/trip/public/{slug}     -- public shareable itinerary
POST /api/trip/{id}/pdf          -- WeasyPrint PDF
POST /api/trip/{id}/feedback     -- Langfuse user score

SSE event types:
  agent_start | agent_done | needs_clarification | complete | usage_summary | error
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.graph.graph import build_graph
from app.graph.state import initial_state

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/trip", tags=["trip"])


# ── Request / Response models ────────────────────────────────────────────────


class PlanRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    session_id: str | None = None
    source: str | None = None
    destination: str | None = None


class ItineraryUpdateRequest(BaseModel):
    segments: list[dict[str, Any]] = Field(default_factory=list)


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
            "destination_context": lambda o: getattr(o.get("destination_context_report"), "crowd_level", "Done"),
            "scam_safety": lambda o: f"{len(getattr(o.get('scam_safety_report'), 'top_scams', []))} scams found",
            "visa": lambda o: f"Visa required: {getattr(o.get('visa_report'), 'visa_required', 'N/A')}",
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
    "destination_context": 1, "scam_safety": 1, "visa": 1,
    "transport_search": 2, "stay_search": 2, "local_experiences": 2,
    "transport_optimizer": 3, "stay_analyst": 3, "self_drive_search": 3,
    "reviews": 4, "food_discovery": 4, "budget_planner": 4,
    "itinerary_compiler": 5,
}


async def _stream_graph(
    query: str,
    session_id: str,
    overrides: dict[str, Any],
) -> AsyncGenerator[str, None]:
    from app.observability.langfuse import get_langfuse_handler

    try:
        yield _sse("agent_start", {"agent": "orchestrator", "session_id": session_id})

        compiled = build_graph()
        state = initial_state(query=query, session_id=session_id)
        state.update(overrides)

        langfuse_handler = get_langfuse_handler(session_id=session_id)
        config: dict[str, Any] = {}
        if langfuse_handler:
            config["callbacks"] = [langfuse_handler]

        # Stream updates node-by-node
        node_outputs: dict[str, Any] = {}
        async for chunk in compiled.astream(state, stream_mode="updates", config=config):
            for node_name, node_output in chunk.items():
                node_outputs[node_name] = node_output

                # Clarification gate — emit special event and stop cleanly
                if node_name == "orchestrator" and node_output.get("needs_clarification"):
                    yield _sse(
                        "needs_clarification",
                        {
                            "session_id": session_id,
                            "prompts": [
                                {"field": p.field, "question": p.question}
                                for p in node_output.get("clarification_prompts", [])
                            ],
                        },
                    )
                    return  # No `complete` event — client re-POSTs with clarified query

                yield _sse(
                    "agent_done",
                    {
                        "agent": node_name,
                        "layer": _AGENT_LAYERS.get(node_name, -1),
                        "session_id": session_id,
                        "preview": _preview(node_name, node_output),
                    },
                )

        # Collect final state by re-invoking (streaming doesn't return final state directly)
        final_state = await compiled.ainvoke(state, config=config)

        itinerary = final_state.get("itinerary")
        itinerary_id = str(uuid.uuid4())
        if itinerary and hasattr(itinerary, "model_copy"):
            itinerary = itinerary.model_copy(update={"id": itinerary_id})

        # Persist to DB (best-effort)
        await _persist_trip(
            session_id=session_id,
            trip_id=itinerary_id,
            query=query,
            state=final_state,
            itinerary=itinerary,
        )

        token_usage = final_state.get("token_usage", {})
        total_tokens = sum(u.total_tokens for u in token_usage.values())

        yield _sse(
            "complete",
            {
                "itinerary_id": itinerary_id,
                "session_id": session_id,
                "itinerary": itinerary.model_dump() if itinerary else None,
            },
        )
        yield _sse(
            "usage_summary",
            {
                "session_id": session_id,
                "total_tokens": total_tokens,
                "per_agent": {
                    name: {"tokens": u.total_tokens, "cost_usd": u.cost_usd}
                    for name, u in token_usage.items()
                },
            },
        )

    except Exception as exc:
        logger.error("stream_graph_error", error=str(exc), session_id=session_id)
        yield _sse("error", {"message": str(exc), "session_id": session_id})


async def _persist_trip(
    session_id: str,
    trip_id: str,
    query: str,
    state: dict[str, Any],
    itinerary: Any,
) -> None:
    """Persist the completed trip to the database.  Best-effort — never blocks SSE."""
    try:
        from sqlalchemy import text

        from app.db import AsyncSessionLocal

        itinerary_json = itinerary.model_dump_json() if itinerary else None
        is_intl = state.get("is_international", False)
        reality_score = None
        ctx = state.get("destination_context_report")
        if ctx and hasattr(ctx, "crowd_level"):
            # Map crowd level to a simple score for indexing
            reality_score = {"Low": 85, "Moderate": 65, "High": 45, "Extreme": 20}.get(
                ctx.crowd_level, 50
            )

        async with AsyncSessionLocal() as session:
            await session.execute(
                text("""
                    INSERT INTO trips (id, session_id, query, is_international, itinerary_json, reality_score)
                    VALUES (:id, :session_id, :query, :is_international, CAST(:itinerary AS jsonb), :reality_score)
                    ON CONFLICT (id) DO UPDATE
                    SET itinerary_json = CAST(EXCLUDED.itinerary AS jsonb),
                        updated_at = NOW()
                """),
                {
                    "id": trip_id,
                    "session_id": session_id,
                    "query": query[:2000],
                    "is_international": is_intl,
                    "itinerary": itinerary_json,
                    "reality_score": reality_score,
                },
            )
            await session.commit()
    except Exception as exc:
        logger.warning("trip_persist_failed", error=str(exc), session_id=session_id)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/plan")
async def plan_trip(request: PlanRequest) -> StreamingResponse:
    """Start a planning session and stream SSE events."""
    session_id = request.session_id or str(uuid.uuid4())
    overrides: dict[str, Any] = {}
    if request.source:
        overrides["source"] = request.source
    if request.destination:
        overrides["destination"] = request.destination

    logger.info("plan_trip_start", session_id=session_id, query=request.query[:80])

    return StreamingResponse(
        _stream_graph(query=request.query, session_id=session_id, overrides=overrides),
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
                    "UPDATE trips SET itinerary_json = itinerary_json || :patch, updated_at = NOW() "
                    "WHERE id = :id"
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
