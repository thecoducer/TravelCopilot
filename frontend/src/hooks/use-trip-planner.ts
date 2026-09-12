import { useCallback, useEffect, useReducer, useRef } from "react";
import { clarifyTrip, downloadItineraryPdf, planTrip } from "@/lib/api";
import { parseSseStream, toTripStreamEvent } from "@/lib/sse";
import type {
  ClarificationPrompt,
  CompletedAgentActivity,
  Itinerary,
  PlannerStatus,
  TripStreamEvent,
  UsageSummaryEvent,
} from "@/lib/types";
import { agentInfo } from "@/lib/agent-catalog";

export type TripPlannerState = {
  status: PlannerStatus;
  sessionId: string | null;
  itineraryId: string | null;
  prompt: string;
  itinerary: Itinerary | null;
  clarificationPrompts: ClarificationPrompt[];
  clarificationRound: number;
  completedAgents: CompletedAgentActivity[];
  planningStartedAt: number | null;
  usage: UsageSummaryEvent | null;
  errorMessage: string | null;
  pdfError: string | null;
};

const initialState: TripPlannerState = {
  status: "idle",
  sessionId: null,
  itineraryId: null,
  prompt: "",
  itinerary: null,
  clarificationPrompts: [],
  clarificationRound: 0,
  completedAgents: [],
  planningStartedAt: null,
  usage: null,
  errorMessage: null,
  pdfError: null,
};

type Action =
  | { type: "prompt_submitted"; prompt: string }
  | { type: "clarification_submitted" }
  | { type: "stream_event"; event: TripStreamEvent }
  | { type: "stream_ended_unexpectedly" }
  | { type: "pdf_download_started" }
  | { type: "pdf_download_finished" }
  | { type: "pdf_download_failed"; message: string };

function reducer(state: TripPlannerState, action: Action): TripPlannerState {
  switch (action.type) {
    case "prompt_submitted":
      return {
        ...initialState,
        status: "planning",
        prompt: action.prompt,
        planningStartedAt: Date.now(),
      };

    case "clarification_submitted":
      return {
        ...state,
        status: "planning",
        clarificationPrompts: [],
      };

    case "stream_event":
      return applyStreamEvent(state, action.event);

    case "stream_ended_unexpectedly":
      if (state.status === "planning") {
        return { ...state, status: "error", errorMessage: "Connection closed unexpectedly." };
      }
      return state;

    case "pdf_download_started":
      return { ...state, status: "downloading", pdfError: null };

    case "pdf_download_finished":
      return { ...state, status: "complete" };

    case "pdf_download_failed":
      return { ...state, status: "complete", pdfError: action.message };

    default:
      return state;
  }
}

function applyStreamEvent(state: TripPlannerState, event: TripStreamEvent): TripPlannerState {
  switch (event.event) {
    case "agent_start": {
      const startedAt = state.planningStartedAt ?? Date.now();
      return { ...state, sessionId: event.data.session_id, planningStartedAt: startedAt };
    }

    case "agent_done": {
      const startedAt = state.planningStartedAt ?? Date.now();
      const entry: CompletedAgentActivity = {
        agent: event.data.agent,
        label: agentInfo(event.data.agent).label,
        preview: event.data.preview,
        layer: event.data.layer,
        elapsedMs: Date.now() - startedAt,
      };
      return {
        ...state,
        sessionId: event.data.session_id,
        completedAgents: [...state.completedAgents, entry],
      };
    }

    case "needs_clarification":
      return {
        ...state,
        status: "awaiting_clarification",
        sessionId: event.data.session_id,
        clarificationPrompts: event.data.prompts,
        clarificationRound: event.data.round,
      };

    case "complete":
      return {
        ...state,
        status: "complete",
        itineraryId: event.data.itinerary_id,
        sessionId: event.data.session_id,
        itinerary: event.data.itinerary,
      };

    case "usage_summary":
      return { ...state, usage: event.data };

    case "error":
      return { ...state, status: "error", errorMessage: event.data.message };

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

export function useTripPlanner() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const submitPrompt = useCallback((prompt: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    dispatch({ type: "prompt_submitted", prompt });

    void (async () => {
      try {
        const response = await planTrip({ query: prompt }, controller.signal);
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
  }, []);

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

  const downloadPdf = useCallback(async () => {
    if (!state.itineraryId) {
      return;
    }
    dispatch({ type: "pdf_download_started" });
    try {
      const { blob, filename } = await downloadItineraryPdf(state.itineraryId);
      triggerBrowserDownload(blob, filename);
      dispatch({ type: "pdf_download_finished" });
    } catch (error) {
      dispatch({ type: "pdf_download_failed", message: toErrorMessage(error) });
    }
  }, [state.itineraryId]);

  return { state, submitPrompt, submitClarification, downloadPdf };
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
