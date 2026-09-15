"""SSE streaming orchestration for the trip planning graph.

Emits the following SSE event types while running / resuming the LangGraph:
  agent_start | agent_done | needs_clarification | complete | usage_summary | error
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from langgraph.types import Command

from app.graph.graph import get_compiled_graph
from app.graph.state import initial_state
from app.services import trip_service

logger = structlog.get_logger(__name__)


AGENT_LAYERS: dict[str, int] = {
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


def sse_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def agent_preview(agent_name: str, output: dict[str, Any]) -> str:
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


async def stream_graph(
    query: str,
    session_id: str,
    trip_id: str,
    username: str | None = None,
    mode: str = "new",
) -> AsyncGenerator[str, None]:
    from app.llm import reset_active_llm_session_id, set_active_llm_session_id
    from app.observability.langfuse import get_langfuse_handler
    from app.services import chat_turn_service
    from app.services.cancellation_service import register, unregister

    register(session_id)
    llm_session_token = set_active_llm_session_id(session_id)
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

        async for chunk in compiled.astream(state, stream_mode="updates", config=config):
            # Detect interrupt() from OrchestratorAgent — graph is paused
            if "__interrupt__" in chunk:
                interrupt_val = chunk["__interrupt__"][0]
                payload = interrupt_val.value if hasattr(interrupt_val, "value") else interrupt_val
                yield sse_event(
                    "needs_clarification",
                    {
                        "session_id": session_id,
                        "prompts": payload.get("prompts", []),
                        "round": payload.get("round", 0),
                    },
                )
                return  # stream closes; client POSTs to /{session_id}/clarify

            for node_name, node_output in chunk.items():
                yield sse_event(
                    "agent_done",
                    {
                        "agent": node_name,
                        "layer": AGENT_LAYERS.get(node_name, -1),
                        "session_id": session_id,
                        "preview": agent_preview(node_name, node_output),
                    },
                )

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
        ):
            yield event

    except Exception as exc:
        logger.exception("stream_graph_error", session_id=session_id, error=str(exc))
        yield sse_event("error", {"message": str(exc), "session_id": session_id})
    finally:
        unregister(session_id)
        reset_active_llm_session_id(llm_session_token)


async def stream_resumed_graph(
    session_id: str,
    trip_id: str,
    answers: dict[str, str],
    query: str,
) -> AsyncGenerator[str, None]:
    """Resume a paused graph after the user answers clarification prompts."""
    from app.llm import reset_active_llm_session_id, set_active_llm_session_id
    from app.observability.langfuse import get_langfuse_handler
    from app.services.cancellation_service import register, unregister

    register(session_id)
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
                yield sse_event(
                    "needs_clarification",
                    {
                        "session_id": session_id,
                        "prompts": payload.get("prompts", []),
                        "round": payload.get("round", 0),
                    },
                )
                return

            for node_name, node_output in chunk.items():
                yield sse_event(
                    "agent_done",
                    {
                        "agent": node_name,
                        "layer": AGENT_LAYERS.get(node_name, -1),
                        "session_id": session_id,
                        "preview": agent_preview(node_name, node_output),
                    },
                )

        snapshot = await compiled.aget_state(config)
        final_state: dict[str, Any] = snapshot.values if snapshot else {}

        async for event in emit_completion_events(
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
        yield sse_event("error", {"message": str(exc), "session_id": session_id})
    finally:
        unregister(session_id)
        reset_active_llm_session_id(llm_session_token)


async def emit_completion_events(
    final_state: dict[str, Any],
    session_id: str,
    trip_id: str,
    query: str,
    compiled: Any,
    config: dict[str, Any],
    username: str | None = None,
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

    usage_summary = await build_usage_summary(final_state=final_state, session_id=session_id)

    await trip_service.persist_trip(
        session_id=session_id,
        trip_id=trip_id,
        query=query,
        state=final_state,
        itinerary=itinerary,
        usage_summary=usage_summary,
        username=username,
    )

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
    yield sse_event(
        "usage_summary",
        {
            "session_id": session_id,
            "total_tokens": usage_summary["total_tokens"],
            "total_cost_usd": usage_summary["total_cost_usd"],
            "total_latency_ms": usage_summary["total_latency_ms"],
            "per_agent": usage_summary["per_agent"],
        },
    )


async def build_usage_summary(final_state: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Build usage summary from Redis usage cache; fallback to graph state when absent."""
    from app.llm import flush_usage_events

    await flush_usage_events()
    per_agent: dict[str, dict[str, Any]] = {}
    total_tokens = 0
    total_cost_usd = 0.0
    total_latency_ms = 0.0

    # Preferred source: live per-agent cache written by UsageLogger callbacks.
    try:
        from app.services.cache_service import CacheService

        cache = CacheService()
        for attempt in range(4):
            per_agent = {}
            total_tokens = 0
            total_cost_usd = 0.0
            total_latency_ms = 0.0

            for agent in AGENT_LAYERS:
                row = await cache.get(CacheService.usage_key(session_id, agent))
                if not row:
                    continue

                prompt_tokens = int(row.get("prompt_tokens", 0) or 0)
                completion_tokens = int(row.get("completion_tokens", 0) or 0)
                agent_total = int(row.get("total_tokens", prompt_tokens + completion_tokens) or 0)
                cost_usd = float(row.get("cost_usd", 0.0) or 0.0)
                latency_ms = float(row.get("latency_ms", 0.0) or 0.0)

                per_agent[agent] = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": agent_total,
                    "cost_usd": cost_usd,
                    "latency_ms": latency_ms,
                }
                total_tokens += agent_total
                total_cost_usd += cost_usd
                total_latency_ms += latency_ms

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
                "latency_ms": float(getattr(usage, "latency_ms", 0.0) or 0.0),
            }
            total_tokens += agent_total
            total_cost_usd += cost_usd
            total_latency_ms += float(getattr(usage, "latency_ms", 0.0) or 0.0)

    return {
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost_usd,
        "total_latency_ms": total_latency_ms,
        "per_agent": per_agent,
    }
