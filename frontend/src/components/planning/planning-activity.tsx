"use client";

import { useEffect, useRef } from "react";
import type { CSSProperties, Ref } from "react";
import { Check, Pause } from "lucide-react";
import { SectionCard } from "@/components/ui/section-card";
import { Spinner } from "@/components/ui/spinner";
import { useElapsedTimer } from "@/hooks/use-elapsed-timer";
import {
  activeAgentsFor,
  AGENT_PIPELINE,
  buildAgentTasks,
  type AgentTask,
} from "@/lib/agent-catalog";
import { formatElapsed } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { CompletedAgentActivity, PlannerStatus } from "@/lib/types";

/** Rows kept visible in the timeline viewport; the rest scroll into view. */
const VISIBLE_TASKS = 5;

type PlanningActivityProps = {
  status: PlannerStatus;
  completedAgents: CompletedAgentActivity[];
  planningStartedAt: number | null;
  isDismissed?: boolean;
};

export function PlanningActivity({
  status,
  completedAgents,
  planningStartedAt,
  isDismissed = false,
}: PlanningActivityProps) {
  const isPlanning = status === "planning";
  const isAwaitingClarification = status === "awaiting_clarification";
  const elapsedMs = useElapsedTimer(planningStartedAt, isPlanning);
  const completedIds = new Set(completedAgents.map((entry) => entry.agent));
  const currentAgents = activeAgentsFor(completedIds);
  const activeAgents = isPlanning ? currentAgents : [];

  const tasks = buildAgentTasks(
    completedAgents,
    activeAgents,
    isPlanning || isAwaitingClarification,
    isAwaitingClarification ? currentAgents : [],
  ).sort((left, right) => {
    const statusOrder = { done: 0, active: 1, paused: 1, pending: 2 };
    return statusOrder[left.status] - statusOrder[right.status];
  });
  const doneCount = tasks.filter((task) => task.status === "done").length;

  const elapsedLabel = `${formatElapsed(elapsedMs)} elapsed`;

  return (
    <div
      className={cn(
        "overflow-hidden transition-[max-height,opacity] duration-250 ease-out",
        isDismissed ? "pointer-events-none max-h-0 opacity-0" : "max-h-[48rem] opacity-100",
      )}
    >
      <SectionCard
        flat
        headerContent={
          <div className="flex w-full items-center justify-between gap-4">
            <span className="font-mono text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-muted">
              {doneCount}/{AGENT_PIPELINE.length} complete
            </span>
            <span className="text-[0.78rem] text-muted">{elapsedLabel}</span>
          </div>
        }
      >
        <TaskTimeline tasks={tasks} />
      </SectionCard>
    </div>
  );
}

function TaskTimeline({ tasks }: { tasks: AgentTask[] }) {
  const activeRef = useRef<HTMLLIElement>(null);
  const activeAgent = tasks.find((task) => task.status === "active")?.agent ?? null;

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeAgent]);

  if (tasks.length === 0) {
    return null;
  }

  return (
    <ol
      className="flex min-w-0 max-h-[calc(4.5rem*var(--visible-tasks))] flex-col gap-1 overflow-x-hidden overflow-y-auto pr-1"
      style={{ "--visible-tasks": VISIBLE_TASKS } as CSSProperties}
      aria-label="Agent tasks"
    >
      {tasks.map((task) => (
        <TaskRow
          key={task.agent}
          task={task}
          rowRef={task.agent === activeAgent ? activeRef : undefined}
        />
      ))}
    </ol>
  );
}

function TaskRow({ task, rowRef }: { task: AgentTask; rowRef?: Ref<HTMLLIElement> }) {
  const isActive = task.status === "active";
  return (
    <li
      ref={rowRef}
      className={cn(
        "grid min-w-0 grid-cols-[1.75rem_minmax(0,1fr)_auto] items-center gap-3 px-2 py-3",
      )}
    >
      <span
        className={cn(
          "inline-flex size-7 items-center justify-center rounded-full",
          task.status === "done" && "bg-accent-soft text-success",
          !isActive && task.status !== "done" && task.status !== "paused" && "border border-border-strong",
        )}
        aria-hidden
      >
        {task.status === "done" ? (
          <Check className="size-3.5" strokeWidth={2.5} />
        ) : task.status === "paused" ? (
          <Pause className="size-3.5 text-muted" strokeWidth={2.5} />
        ) : isActive ? (
          <Spinner label="" />
        ) : (
          <span className="size-2.5 rounded-full border-2 border-border-strong" />
        )}
      </span>

      <div className="min-w-0">
        <p
          className={cn(
            "text-[0.88rem] font-semibold text-fg",
            (isActive || task.status === "paused") && "text-accent-hover",
          )}
        >
          {task.label}
        </p>
        <p className="mt-0.5 truncate text-[0.78rem] text-muted">
          {task.status === "done" && task.preview ? task.preview : task.description}
        </p>
      </div>

      {task.status === "done" && task.elapsedMs !== null ? (
        <span className="font-mono text-[0.68rem] tabular-nums text-faint">+{formatElapsed(task.elapsedMs)}</span>
      ) : isActive ? (
        <span className="font-mono text-[0.68rem] font-semibold uppercase tracking-[0.1em] text-accent-hover">
          Working
        </span>
      ) : task.status === "paused" ? (
        <span className="font-mono text-[0.68rem] font-semibold uppercase tracking-[0.1em] text-muted">
          Paused
        </span>
      ) : null}
    </li>
  );
}
