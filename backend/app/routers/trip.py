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

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from app.graph.graph import get_compiled_graph
from app.models.trip import (
    ClarifyRequest,
    FeedbackRequest,
    ItineraryUpdateRequest,
    PlanRequest,
)
from app.services import trip_service
from app.services.trip_stream_service import stream_graph, stream_resumed_graph

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/trip", tags=["trip"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.post("/plan")
async def plan_trip(request: PlanRequest) -> StreamingResponse:
    """Start a planning session and stream SSE events."""
    session_id = request.session_id or str(uuid.uuid4())
    trip_id = str(uuid.uuid4())

    logger.info("plan_trip_start", session_id=session_id, query=request.query[:80])

    return StreamingResponse(
        stream_graph(
            query=request.query,
            session_id=session_id,
            trip_id=trip_id,
            username=request.username,
            mode=request.mode,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
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

    # Retrieve the original query from the checkpoint so persist_trip can record it
    try:
        compiled = await get_compiled_graph()
        config = {"configurable": {"thread_id": session_id}}
        snapshot = await compiled.aget_state(config)
        query = (snapshot.values or {}).get("query", "") if snapshot else ""
    except Exception:
        query = ""

    # Continue updating the same trip row started in /plan.
    trip_id = await trip_service.get_latest_trip_id(session_id) or str(uuid.uuid4())

    return StreamingResponse(
        stream_resumed_graph(
            session_id=session_id,
            trip_id=trip_id,
            answers=request.answers,
            query=query,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/{session_id}/turns")
async def get_session_turns(session_id: str) -> dict[str, Any]:
    """Return the ordered chat-turn history for a session."""
    from app.services import chat_turn_service

    try:
        turns = await chat_turn_service.list_turns(session_id)
    except Exception as exc:
        logger.warning("get_turns_db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"session_id": session_id, "turns": turns}


@router.get("/{session_id}")
async def get_itinerary(session_id: str) -> dict[str, Any]:
    """Return the latest itinerary for a session from the database."""
    try:
        result = await trip_service.get_latest_itinerary(session_id)
    except Exception as exc:
        logger.warning("get_itinerary_db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    if not result:
        raise HTTPException(status_code=404, detail="No itinerary found for this session")
    return result


@router.put("/{trip_id}/itinerary")
async def update_itinerary(trip_id: str, payload: ItineraryUpdateRequest) -> dict[str, Any]:
    """Persist drag-drop day reorders from the frontend."""
    try:
        await trip_service.update_itinerary_days(trip_id, payload.trip_days)
    except Exception as exc:
        logger.warning("update_itinerary_db_error", error=str(exc))
    return {"status": "ok", "trip_id": trip_id}


@router.get("/{trip_id}/usage")
async def get_usage(trip_id: str) -> dict[str, Any]:
    """Return per-agent token and cost breakdown from the database."""
    try:
        usage = await trip_service.get_usage_json(trip_id)
    except Exception:
        return {"trip_id": trip_id, "message": "Usage data unavailable — check Langfuse dashboard"}

    if usage is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    return {"trip_id": trip_id, "usage": usage}


@router.get("/public/{slug}")
async def get_public_itinerary(slug: str) -> dict[str, Any]:
    """Return a public shared itinerary by slug."""
    try:
        result = await trip_service.get_public_itinerary(slug)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    if not result:
        raise HTTPException(status_code=404, detail="Public itinerary not found")
    return result


@router.post("/{trip_id}/pdf")
async def generate_pdf(trip_id: str) -> Response:
    """Generate a PDF of the itinerary using WeasyPrint."""
    try:
        itinerary_data = await trip_service.get_itinerary_json_for_pdf(trip_id)
    except Exception as exc:
        logger.warning("pdf_db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    if itinerary_data is None:
        raise HTTPException(status_code=404, detail="Itinerary not found")

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
