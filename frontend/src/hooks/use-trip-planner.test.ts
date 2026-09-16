import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initialState, reducer, type TripPlannerState } from "@/hooks/use-trip-planner";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function startTurn(prompt = "Plan a trip"): TripPlannerState {
  return reducer(initialState, { type: "turn_started", prompt, sessionId: "session-1" });
}

describe("use-trip-planner reducer — active agent tracking", () => {
  it("tracks an agent as active once agent_start arrives, and moves it to completed on agent_done", () => {
    let state = startTurn();
    state = reducer(state, {
      type: "stream_event",
      event: { event: "agent_start", data: { agent: "orchestrator", session_id: "session-1" } },
    });

    expect(state.turns[0]?.activeAgents).toEqual(["orchestrator"]);
    expect(state.turns[0]?.completedAgents).toHaveLength(0);

    state = reducer(state, {
      type: "stream_event",
      event: {
        event: "agent_done",
        data: { agent: "orchestrator", layer: 0, session_id: "session-1", preview: "Kolkata → Goa" },
      },
    });

    expect(state.turns[0]?.activeAgents).toEqual([]);
    expect(state.turns[0]?.completedAgents.map((entry) => entry.agent)).toEqual(["orchestrator"]);
  });

  it("never reports a skipped agent (e.g. visa) as active or completed", () => {
    let state = startTurn();
    state = reducer(state, {
      type: "stream_event",
      event: { event: "agent_start", data: { agent: "transport_search", session_id: "session-1" } },
    });
    state = reducer(state, {
      type: "stream_event",
      event: {
        event: "agent_done",
        data: { agent: "transport_search", layer: 2, session_id: "session-1", preview: "Found 3 options" },
      },
    });

    expect(state.turns[0]?.activeAgents).not.toContain("visa");
    expect(state.turns[0]?.completedAgents.map((entry) => entry.agent)).not.toContain("visa");
  });

  it("tracks multiple agents running in parallel independently", () => {
    let state = startTurn();
    state = reducer(state, {
      type: "stream_event",
      event: { event: "agent_start", data: { agent: "transport_search", session_id: "session-1" } },
    });
    state = reducer(state, {
      type: "stream_event",
      event: { event: "agent_start", data: { agent: "stay_search", session_id: "session-1" } },
    });
    expect(state.turns[0]?.activeAgents).toEqual(["transport_search", "stay_search"]);

    state = reducer(state, {
      type: "stream_event",
      event: {
        event: "agent_done",
        data: { agent: "transport_search", layer: 2, session_id: "session-1", preview: "Done" },
      },
    });
    expect(state.turns[0]?.activeAgents).toEqual(["stay_search"]);
  });
});

describe("use-trip-planner reducer — elapsed timer pause/resume", () => {
  it("pauses the running clock when a clarification is requested", () => {
    let state = startTurn();
    const startedRunningSince = state.turns[0]?.runningSince;
    expect(startedRunningSince).not.toBeNull();

    vi.advanceTimersByTime(2000);
    state = reducer(state, {
      type: "stream_event",
      event: {
        event: "needs_clarification",
        data: { session_id: "session-1", request_id: "req-1", requester: "orchestrator", prompts: [], round: 0 },
      },
    });

    const turn = state.turns[0]!;
    expect(turn.status).toBe("awaiting_clarification");
    expect(turn.runningSince).toBeNull();
    expect(turn.activeElapsedMs).toBeGreaterThanOrEqual(2000);
  });

  it("does not accumulate elapsed time while paused, and resumes cleanly on submit", () => {
    let state = startTurn();
    vi.advanceTimersByTime(1000);
    state = reducer(state, {
      type: "stream_event",
      event: {
        event: "needs_clarification",
        data: { session_id: "session-1", request_id: "req-1", requester: "orchestrator", prompts: [], round: 0 },
      },
    });
    const pausedElapsed = state.turns[0]!.activeElapsedMs;

    // Time passes while the user is answering the clarification prompt.
    vi.advanceTimersByTime(10_000);
    state = reducer(state, { type: "clarification_submitted" });

    const resumed = state.turns[0]!;
    expect(resumed.status).toBe("planning");
    expect(resumed.runningSince).not.toBeNull();
    expect(resumed.activeElapsedMs).toBe(pausedElapsed);
  });

  it("freezes the clock when planning completes", () => {
    let state = startTurn();
    vi.advanceTimersByTime(3000);
    state = reducer(state, {
      type: "stream_event",
      event: {
        event: "complete",
        data: { session_id: "session-1", itinerary_id: "trip-1", itinerary: null },
      },
    });

    const turn = state.turns[0]!;
    expect(turn.status).toBe("complete");
    expect(turn.runningSince).toBeNull();
    expect(turn.activeElapsedMs).toBeGreaterThanOrEqual(3000);
  });
});
