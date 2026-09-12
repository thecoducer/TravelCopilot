import { describe, expect, it } from "vitest";
import { activeAgentsFor, PLANNING_PHASES } from "@/lib/agent-catalog";

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
