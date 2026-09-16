"""LangGraph StateGraph — 14 agent nodes with managed clarification.

The ClarificationManager uses LangGraph ``interrupt()`` to pause the graph
when a query or domain-specific input is ambiguous. The client resumes via
``POST /api/trip/{session_id}/clarify`` — no full re-POST is needed. Every
interrupt lives in a dedicated LLM-free node, because LangGraph re-executes a
node from the top on resume.

After the orchestrator finishes (with or without clarification rounds), route
discovery fans out directly to the Layer 1 and Layer 2 entry nodes in parallel.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.budget_planner_agent import BudgetPlannerAgent
from app.agents.food_discovery_agent import FoodDiscoveryAgent
from app.agents.itinerary_compiler_agent import ItineraryCompilerAgent
from app.agents.local_experiences_agent import LocalExperiencesAgent
from app.agents.orchestrator import (
    OrchestratorAgent,
    optional_clarification_node,
    orchestrator_clarification_node,
)
from app.agents.reviews_agent import ReviewsAgent
from app.agents.safety_agent import SafetyAgent
from app.agents.self_drive_search_agent import SelfDriveSearchAgent
from app.agents.stay_analyst_agent import StayAnalystAgent
from app.agents.stay_search_agent import StaySearchAgent
from app.agents.stops_discovery_agent import StopsDiscoveryAgent
from app.agents.transport_optimizer_agent import TransportOptimizerAgent
from app.agents.transport_search_agent import TransportSearchAgent
from app.agents.visa_agent import VisaAgent
from app.config import settings
from app.graph.state import TripState, initial_state
from app.logging import get_agent_logger
from app.models.clarification import ClarificationPrompt
from app.services.clarification_manager import ClarificationManager
from app.tools.factory import ToolFactory


async def _route_clarification_node(state: dict[str, Any]) -> dict[str, Any]:
    """Pause the graph when StopsDiscoveryAgent could not shape a usable route.

    Reuses the shared ClarificationManager interrupt/resume mechanism
    instead of silently falling back to a single-destination itinerary — a
    ``discovery_failed`` route must never reach Layer 2 supply search.
    """
    session_id = state.get("session_id", "")
    round_ = state.get("clarification_round", 0)
    log = get_agent_logger("stops_discovery", session_id)
    log.info("route_clarification_requested", round=round_)

    prompt = ClarificationPrompt(
        field="destination",
        question=(
            "I couldn't work out a clear route for this trip — could you name the"
            " specific places or region you'd like to visit?"
        ),
        reason="Route discovery failed",
        input_type="text",
    )
    answers = ClarificationManager.request(
        [prompt], requester="route_clarification", round_number=round_
    )
    updates: dict[str, Any] = {"clarification_round": round_ + 1}
    new_destination = answers.get("destination", "").strip()
    if new_destination:
        updates["destination"] = new_destination
    return updates


async def _discovery_failed_end_node(state: dict[str, Any]) -> dict[str, Any]:
    """Hard-stop after clarification rounds are exhausted and no route was shaped.

    A ``discovery_failed`` route must never silently degrade into a plausible-
    looking but wrong single-destination itinerary (see spec's non-negotiable
    acceptance gates).
    """
    log = get_agent_logger("stops_discovery", state.get("session_id", ""))
    log.error("route_discovery_failed_hard_stop")
    return {"error": "Could not determine a usable trip route from the query provided."}


async def _required_fields_end_node(state: dict[str, Any]) -> dict[str, Any]:
    """Hard-stop before route discovery when required query fields remain missing."""
    log = get_agent_logger("orchestrator", state.get("session_id", ""))
    fields = state.get("missing_required_fields", [])
    log.error("required_trip_fields_missing", fields=fields)
    return {
        "error": "Required trip details are missing: " + ", ".join(fields),
    }


def _route_after_orchestrator(state: dict[str, Any]) -> str:
    if state.get("missing_required_fields") or state.get("error"):
        return "required_fields_end"
    if state.get("pending_clarification_fields"):
        return "orchestrator_clarification"
    return "optional_clarification"


def _route_after_discovery(state: dict[str, Any]) -> str | list[str]:
    if state.get("route_discovery_status") != "discovery_failed":
        # visa has no downstream edge (its report is only read from state later), so
        # skipping it entirely for domestic trips is safe: nothing waits on it as a
        # named barrier source.
        routes = ["transport_search", "stay_search", "local_experiences", "food_discovery"]
        if state.get("is_international"):
            routes.append("visa")
        return routes
    if state.get("clarification_round", 0) >= settings.max_clarification_rounds:
        return "discovery_failed_end"
    return "route_clarification"


def _route_after_transport_search(state: dict[str, Any]) -> list[str]:
    # self_drive_search is skipped entirely unless the traveller wants to self-drive.
    # It is deliberately NOT a named source in the budget_planner barrier below: when
    # it does run, it shares transport_optimizer's graph depth, so its state write is
    # always committed before that barrier can resolve — no edge needed for correctness.
    routes = ["transport_optimizer"]
    if state.get("self_drive_intent"):
        routes.append("self_drive_search")
    return routes


# ── Graph builder ──────────────────────────────────────────────────────────────


def build_graph(
    tool_factory: ToolFactory | None = None,
    llm: Any | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """Construct and compile the full planning graph.

    Args:
        tool_factory: Injected factory (mock or real).
        llm: Optional shared LLM instance injected into all agents.
             Primarily used in tests to avoid real API calls.
        checkpointer: LangGraph checkpointer for interrupt/resume support.
                      Pass ``None`` in tests; use ``AsyncPostgresSaver`` in production.
    """
    factory = tool_factory or ToolFactory()

    orchestrator = OrchestratorAgent(llm=llm)
    stops_discovery = StopsDiscoveryAgent(llm=llm)
    safety = SafetyAgent(tool_factory=factory, llm=llm)
    visa = VisaAgent(tool_factory=factory, llm=llm)
    transport_search = TransportSearchAgent(tool_factory=factory, llm=llm)
    stay_search = StaySearchAgent(tool_factory=factory)
    local_experiences = LocalExperiencesAgent(tool_factory=factory, llm=llm)
    transport_optimizer = TransportOptimizerAgent(tool_factory=factory, llm=llm)
    stay_analyst = StayAnalystAgent(llm=llm)
    self_drive_search = SelfDriveSearchAgent(tool_factory=factory, llm=llm)
    reviews = ReviewsAgent(tool_factory=factory, llm=llm)
    food_discovery = FoodDiscoveryAgent(tool_factory=factory)
    budget_planner = BudgetPlannerAgent(tool_factory=factory, llm=llm)
    itinerary_compiler = ItineraryCompilerAgent(tool_factory=factory, llm=llm)

    graph: Any = StateGraph(TripState)

    # Control nodes (orchestration + interrupt-based gates, not a numbered layer)
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("orchestrator_clarification", orchestrator_clarification_node)
    graph.add_node("optional_clarification", optional_clarification_node)
    graph.add_node("route_clarification", _route_clarification_node)
    graph.add_node("discovery_failed_end", _discovery_failed_end_node)
    graph.add_node("required_fields_end", _required_fields_end_node)

    # Layer 1 — Route Discovery + Destination Intelligence
    # (stops_discovery gates every Layer 2 supply-search node; visa runs in
    # parallel with Layer 2 but never blocks it — see plan.md Layer 1 section)
    graph.add_node("stops_discovery", stops_discovery)
    graph.add_node("visa", visa)

    # Layer 2
    graph.add_node("transport_search", transport_search)
    graph.add_node("stay_search", stay_search)
    graph.add_node("local_experiences", local_experiences)

    # Layer 3
    graph.add_node("transport_optimizer", transport_optimizer)
    graph.add_node("stay_analyst", stay_analyst)
    graph.add_node("self_drive_search", self_drive_search)

    # Layer 4
    graph.add_node("reviews", reviews)
    graph.add_node("food_discovery", food_discovery)
    graph.add_node("budget_planner", budget_planner)
    graph.add_node("safety", safety)

    # Layer 5 — deferred so it runs exactly once, after every other node finishes,
    # regardless of how many predecessors feed it (see NamedBarrierValue vs. defer
    # trade-off notes in plan.md).
    graph.add_node("itinerary_compiler", itinerary_compiler, defer=True)

    # ── Edges ──────────────────────────────────────────────────────────────
    graph.add_edge(START, "orchestrator")

    # The orchestrator never pauses itself: it flags the fields it still needs and the
    # clarification node performs the interrupt, so a resume never re-runs the LLM parse.
    graph.add_conditional_edges(
        "orchestrator",
        _route_after_orchestrator,
        {
            "orchestrator_clarification": "orchestrator_clarification",
            "optional_clarification": "optional_clarification",
            "required_fields_end": "required_fields_end",
        },
    )
    graph.add_edge("orchestrator_clarification", "orchestrator")
    graph.add_edge("optional_clarification", "stops_discovery")
    graph.add_edge("required_fields_end", END)

    # Successful route discovery fans out directly to every Layer 1/2 entry node that
    # applies to this trip (including food_discovery, which only needs stops/day
    # allocations, not local_experiences' output); a discovery_failed route never
    # reaches supply search with a fabricated single-destination fallback (see the
    # route spec's acceptance gates).
    graph.add_conditional_edges(
        "stops_discovery",
        _route_after_discovery,
        {
            "visa": "visa",
            "transport_search": "transport_search",
            "stay_search": "stay_search",
            "local_experiences": "local_experiences",
            "food_discovery": "food_discovery",
            "route_clarification": "route_clarification",
            "discovery_failed_end": "discovery_failed_end",
        },
    )
    graph.add_edge("route_clarification", "stops_discovery")
    graph.add_edge("discovery_failed_end", END)

    # Layer 2 → Layer 3. self_drive_search only runs when the traveller wants it;
    # it is excluded from the budget_planner barrier below on purpose (see routing
    # function above), so skipping it here cannot deadlock that barrier.
    graph.add_conditional_edges(
        "transport_search",
        _route_after_transport_search,
        {
            "transport_optimizer": "transport_optimizer",
            "self_drive_search": "self_drive_search",
        },
    )
    graph.add_edge("stay_search", "stay_analyst")

    # reviews barrier: fires exactly once, after both predecessors have completed.
    graph.add_edge(["stay_analyst", "local_experiences"], "reviews")

    # budget_planner barrier: fires exactly once, after all three predecessors have
    # completed (food_discovery included so food costs are never read empty).
    # self_drive_search is deliberately excluded: it shares transport_optimizer's
    # graph depth when it runs, so self_drive_report is already in state by the time
    # this barrier resolves. Naming it here would deadlock the barrier for any trip
    # without self_drive_intent, since a NamedBarrierValue never resolves if one of
    # its named sources never executes.
    graph.add_edge(
        ["transport_optimizer", "stay_analyst", "food_discovery"],
        "budget_planner",
    )

    # food_discovery → safety: agent runs after food outlets are in state;
    # experiences_raw is already committed by local_experiences in the same
    # superstep as food_discovery, so no extra edge is needed for correctness.
    graph.add_edge("food_discovery", "safety")

    # Layer 4 + safety → itinerary_compiler. Plain edges are sufficient because the
    # node is registered with defer=True above.
    graph.add_edge("budget_planner", "itinerary_compiler")
    graph.add_edge("reviews", "itinerary_compiler")
    graph.add_edge("safety", "itinerary_compiler")

    graph.add_edge("itinerary_compiler", END)

    return graph.compile(checkpointer=checkpointer)


_compiled_graph: Any | None = None
_graph_init_lock: Any | None = None


def get_graph() -> Any:
    """Return the compiled graph without a checkpointer.

    Used in tests and scripts where no persistent checkpoint is needed.
    For production use ``get_compiled_graph()`` instead.
    """
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


async def get_compiled_graph() -> Any:
    """Return the production compiled graph (with checkpointer), initialising lazily.

    Async-safe singleton using a lock — safe to call from multiple concurrent
    request handlers.
    """
    import asyncio

    global _compiled_graph, _graph_init_lock

    if _compiled_graph is not None:
        return _compiled_graph

    if _graph_init_lock is None:
        _graph_init_lock = asyncio.Lock()

    async with _graph_init_lock:
        if _compiled_graph is None:
            from app.checkpointer import get_checkpointer

            checkpointer = await get_checkpointer()
            _compiled_graph = build_graph(checkpointer=checkpointer)

    return _compiled_graph


async def run_graph(query: str, session_id: str, **overrides: Any) -> dict[str, Any]:
    """Run the full planning graph for a query.  Returns the final TripState dict."""
    state = initial_state(query=query, session_id=session_id)
    state.update(overrides)
    compiled = await get_compiled_graph()
    config = {"configurable": {"thread_id": session_id}}
    result: dict[str, Any] = await compiled.ainvoke(state, config=config)
    return result
