"use client";

import { useCallback } from "react";
import { ChatComposer } from "@/components/chat/chat-composer";
import { EmptyState } from "@/components/chat/empty-state";
import { MessageBubble } from "@/components/chat/message-bubble";
import { ClarificationForm } from "@/components/clarification/clarification-form";
import { ItineraryResponse } from "@/components/itinerary/itinerary-response";
import { MetricsPanel } from "@/components/planning/metrics-panel";
import { PlanningActivity } from "@/components/planning/planning-activity";
import { ErrorBanner } from "@/components/ui/error-banner";
import { useTripPlanner, type PlannerTurn } from "@/hooks/use-trip-planner";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useSessions } from "@/hooks/use-sessions";
import { renameSession } from "@/lib/api";
import type { SessionSummary } from "@/lib/types";

export function TravelChat({ initialSessionId }: { initialSessionId?: string }) {
  const { username } = useCurrentUser();
  const { addSession, refresh, updateSession } = useSessions();

  const onSessionCreated = useCallback(
    (sessionId: string, title: string, createdAt: string) => {
      // Shallow URL update keeps the component mounted (and the stream alive)
      // while giving the new chat a shareable /c/{id} address.
      if (!initialSessionId && typeof window !== "undefined") {
        window.history.replaceState(null, "", `/c/${sessionId}`);
      }
      const session: SessionSummary = {
        session_id: sessionId,
        title,
        created_at: createdAt,
        has_itinerary: false,
      };
      addSession(session);
      void refresh();
    },
    [addSession, initialSessionId, refresh],
  );

  const onItineraryTitle = useCallback(
    (sessionId: string, title: string) => {
      updateSession(sessionId, { title, has_itinerary: true });
      if (username) {
        void renameSession(username, sessionId, title).catch(() => undefined);
      }
    },
    [updateSession, username],
  );

  const { state, isHydrating, isBusy, submitPrompt, submitClarification, cancelPlanning, downloadPdf } = useTripPlanner({
    username,
    initialSessionId,
    onSessionCreated,
    onItineraryTitle,
  });

  const hasStarted = state.turns.length > 0;

  return (
    <div className="relative flex h-full flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto px-4 py-8 pb-32 [scrollbar-gutter:stable_both-edges] sm:px-8 sm:pb-36">
        <div className="mx-auto flex min-h-full w-full max-w-[1200px] flex-col gap-6">
          {isHydrating ? (
            <div className="flex min-h-full items-center justify-center py-12 text-sm text-muted" aria-live="polite">
              Loading trip…
            </div>
          ) : hasStarted ? (
            <>
              <ChatStartedAt timestamp={state.turns[0]?.startedAt} />
              {state.turns.map((turn, index) => (
                <TurnView
                  key={turn.id}
                  turn={turn}
                  isLatest={index === state.turns.length - 1}
                  isDownloading={state.isDownloading}
                  pdfError={state.pdfError}
                  onSubmitClarification={submitClarification}
                  onDownloadPdf={downloadPdf}
                />
              ))}
            </>
          ) : (
            <EmptyState />
          )}
        </div>
      </div>

      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-9 bg-gradient-to-t from-canvas/90 via-canvas/45 to-transparent sm:h-35"
        aria-hidden="true"
      />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 px-4 pb-4 sm:px-8 sm:pb-6">
        <div className="pointer-events-auto mx-auto w-full max-w-[900px]">
          <ChatComposer
            onSend={submitPrompt}
            onStop={cancelPlanning}
            disabled={isBusy}
            isBusy={isBusy}
            placeholder={hasStarted ? "Ask for a change to your trip…" : undefined}
          />
        </div>
      </div>
    </div>
  );
}

function ChatStartedAt({ timestamp }: { timestamp?: string }) {
  if (!timestamp) {
    return null;
  }

  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return (
    <div className="flex justify-center px-4 pb-4 pt-5 text-center">
      <p className="text-xs font-medium tracking-wide text-faint">
        {date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
      </p>
    </div>
  );
}

function TurnView({
  turn,
  isLatest,
  isDownloading,
  pdfError,
  onSubmitClarification,
  onDownloadPdf,
}: {
  turn: PlannerTurn;
  isLatest: boolean;
  isDownloading: boolean;
  pdfError: string | null;
  onSubmitClarification: (answers: Record<string, string>) => void;
  onDownloadPdf: (tripId: string) => void;
}) {
  const isPlanning = turn.status === "planning";

  return (
    <div className="flex w-full flex-col gap-8">
      {turn.prompt ? <MessageBubble role="user">{turn.prompt}</MessageBubble> : null}
      <MessageBubble role="assistant">
        <div className="flex w-full flex-col gap-4">
          {turn.status === "error" && turn.errorMessage ? (
            <ErrorBanner message={turn.errorMessage} />
          ) : null}

          {isPlanning || turn.status === "awaiting_clarification" || turn.completedAgents.length > 0 ? (
            <PlanningActivity
              status={turn.status}
              completedAgents={turn.completedAgents}
              activeAgents={turn.activeAgents}
              activeElapsedMs={turn.activeElapsedMs}
              runningSince={turn.runningSince}
              isDismissed={Boolean(turn.itinerary)}
            />
          ) : null}

          {turn.status === "awaiting_clarification" ? (
            <ClarificationForm
              key={turn.clarificationRequestId ?? turn.clarificationPrompts.map((prompt) => prompt.field).join("|")}
              prompts={turn.clarificationPrompts}
              onSubmit={onSubmitClarification}
            />
          ) : null}

          {turn.itinerary ? (
            isLatest ? (
              <div className="mt-8 flex flex-col gap-6">
                <ItineraryResponse
                  itinerary={turn.itinerary}
                  onDownloadPdf={() => turn.itineraryId && onDownloadPdf(turn.itineraryId)}
                  isPdfDownloading={isDownloading}
                  pdfError={pdfError}
                />
                <MetricsPanel usage={turn.usage} />
              </div>
            ) : (
              <details className="overflow-hidden rounded-lg border border-border bg-surface">
                <summary className="cursor-pointer list-none p-4 text-sm font-semibold text-muted [&::-webkit-details-marker]:hidden">
                  Earlier version — {turn.itinerary.title}
                </summary>
                <div className="border-t border-border p-4">
                  <ItineraryResponse
                    itinerary={turn.itinerary}
                    onDownloadPdf={() => turn.itineraryId && onDownloadPdf(turn.itineraryId)}
                    isPdfDownloading={isDownloading}
                    pdfError={pdfError}
                  />
                </div>
              </details>
            )
          ) : null}
        </div>
      </MessageBubble>
    </div>
  );
}
