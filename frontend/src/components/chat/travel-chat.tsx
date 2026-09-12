"use client";

import { ChatComposer } from "@/components/chat/chat-composer";
import { EmptyState } from "@/components/chat/empty-state";
import { MessageBubble } from "@/components/chat/message-bubble";
import { ClarificationForm } from "@/components/clarification/clarification-form";
import { ItineraryResponse } from "@/components/itinerary/itinerary-response";
import { MetricsPanel } from "@/components/planning/metrics-panel";
import { PlanningActivity } from "@/components/planning/planning-activity";
import { ErrorBanner } from "@/components/ui/error-banner";
import { useTripPlanner } from "@/hooks/use-trip-planner";
import styles from "./travel-chat.module.css";

export function TravelChat() {
  const { state, submitPrompt, submitClarification, downloadPdf } = useTripPlanner();
  const hasStarted = state.status !== "idle";

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.brand}>Travel Copilot</span>
      </header>

      <div className={styles.conversation}>
        {hasStarted ? (
          <>
            <MessageBubble role="user">{state.prompt}</MessageBubble>
            <MessageBubble role="assistant">
              <div className={styles.assistantTurn}>
                {state.status === "error" && state.errorMessage ? (
                  <ErrorBanner message={state.errorMessage} />
                ) : null}

                <PlanningActivity
                  status={state.status}
                  completedAgents={state.completedAgents}
                  planningStartedAt={state.planningStartedAt}
                />

                {state.status === "awaiting_clarification" ? (
                  <ClarificationForm
                    prompts={state.clarificationPrompts}
                    onSubmit={submitClarification}
                  />
                ) : null}

                {state.itinerary ? (
                  <ItineraryResponse
                    itinerary={state.itinerary}
                    onDownloadPdf={downloadPdf}
                    isPdfDownloading={state.status === "downloading"}
                    pdfError={state.pdfError}
                  />
                ) : null}

                {state.itinerary ? <MetricsPanel usage={state.usage} /> : null}
              </div>
            </MessageBubble>
          </>
        ) : (
          <EmptyState onExampleClick={submitPrompt} />
        )}
      </div>

      <div className={styles.composerBar}>
        <ChatComposer onSend={submitPrompt} />
      </div>
    </div>
  );
}
