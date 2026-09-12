"use client";

import { SectionCard } from "@/components/ui/section-card";
import { Spinner } from "@/components/ui/spinner";
import { useElapsedTimer } from "@/hooks/use-elapsed-timer";
import { activeAgentsFor, agentInfo, PLANNING_PHASES } from "@/lib/agent-catalog";
import { formatElapsed } from "@/lib/format";
import type { CompletedAgentActivity, PlannerStatus } from "@/lib/types";
import styles from "./planning-activity.module.css";

type PlanningActivityProps = {
  status: PlannerStatus;
  completedAgents: CompletedAgentActivity[];
  planningStartedAt: number | null;
};

export function PlanningActivity({
  status,
  completedAgents,
  planningStartedAt,
}: PlanningActivityProps) {
  const isPlanning = status === "planning";
  const elapsedMs = useElapsedTimer(planningStartedAt, isPlanning);
  const completedIds = new Set(completedAgents.map((entry) => entry.agent));
  const activeAgents = isPlanning ? activeAgentsFor(completedIds) : [];
  const currentPhase = PLANNING_PHASES.find((phase) =>
    phase.agents.some((agent) => activeAgents.includes(agent)),
  );

  return (
    <SectionCard
      title="Activity and metrics"
      subtitle={
        isPlanning
          ? `${currentPhase?.name ?? "Planning"} · ${formatElapsed(elapsedMs)} elapsed`
          : `Finished in ${formatElapsed(elapsedMs)}`
      }
    >
      {isPlanning && activeAgents.length > 0 ? (
        <div className={styles.workingNow}>
          <h4 className={styles.sectionLabel}>Working now</h4>
          <ul className={styles.activeList}>
            {activeAgents.map((agent) => (
              <li key={agent} className={styles.activeItem}>
                <Spinner />
                <div>
                  <p className={styles.activeLabel}>{agentInfo(agent).label}</p>
                  <p className={styles.activeDescription}>{agentInfo(agent).description}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {completedAgents.length > 0 ? (
        <div className={styles.completed}>
          <h4 className={styles.sectionLabel}>Completed</h4>
          <ol className={styles.completedList}>
            {completedAgents.map((entry, index) => (
              <li key={`${entry.agent}-${index}`} className={styles.completedItem}>
                <span className={styles.completedLabel}>{entry.label}</span>
                <span className={styles.completedPreview}>{entry.preview}</span>
                <span className={styles.completedElapsed}>
                  +{formatElapsed(entry.elapsedMs)}
                </span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </SectionCard>
  );
}
