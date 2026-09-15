import { useCallback, useEffect, useReducer, useRef } from "react";
import {
  clarifyTrip,
  cancelTripPlanning,
  downloadItineraryPdf,
  getSessionItinerary,
  getSessionTurns,
  planTrip,
} from "@/lib/api";
import { parseSseStream, toTripStreamEvent } from "@/lib/sse";
import type {
  ClarificationPrompt,
  CompletedAgentActivity,
  Itinerary,
  TripStreamEvent,
  UsageSummaryEvent,
} from "@/lib/types";
import { agentInfo } from "@/lib/agent-catalog";

export type TurnStatus = "planning" | "awaiting_clarification" | "complete" | "error";

/** One prompt→response exchange in the conversation transcript. */
export type PlannerTurn = {
  id: string;
  prompt: string;
  startedAt: string;
  status: TurnStatus;
  completedAgents: CompletedAgentActivity[];
  planningStartedAt: number | null;
  itinerary: Itinerary | null;
  itineraryId: string | null;
  usage: UsageSummaryEvent | null;
  clarificationPrompts: ClarificationPrompt[];
  clarificationRound: number;
  agentStartedAt: Record<string, number>;
  errorMessage: string | null;
};

export type TripPlannerState = {
  sessionId: string | null;
  turns: PlannerTurn[];
  isDownloading: boolean;
  pdfError: string | null;
};

const initialState: TripPlannerState = {
  sessionId: null,
  turns: [],
  isDownloading: false,
  pdfError: null,
};

function newTurn(prompt: string): PlannerTurn {
  return {
    id: `turn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    prompt,
    startedAt: new Date().toISOString(),
    status: "planning",
    completedAgents: [],
    planningStartedAt: Date.now(),
    itinerary: null,
    itineraryId: null,
    usage: null,
    clarificationPrompts: [],
    clarificationRound: 0,
    agentStartedAt: {},
    errorMessage: null,
  };
}

type Action =
  | { type: "turn_started"; prompt: string }
  | { type: "clarification_submitted" }
  | { type: "planning_cancelled" }
  | { type: "hydrated"; sessionId: string; turns: PlannerTurn[] }
  | { type: "stream_event"; event: TripStreamEvent }
  | { type: "stream_ended_unexpectedly" }
  | { type: "pdf_download_started" }
  | { type: "pdf_download_finished" }
  | { type: "pdf_download_failed"; message: string };

function patchLastTurn(
  state: TripPlannerState,
  patch: (turn: PlannerTurn) => PlannerTurn,
): TripPlannerState {
  if (state.turns.length === 0) {
    return state;
  }
  const turns = state.turns.slice();
  const last = turns[turns.length - 1]!;
  turns[turns.length - 1] = patch(last);
  return { ...state, turns };
}

function reducer(state: TripPlannerState, action: Action): TripPlannerState {
  switch (action.type) {
    case "turn_started":
      return { ...state, pdfError: null, turns: [...state.turns, newTurn(action.prompt)] };

    case "clarification_submitted":
      return patchLastTurn(state, (turn) => ({
        ...turn,
        status: "planning",
        clarificationPrompts: [],
      }));

    case "planning_cancelled":
      return patchLastTurn(state, (turn) =>
        turn.status === "planning"
          ? { ...turn, status: "error", errorMessage: "Planning stopped." }
          : turn,
      );

    case "hydrated":
      return { ...initialState, sessionId: action.sessionId, turns: action.turns };

    case "stream_event":
      return applyStreamEvent(state, action.event);

    case "stream_ended_unexpectedly":
      return patchLastTurn(state, (turn) =>
        turn.status === "planning"
          ? { ...turn, status: "error", errorMessage: "Connection closed unexpectedly." }
          : turn,
      );

    case "pdf_download_started":
      return { ...state, isDownloading: true, pdfError: null };

    case "pdf_download_finished":
      return { ...state, isDownloading: false };

    case "pdf_download_failed":
      return { ...state, isDownloading: false, pdfError: action.message };

    default:
      return state;
  }
}

function applyStreamEvent(state: TripPlannerState, event: TripStreamEvent): TripPlannerState {
  switch (event.event) {
    case "agent_start":
      return patchLastTurn(
        { ...state, sessionId: event.data.session_id },
        (turn) => ({
          ...turn,
          planningStartedAt: turn.planningStartedAt ?? Date.now(),
          agentStartedAt: { ...turn.agentStartedAt, [event.data.agent]: Date.now() },
        }),
      );

    case "agent_done": {
      const withSession = { ...state, sessionId: event.data.session_id };
      return patchLastTurn(withSession, (turn) => {
        const startedAt = turn.agentStartedAt[event.data.agent] ?? turn.planningStartedAt ?? Date.now();
        const entry: CompletedAgentActivity = {
          agent: event.data.agent,
          label: agentInfo(event.data.agent).label,
          preview: event.data.preview,
          layer: event.data.layer,
          elapsedMs: Date.now() - startedAt,
        };
        return { ...turn, completedAgents: [...turn.completedAgents, entry] };
      });
    }

    case "needs_clarification":
      return patchLastTurn(
        { ...state, sessionId: event.data.session_id },
        (turn) => ({
          ...turn,
          status: "awaiting_clarification",
          clarificationPrompts: event.data.prompts,
          clarificationRound: event.data.round,
        }),
      );

    case "complete":
      return patchLastTurn(
        { ...state, sessionId: event.data.session_id },
        (turn) => ({
          ...turn,
          status: "complete",
          itinerary: event.data.itinerary,
          itineraryId: event.data.itinerary_id,
        }),
      );

    case "usage_summary":
      return patchLastTurn(state, (turn) => ({ ...turn, usage: event.data }));

    case "error":
      return patchLastTurn(state, (turn) => ({
        ...turn,
        status: "error",
        errorMessage: event.data.message,
      }));

    default:
      return state;
  }
}

/** Consumes a trip-planning SSE response, dispatching one action per event. */
async function consumeTripStream(
  response: Response,
  dispatch: (action: Action) => void,
): Promise<void> {
  if (!response.body) {
    dispatch({ type: "stream_ended_unexpectedly" });
    return;
  }

  let receivedTerminalEvent = false;

  for await (const raw of parseSseStream(response.body)) {
    const event = toTripStreamEvent(raw);
    if (!event) {
      continue;
    }
    dispatch({ type: "stream_event", event });
    if (
      event.event === "needs_clarification" ||
      event.event === "complete" ||
      event.event === "error"
    ) {
      receivedTerminalEvent = true;
    }
  }

  if (!receivedTerminalEvent) {
    dispatch({ type: "stream_ended_unexpectedly" });
  }
}

/** Rebuilds a transcript from stored turns, attaching the final itinerary to the last turn. */
function buildHydratedTurns(
  storedTurns: { role: string; content: string; trip_id: string | null; created_at: string }[],
  itinerary: Itinerary | null,
): PlannerTurn[] {
  const userTurns = storedTurns.filter((turn) => turn.role === "user");
  if (userTurns.length === 0) {
    if (!itinerary) {
      return [];
    }
    return [
      {
        ...newTurn(""),
        status: "complete",
        planningStartedAt: null,
        itinerary,
        itineraryId: itinerary.id,
      },
    ];
  }

  return userTurns.map((turn, index) => {
    const isLast = index === userTurns.length - 1;
    return {
      ...newTurn(turn.content),
      startedAt: turn.created_at,
      status: "complete",
      planningStartedAt: null,
      itinerary: isLast ? itinerary : null,
      itineraryId: isLast ? (itinerary?.id ?? null) : null,
    };
  });
}

type UseTripPlannerOptions = {
  username?: string | null;
  initialSessionId?: string;
  onSessionCreated?: (sessionId: string) => void;
};

export function useTripPlanner(options: UseTripPlannerOptions = {}) {
  const { username, initialSessionId, onSessionCreated } = options;
  const [state, dispatch] = useReducer(reducer, initialState);
  const abortRef = useRef<AbortController | null>(null);
  const notifiedSessionRef = useRef<string | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  // Notify the shell when a session id is first established (URL + sidebar sync).
  useEffect(() => {
    if (state.sessionId && notifiedSessionRef.current !== state.sessionId) {
      notifiedSessionRef.current = state.sessionId;
      onSessionCreated?.(state.sessionId);
    }
  }, [state.sessionId, onSessionCreated]);

  // Hydrate a saved session when navigating directly to /c/[sessionId].
  useEffect(() => {
    if (!initialSessionId) {
      return;
    }
    notifiedSessionRef.current = initialSessionId;
    let cancelled = false;
    void (async () => {
      const [itinerary, storedTurns] = await Promise.all([
        getSessionItinerary(initialSessionId).catch(() => null),
        getSessionTurns(initialSessionId).catch(() => []),
      ]);
      if (!cancelled) {
        dispatch({
          type: "hydrated",
          sessionId: initialSessionId,
          turns: buildHydratedTurns(storedTurns, itinerary),
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initialSessionId]);

  const lastTurn = state.turns.at(-1) ?? null;
  const isBusy = lastTurn?.status === "planning";

  const submitPrompt = useCallback(
    (prompt: string) => {
      if (isBusy) {
        return;
      }
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const isFollowup = Boolean(state.sessionId && lastTurn?.itinerary);
      dispatch({ type: "turn_started", prompt });

      void (async () => {
        try {
          const response = await planTrip(
            {
              query: prompt,
              username: username ?? undefined,
              session_id: isFollowup ? state.sessionId ?? undefined : undefined,
              mode: isFollowup ? "followup" : "new",
            },
            controller.signal,
          );
          await consumeTripStream(response, dispatch);
        } catch (error) {
          if (controller.signal.aborted) {
            return;
          }
          dispatch({
            type: "stream_event",
            event: { event: "error", data: { message: toErrorMessage(error) } },
          });
        }
      })();
    },
    [username, state.sessionId, lastTurn, isBusy],
  );

  const submitClarification = useCallback(
    (answers: Record<string, string>) => {
      const sessionId = state.sessionId;
      if (!sessionId) {
        return;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      dispatch({ type: "clarification_submitted" });

      void (async () => {
        try {
          const response = await clarifyTrip(sessionId, { answers }, controller.signal);
          await consumeTripStream(response, dispatch);
        } catch (error) {
          if (controller.signal.aborted) {
            return;
          }
          dispatch({
            type: "stream_event",
            event: { event: "error", data: { message: toErrorMessage(error) } },
          });
        }
      })();
    },
    [state.sessionId],
  );

  const cancelPlanning = useCallback(async () => {
    if (!isBusy) {
      return;
    }
    const sessionId = state.sessionId;
    if (sessionId) {
      await cancelTripPlanning(sessionId).catch(() => undefined);
    }
    abortRef.current?.abort();
    abortRef.current = null;
    dispatch({ type: "planning_cancelled" });
  }, [isBusy, state.sessionId]);

  const downloadPdf = useCallback(async (tripId: string) => {
    if (!tripId) {
      return;
    }
    dispatch({ type: "pdf_download_started" });
    try {
      const { blob, filename } = await downloadItineraryPdf(tripId);
      triggerBrowserDownload(blob, filename);
      dispatch({ type: "pdf_download_finished" });
    } catch (error) {
      dispatch({ type: "pdf_download_failed", message: toErrorMessage(error) });
    }
  }, []);

  return { state, isBusy, submitPrompt, submitClarification, cancelPlanning, downloadPdf };
}

function triggerBrowserDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function toErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}
