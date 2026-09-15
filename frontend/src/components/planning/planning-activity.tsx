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
import { formatElapsed, formatLatencyMs, formatTokenCount, formatUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { CompletedAgentActivity, PlannerStatus, UsageSummaryEvent } from "@/lib/types";

/** Rows kept visible in the timeline viewport; the rest scroll into view. */
const VISIBLE_TASKS = 5;

type PlanningActivityProps = {
  status: PlannerStatus;
  completedAgents: CompletedAgentActivity[];
  planningStartedAt: number | null;
  usage: UsageSummaryEvent | null;
};

export function PlanningActivity({
  status,
  completedAgents,
  planningStartedAt,
  usage,
}: PlanningActivityProps) {
  const isPlanning = status === "planning";
  const elapsedMs = useElapsedTimer(planningStartedAt, isPlanning);
  const completedIds = new Set(completedAgents.map((entry) => entry.agent));
  const activeAgents = isPlanning ? activeAgentsFor(completedIds) : [];
  const currentPhase = PLANNING_PHASES.find((phase) =>
    phase.agents.some((agent) => activeAgents.includes(agent)),
  );

  const tasks = buildAgentTasks(completedAgents, activeAgents, isPlanning);
  const doneCount = tasks.filter((task) => task.status === "done").length;

  const subtitle = isPlanning
    ? `${currentPhase?.name ?? "Planning"} · ${formatElapsed(elapsedMs)} elapsed`
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
      {usage ? <MetricsStrip usage={usage} /> : null}
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
      className="flex max-h-[calc(3.25rem*var(--visible-tasks))] flex-col overflow-y-auto"
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
        "grid grid-cols-[1.5rem_1fr_auto] items-center gap-3 border-b border-border px-1 py-2 last:border-0",
        isActive && "-mx-2 rounded-md border-b-transparent bg-accent-soft px-2",
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

function MetricsStrip({ usage }: { usage: UsageSummaryEvent }) {
  return (
    <dl className="mt-3 grid grid-cols-3 gap-2 border-t border-border pt-3">
      <Metric label="Tokens" value={formatTokenCount(usage.total_tokens)} />
      <Metric label="Cost" value={formatUsd(usage.total_cost_usd)} />
      <Metric label="LLM latency" value={formatLatencyMs(usage.total_latency_ms)} />
    </dl>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.7rem] uppercase tracking-wide text-faint">{label}</dt>
      <dd className="m-0 text-[0.9rem] font-semibold tabular-nums text-fg">{value}</dd>
    </div>
  );
}
