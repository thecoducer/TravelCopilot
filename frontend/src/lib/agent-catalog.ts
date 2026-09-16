/**
 * Static catalog of graph nodes shown to the user, and the phase grouping used
 * to infer which agents are currently active (the backend does not yet emit a
 * per-node `agent_start`, so "in progress" is derived from graph topology plus
 * the `agent_done` events actually received).
 */

export type AgentInfo = {
  label: string;
  description: string;
};

export const AGENT_CATALOG: Record<string, AgentInfo> = {
  orchestrator: {
    label: "Understanding your request",
    description: "Extracting the essentials from your request",
  },
  stops_discovery: {
    label: "Building the route",
    description: "Working out the stops and legs of your trip",
  },
  visa: {
    label: "Checking visa requirements",
    description: "Looking up visa rules for your route",
  },
  transport_search: {
    label: "Searching transport options",
    description: "Looking for flights, trains, and transit routes",
  },
  stay_search: {
    label: "Finding places to stay",
    description: "Gathering stays that fit your trip",
  },
  local_experiences: {
    label: "Finding things to do",
    description: "Discovering attractions and local experiences",
  },
  transport_optimizer: {
    label: "Optimizing your route",
    description: "Weighing transport options against each other",
  },
  stay_analyst: {
    label: "Ranking your stay options",
    description: "Shortlisting the best places to stay",
  },
  self_drive_search: {
    label: "Checking self-drive options",
    description: "Looking into rentals and driving routes",
  },
  reviews: {
    label: "Reading traveler reviews",
    description: "Summarizing reviews for top picks",
  },
  food_discovery: {
    label: "Finding great food",
    description: "Looking for restaurants and local food",
  },
  budget_planner: {
    label: "Balancing the budget",
    description: "Adding up costs and checking them against your budget",
  },
  safety: {
    label: "Checking safety and local conditions",
    description: "Reviewing safety notes and local conditions",
  },
  itinerary_compiler: {
    label: "Assembling the itinerary",
    description: "Putting the full itinerary together",
  }
};

export type PlanningPhase = {
  id: number;
  name: string;
  agents: string[];
};

/** Ordered phases mirroring the graph's actual execution layers. */
export const PLANNING_PHASES: PlanningPhase[] = [
  { id: 0, name: "Understanding your trip", agents: ["orchestrator"] },
  { id: 1, name: "Building the route", agents: ["stops_discovery"] },
  { id: 2, name: "Checking destination details", agents: ["visa"] },
  {
    id: 3,
    name: "Searching options",
    agents: ["transport_search", "stay_search", "local_experiences"],
  },
  {
    id: 4,
    name: "Comparing and ranking",
    agents: ["transport_optimizer", "stay_analyst", "self_drive_search"],
  },
  {
    id: 5,
    name: "Finalizing details",
    agents: ["reviews", "food_discovery", "budget_planner", "safety"],
  },
  { id: 6, name: "Assembling the itinerary", agents: ["itinerary_compiler"] },
];

export function agentInfo(agent: string): AgentInfo {
  return (
    AGENT_CATALOG[agent] ?? {
      label: titleizeAgentId(agent),
      description: "Working on your trip",
    }
  );
}

export function titleizeAgentId(agent: string): string {
  return agent
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/** Agents from the current phase that have not yet posted `agent_done`. */
export function activeAgentsFor(completedAgents: ReadonlySet<string>): string[] {
  for (const phase of PLANNING_PHASES) {
    const pending = phase.agents.filter((agent) => !completedAgents.has(agent));
    if (pending.length > 0) {
      return pending;
    }
  }
  return [];
}

/** Canonical execution order of every agent shown in the task timeline. */
export const AGENT_PIPELINE: string[] = PLANNING_PHASES.flatMap((phase) => phase.agents);

export type AgentTaskStatus = "done" | "active" | "paused" | "pending";

export type AgentTask = {
  agent: string;
  label: string;
  description: string;
  status: AgentTaskStatus;
  preview: string | null;
  elapsedMs: number | null;
};

type CompletedAgentSummary = {
  agent: string;
  preview: string;
  elapsedMs: number;
};

/**
 * Builds the ordered todo-style task list for the timeline from the allowlisted
 * pipeline agents, tagged done / active / pending.
 * Once planning stops, unreached pipeline agents are dropped so the list shows
 * only what actually ran.
 */
export function buildAgentTasks(
  completed: readonly CompletedAgentSummary[],
  activeAgents: readonly string[],
  isPlanning: boolean,
  pausedAgents: readonly string[] = [],
): AgentTask[] {
  const completedByAgent = new Map(completed.map((entry) => [entry.agent, entry]));
  const activeSet = new Set(activeAgents);
  const pausedSet = new Set(pausedAgents);
  const ordered = AGENT_PIPELINE;

  const tasks: AgentTask[] = [];
  const seen = new Set<string>();
  for (const agent of ordered) {
    if (seen.has(agent)) {
      continue;
    }
    seen.add(agent);

    const done = completedByAgent.get(agent);
    const status: AgentTaskStatus = done
      ? "done"
      : activeSet.has(agent)
        ? "active"
        : pausedSet.has(agent)
          ? "paused"
        : "pending";

    if (status === "pending") {
      continue;
    }

    const info = agentInfo(agent);
    tasks.push({
      agent,
      label: info.label,
      description: info.description,
      status,
      preview: done?.preview ?? null,
      elapsedMs: done?.elapsedMs ?? null,
    });
  }
  return tasks;
}
