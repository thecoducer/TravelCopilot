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

export function TravelChat({ initialSessionId }: { initialSessionId?: string }) {
  const { username } = useCurrentUser();
  const { refresh } = useSessions();

  const onSessionCreated = useCallback(
    (sessionId: string) => {
      // Shallow URL update keeps the component mounted (and the stream alive)
      // while giving the new chat a shareable /c/{id} address.
      if (!initialSessionId && typeof window !== "undefined") {
        window.history.replaceState(null, "", `/c/${sessionId}`);
      }
      void refresh();
    },
    [initialSessionId, refresh],
  );

  const { state, isBusy, submitPrompt, submitClarification, downloadPdf } = useTripPlanner({
    username,
    initialSessionId,
    onSessionCreated,
  });

  const hasStarted = state.turns.length > 0;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto px-3 py-6 [scrollbar-gutter:stable] sm:px-6">
        <div className="mx-auto flex min-h-full w-full max-w-[1120px] flex-col gap-4">
          {hasStarted ? (
            state.turns.map((turn, index) => (
              <TurnView
                key={turn.id}
                turn={turn}
                isLatest={index === state.turns.length - 1}
                isDownloading={state.isDownloading}
                pdfError={state.pdfError}
                onSubmitClarification={submitClarification}
                onDownloadPdf={downloadPdf}
              />
            ))
          ) : (
            <EmptyState onExampleClick={submitPrompt} />
          )}
        </div>
      </div>

      <div className="shrink-0 border-t border-border bg-canvas p-4">
        <div className="mx-auto max-w-[1120px]">
          <ChatComposer
            onSend={submitPrompt}
            disabled={isBusy}
            placeholder={hasStarted ? "Ask for a change to your trip…" : undefined}
          />
        </div>
      </div>
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
    <div className="flex w-full flex-col gap-4">
      {turn.prompt ? <MessageBubble role="user">{turn.prompt}</MessageBubble> : null}
      <MessageBubble role="assistant">
        <div className="flex w-full flex-col gap-4">
          {turn.status === "error" && turn.errorMessage ? (
            <ErrorBanner message={turn.errorMessage} />
          ) : null}

          {isPlanning || turn.completedAgents.length > 0 ? (
            <PlanningActivity
              status={isPlanning ? "planning" : "complete"}
              completedAgents={turn.completedAgents}
              planningStartedAt={turn.planningStartedAt}
              usage={turn.usage}
            />
          ) : null}

          {turn.status === "awaiting_clarification" ? (
            <ClarificationForm
              prompts={turn.clarificationPrompts}
              onSubmit={onSubmitClarification}
            />
          ) : null}

          {turn.itinerary ? (
            isLatest ? (
              <>
                <ItineraryResponse
                  itinerary={turn.itinerary}
                  onDownloadPdf={() => turn.itineraryId && onDownloadPdf(turn.itineraryId)}
                  isPdfDownloading={isDownloading}
                  pdfError={pdfError}
                />
                <MetricsPanel usage={turn.usage} />
              </>
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
