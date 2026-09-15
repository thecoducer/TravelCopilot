"use client";

import { useEffect, useRef } from "react";
import type { CSSProperties, Ref } from "react";
import { Check } from "lucide-react";
import { SectionCard } from "@/components/ui/section-card";
import { Spinner } from "@/components/ui/spinner";
import { useElapsedTimer } from "@/hooks/use-elapsed-timer";
import {
  activeAgentsFor,
  buildAgentTasks,
  PLANNING_PHASES,
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
};

export function PlanningActivity({
  status,
  completedAgents,
  planningStartedAt,
}: PlanningActivityProps) {
  const isPlanning = status === "planning";
  const isAwaitingClarification = status === "awaiting_clarification";
  const elapsedMs = useElapsedTimer(planningStartedAt, isPlanning);
  const completedIds = new Set(completedAgents.map((entry) => entry.agent));
  const activeAgents = isPlanning ? activeAgentsFor(completedIds) : [];
  const currentPhase = PLANNING_PHASES.find((phase) =>
    phase.agents.some((agent) => activeAgents.includes(agent)),
  );

  const tasks = buildAgentTasks(
    completedAgents,
    activeAgents,
    isPlanning || isAwaitingClarification,
  ).sort((left, right) => {
    const statusOrder = { done: 0, active: 1, pending: 2 };
    return statusOrder[left.status] - statusOrder[right.status];
  });
  const doneCount = tasks.filter((task) => task.status === "done").length;

  const subtitle = isPlanning
    ? `${currentPhase?.name ?? "Planning"} · ${formatElapsed(elapsedMs)} elapsed`
    : isAwaitingClarification
      ? "Planning is paused while we get a few details"
      : `${doneCount} step${doneCount === 1 ? "" : "s"} · finished in ${formatElapsed(elapsedMs)}`;

  return (
    <SectionCard
      title="Planning activity"
      subtitle={subtitle}
      actions={
        <span className="inline-flex items-baseline text-[0.9rem] font-bold tabular-nums text-fg">
          {doneCount}
          <span className="text-[0.78rem] font-semibold text-faint">/{tasks.length}</span>
        </span>
      }
    >
      <TaskTimeline tasks={tasks} />
    </SectionCard>
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
      className="flex min-w-0 max-h-[calc(3.25rem*var(--visible-tasks))] flex-col overflow-x-hidden overflow-y-auto"
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
  const isPending = task.status === "pending";
  return (
    <li
      ref={rowRef}
      className={cn(
        "grid min-w-0 grid-cols-[1.5rem_minmax(0,1fr)_auto] items-center gap-3 border-b border-border px-1 py-2 last:border-0",
        isActive && "-mx-2 rounded-md border-b-transparent px-2",
        isPending && "opacity-60",
      )}
    >
      <span
        className={cn(
          "inline-flex size-6 items-center justify-center rounded-full",
          task.status === "done" && "bg-success-soft",
        )}
        aria-hidden
      >
        {task.status === "done" ? (
          <Check className="size-3.5 text-success" strokeWidth={3} />
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
            isActive && "text-accent-hover",
            isPending && "font-medium text-muted",
          )}
        >
          {task.label}
        </p>
        <p className="mt-0.5 truncate text-[0.78rem] text-muted">
          {task.status === "done" && task.preview ? task.preview : task.description}
        </p>
      </div>

      {task.status === "done" && task.elapsedMs !== null ? (
        <span className="text-[0.78rem] tabular-nums text-faint">+{formatElapsed(task.elapsedMs)}</span>
      ) : isActive ? (
        <span className="text-[0.72rem] font-semibold uppercase tracking-wide text-accent">
          Working…
        </span>
      ) : null}
    </li>
  );
}
