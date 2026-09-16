import { describe, expect, it } from "vitest";
import { buildAgentTasks } from "@/lib/agent-catalog";

describe("buildAgentTasks", () => {
  const completed = [{ agent: "orchestrator", preview: "Delhi → Goa", elapsedMs: 1200 }];

  it("shows completed and active tasks while planning", () => {
    const tasks = buildAgentTasks(completed, ["stops_discovery"]);
    const byAgent = new Map(tasks.map((task) => [task.agent, task]));

    expect(byAgent.get("orchestrator")?.status).toBe("done");
    expect(byAgent.get("orchestrator")?.preview).toBe("Delhi → Goa");
    expect(byAgent.get("orchestrator")?.elapsedMs).toBe(1200);
    expect(byAgent.get("stops_discovery")?.status).toBe("active");
    expect(byAgent.has("visa")).toBe(false);
  });

  it("keeps the next task visible as paused during clarification", () => {
    const tasks = buildAgentTasks(completed, [], ["stops_discovery"]);
    const byAgent = new Map(tasks.map((task) => [task.agent, task]));

    expect(byAgent.get("orchestrator")?.status).toBe("done");
    expect(byAgent.get("stops_discovery")?.status).toBe("paused");
    expect(byAgent.has("itinerary_compiler")).toBe(false);
  });

  it("drops unreached pending tasks once planning stops", () => {
    const tasks = buildAgentTasks(completed, []);
    expect(tasks).toHaveLength(1);
    expect(tasks[0]?.agent).toBe("orchestrator");
    expect(tasks[0]?.status).toBe("done");
  });

  it("keeps every task in canonical pipeline order", () => {
    const tasks = buildAgentTasks(completed, ["stops_discovery"]);
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
    );

    expect(tasks.map((task) => task.agent)).toEqual(["orchestrator"]);
  });
});
