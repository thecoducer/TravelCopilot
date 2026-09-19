"""SSE streaming orchestration for the trip planning graph.

Emits the following SSE event types while running / resuming the LangGraph:
  agent_start | agent_done | needs_clarification | complete | usage_summary | error
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from langgraph.types import Command

from app.graph.graph import get_compiled_graph
from app.graph.state import initial_state
from app.services import trip_service, usage_service

logger = structlog.get_logger(__name__)


AGENT_LAYERS: dict[str, int] = {
    "orchestrator": 0,
    "stops_discovery": 1,
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


def sse_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _result_count(*values: Any) -> int:
    """Count result items across flat and per-stop/per-leg state shapes."""
    count = 0
    for value in values:
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, dict):
            count += sum(len(items) if isinstance(items, list) else 1 for items in value.values())
    return count


def _found_preview(count: int, singular: str, plural: str) -> str:
    if count == 0:
        return f"No {plural} found"
    return f"Found {count} {singular if count == 1 else plural}"


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _nested_item_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return sum(_nested_item_count(items) for items in value.values())
    return 0


def _route_preview(output: dict[str, Any]) -> str:
    source = str(output.get("source") or "").strip()
    destination = str(output.get("destination") or "").strip()
    if source and destination:
        return f"{source} → {destination}"
    return source or destination or "Extracting trip details"


def agent_preview(agent_name: str, output: dict[str, Any]) -> str:
    try:
        m: dict[str, Any] = {
            "orchestrator": _route_preview,
            "stops_discovery": lambda o: (
                f"{len(o.get('stops', {}) or {})} stops planned"
                if o.get("stops")
                else "Single destination"
            ),
            "safety": lambda o: (
                f"{len(_field(o.get('safety_report'), 'top_scams', []))} scams found"
            ),
            "visa": lambda o: (
                f"Visa required: {_field(o.get('visa_report'), 'visa_required', 'N/A')}"
            ),
            "transport_search": lambda o: _found_preview(
                _result_count(o.get("transport_legs_raw"), o.get("transport_legs_raw_by_leg")),
                "transport option",
                "transport options",
            ),
            "stay_search": lambda o: _found_preview(
                _result_count(o.get("stays_raw"), o.get("stays_raw_by_stop")),
                "hotel",
                "hotels",
            ),
            "local_experiences": lambda o: _found_preview(
                _result_count(o.get("experiences_raw"), o.get("experiences_raw_by_stop")),
                "experience",
                "experiences",
            ),
            "self_drive_search": lambda o: _found_preview(
                _result_count(_field(o.get("self_drive_report"), "rental_options", [])),
                "rental option",
                "rental options",
            ),
            "reviews": lambda o: _found_preview(
                len(o.get("reviews_summary", {}) or {}),
                "review summary",
                "review summaries",
            ),
            "food_discovery": lambda o: _found_preview(
                _nested_item_count(o.get("food_recommendations_by_stop")),
                "food recommendation",
                "food recommendations",
            ),
            "stay_analyst": lambda o: _found_preview(
                _result_count(o.get("stays_shortlist"), o.get("stays_shortlist_by_stop")),
                "shortlisted stay",
                "shortlisted stays",
            ),
            "transport_optimizer": lambda o: (
                _field(o.get("transport_recommendation"), "rationale", "")[:80] or "Done"
            ),
            "budget_planner": lambda o: (
                f"{_field(o.get('budget_report'), 'total_estimated_cost', '?')} "
                f"({_field(o.get('budget_report'), 'vs_budget_verdict', '?')})"
            ),
            "itinerary_compiler": lambda o: _field(o.get("itinerary"), "title", "Done"),
        }
        fn = m.get(agent_name)
        return fn(output) if fn else "Done"
    except Exception:
        return "Done"


def _graph_chunk_events(mode: str, chunk: Any, session_id: str) -> tuple[list[str], bool]:
    """Translate one ``astream`` chunk into SSE events.

    Returns ``(events, paused)`` where ``paused`` means the graph hit a
    clarification interrupt and the caller must close the stream.
    """
    if mode == "tasks":
        name = chunk.get("name") if isinstance(chunk, dict) else None
        is_task_start = isinstance(chunk, dict) and "result" not in chunk and "error" not in chunk
        if is_task_start and name in AGENT_LAYERS:
            return [sse_event("agent_start", {"agent": name, "session_id": session_id})], False
        return [], False

    if "__interrupt__" in chunk:
        interrupt_val = chunk["__interrupt__"][0]
        payload = interrupt_val.value if hasattr(interrupt_val, "value") else interrupt_val
        return [
            sse_event(
                "needs_clarification",
                {
                    "session_id": session_id,
                    "request_id": payload.get("request_id"),
                    "requester": payload.get("requester"),
                    "prompts": payload.get("prompts", []),
                    "round": payload.get("round", 0),
                },
            )
        ], True

    return [
        sse_event(
            "agent_done",
            {
                "agent": node_name,
                "layer": AGENT_LAYERS.get(node_name, -1),
                "session_id": session_id,
                "preview": agent_preview(node_name, node_output),
            },
        )
        for node_name, node_output in chunk.items()
    ], False


async def stream_graph(
    query: str,
    session_id: str,
    trip_id: str,
    username: str | None = None,
    mode: str = "new",
) -> AsyncGenerator[str, None]:
    from app.llm import reset_active_llm_run_id, set_active_llm_run_id
    from app.observability.langfuse import get_langfuse_handler
    from app.services import chat_turn_service
    from app.services.cancellation_service import register, unregister

    register(session_id)
    started_at = time.perf_counter()
    # One trip_id == one planning run, so usage is tracked per turn, not per session.
    llm_run_token = set_active_llm_run_id(trip_id)
    is_followup = mode == "followup"

    try:
        yield sse_event("agent_start", {"agent": "orchestrator", "session_id": session_id})

        compiled = await get_compiled_graph()

        # A follow-up reuses the checkpointed thread: pass only the new query so
        # prior parsed fields and the previous itinerary survive, instead of the
        # full defaults dict that would wipe them.
        state: dict[str, Any] = (
            {"query": query} if is_followup else initial_state(query=query, session_id=session_id)
        )

        await chat_turn_service.append_turn(
            session_id=session_id, role="user", content=query, username=username
        )

        if not is_followup:
            # Persist a stub row immediately so session_id is stored even if the
            # graph pauses for clarification or fails before completion.
            await trip_service.persist_trip(
                session_id=session_id,
                trip_id=trip_id,
                query=query,
                state=state,
                itinerary=None,
                username=username,
            )

        langfuse_handler = get_langfuse_handler(session_id=session_id)
        config: dict[str, Any] = {"configurable": {"thread_id": session_id}}
        if langfuse_handler:
            config["callbacks"] = [langfuse_handler]

        async for mode, chunk in compiled.astream(
            state, stream_mode=["updates", "tasks"], config=config
        ):
            events, paused = _graph_chunk_events(mode, chunk, session_id)
            for event in events:
                yield event
            if paused:
                return  # stream closes; client POSTs to /{session_id}/clarify

        # Graph completed — get final state from checkpoint
        snapshot = await compiled.aget_state(config)
        final_state: dict[str, Any] = snapshot.values if snapshot else {}

        async for event in emit_completion_events(
            final_state=final_state,
            session_id=session_id,
            trip_id=trip_id,
            query=query,
            compiled=compiled,
            config=config,
            username=username,
            started_at=started_at,
        ):
            yield event

    except Exception as exc:
        logger.exception("stream_graph_error", session_id=session_id, error=str(exc))
        yield sse_event("error", {"message": str(exc), "session_id": session_id})
    finally:
        unregister(session_id)
        reset_active_llm_run_id(llm_run_token)


async def stream_resumed_graph(
    session_id: str,
    trip_id: str,
    answers: dict[str, str],
    query: str,
) -> AsyncGenerator[str, None]:
    """Resume a paused graph after the user answers clarification prompts."""
    from app.llm import reset_active_llm_run_id, set_active_llm_run_id
    from app.observability.langfuse import get_langfuse_handler
    from app.services.cancellation_service import register, unregister

    register(session_id)
    started_at = time.perf_counter()
    llm_run_token = set_active_llm_run_id(trip_id)

    try:
        compiled = await get_compiled_graph()

        langfuse_handler = get_langfuse_handler(session_id=session_id)
        config: dict[str, Any] = {"configurable": {"thread_id": session_id}}
        if langfuse_handler:
            config["callbacks"] = [langfuse_handler]

        async for mode, chunk in compiled.astream(
            Command(resume=answers), stream_mode=["updates", "tasks"], config=config
        ):
            events, paused = _graph_chunk_events(mode, chunk, session_id)
            for event in events:
                yield event
            if paused:
                return

        snapshot = await compiled.aget_state(config)
        final_state: dict[str, Any] = snapshot.values if snapshot else {}

        async for event in emit_completion_events(
            final_state=final_state,
            session_id=session_id,
            trip_id=trip_id,
            query=query,
            compiled=compiled,
            config=config,
            started_at=started_at,
        ):
            yield event

    except Exception as exc:
        logger.exception("stream_resumed_error", session_id=session_id, error=str(exc))
        yield sse_event("error", {"message": str(exc), "session_id": session_id})
    finally:
        unregister(session_id)
        reset_active_llm_run_id(llm_run_token)


async def emit_completion_events(
    final_state: dict[str, Any],
    session_id: str,
    trip_id: str,
    query: str,
    compiled: Any,
    config: dict[str, Any],
    username: str | None = None,
    started_at: float | None = None,
) -> AsyncGenerator[str, None]:
    """Emit ``complete`` and ``usage_summary`` SSE events after the graph finishes."""
    if final_state.get("error") and not final_state.get("itinerary"):
        yield sse_event(
            "error",
            {
                "message": final_state["error"],
                "missing_required_fields": final_state.get("missing_required_fields", []),
                "session_id": session_id,
            },
        )
        return

    itinerary = final_state.get("itinerary")
    if itinerary and hasattr(itinerary, "model_copy"):
        itinerary = itinerary.model_copy(update={"id": trip_id})

    usage_summary = await usage_service.get_run_usage(trip_id)
    if started_at is not None:
        usage_summary.total_duration_ms = round((time.perf_counter() - started_at) * 1000, 1)

    await trip_service.persist_trip(
        session_id=session_id,
        trip_id=trip_id,
        query=query,
        state=final_state,
        itinerary=itinerary,
        run_usage=usage_summary,
        username=username,
    )
    await usage_service.clear_run_usage(trip_id)

    from app.services import chat_turn_service

    assistant_summary = getattr(itinerary, "title", None) or "Itinerary ready"
    await chat_turn_service.append_turn(
        session_id=session_id,
        role="assistant",
        content=str(assistant_summary),
        username=username,
        trip_id=trip_id,
    )

    yield sse_event(
        "complete",
        {
            "itinerary_id": trip_id,
            "session_id": session_id,
            "itinerary": itinerary.model_dump() if itinerary else None,
        },
    )
    logger.info(
        "run_usage_summary",
        session_id=session_id,
        trip_id=trip_id,
        **usage_summary.model_dump(),
    )
    yield sse_event(
        "usage_summary",
        {"session_id": session_id, **usage_summary.model_dump()},
    )
