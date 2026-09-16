import { describe, expect, it } from "vitest";
import { activeAgentsFor, buildAgentTasks, PLANNING_PHASES } from "@/lib/agent-catalog";

describe("activeAgentsFor", () => {
  it("returns the first phase's agents when nothing has completed", () => {
    expect(activeAgentsFor(new Set())).toEqual(["orchestrator"]);
  });

  it("shows parallel agents in the same phase together", () => {
    const completed = new Set(["orchestrator", "stops_discovery", "visa"]);
    const searchPhase = PLANNING_PHASES.find((phase) => phase.name === "Searching options");
    expect(activeAgentsFor(completed)).toEqual(searchPhase?.agents);
  });

  it("removes only the agents that have completed within a phase", () => {
    const completed = new Set([
      "orchestrator",
      "stops_discovery",
      "visa",
      "transport_search",
    ]);
    expect(activeAgentsFor(completed)).toEqual(["stay_search", "local_experiences"]);
  });

  it("returns an empty list once every phase has completed", () => {
    const allAgents = PLANNING_PHASES.flatMap((phase) => phase.agents);
    expect(activeAgentsFor(new Set(allAgents))).toEqual([]);
  });
});

describe("buildAgentTasks", () => {
  const completed = [{ agent: "orchestrator", preview: "Delhi → Goa", elapsedMs: 1200 }];

  it("shows completed and active tasks while planning", () => {
    const tasks = buildAgentTasks(completed, ["stops_discovery"], true);
    const byAgent = new Map(tasks.map((task) => [task.agent, task]));

    expect(byAgent.get("orchestrator")?.status).toBe("done");
    expect(byAgent.get("orchestrator")?.preview).toBe("Delhi → Goa");
    expect(byAgent.get("orchestrator")?.elapsedMs).toBe(1200);
    expect(byAgent.get("stops_discovery")?.status).toBe("active");
    expect(byAgent.has("visa")).toBe(false);
  });

  it("keeps the next task visible as paused during clarification", () => {
    const tasks = buildAgentTasks(completed, [], true, ["stops_discovery"]);
    const byAgent = new Map(tasks.map((task) => [task.agent, task]));

    expect(byAgent.get("orchestrator")?.status).toBe("done");
    expect(byAgent.get("stops_discovery")?.status).toBe("paused");
    expect(byAgent.has("itinerary_compiler")).toBe(false);
  });

  it("drops unreached pending tasks once planning stops", () => {
    const tasks = buildAgentTasks(completed, [], false);
    expect(tasks).toHaveLength(1);
    expect(tasks[0]?.agent).toBe("orchestrator");
    expect(tasks[0]?.status).toBe("done");
  });

  it("keeps every task in canonical pipeline order", () => {
    const tasks = buildAgentTasks(completed, ["stops_discovery"], true);
    const order = tasks.map((task) => task.agent);
    expect(order.indexOf("orchestrator")).toBeLessThan(order.indexOf("stops_discovery"));
    expect(order).toEqual(["orchestrator", "stops_discovery"]);
  });

  it("hides clarification and metadata events from the activity list", () => {
    const tasks = buildAgentTasks(
      [
        ...completed,
        { agent: "orchestrator_clarification", preview: "Done", elapsedMs: 100 },
        { agent: "optional_clarification", preview: "Done", elapsedMs: 100 },
        { agent: "metadata", preview: "Done", elapsedMs: 100 },
      ],
      [],
      false,
    );

    expect(tasks.map((task) => task.agent)).toEqual(["orchestrator"]);
  });
});
