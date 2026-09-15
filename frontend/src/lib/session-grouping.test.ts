import { describe, expect, it } from "vitest";
import { groupSessions } from "@/lib/session-grouping";
import type { SessionSummary } from "@/lib/types";

function session(id: string, ageDays: number, now: number): SessionSummary {
  return {
    session_id: id,
    title: `Trip ${id}`,
    created_at: new Date(now - ageDays * 86_400_000).toISOString(),
    has_itinerary: true,
  };
}

describe("groupSessions", () => {
  const now = Date.UTC(2026, 0, 15, 12, 0, 0);

  it("buckets sessions by age into the expected labels", () => {
    const sessions = [
      session("a", 0.2, now),
      session("b", 1.5, now),
      session("c", 4, now),
      session("d", 30, now),
    ];
    const groups = groupSessions(sessions, now);
    expect(groups.map((group) => group.label)).toEqual([
      "Today",
      "Yesterday",
      "Previous 7 days",
      "Older",
    ]);
  });

  it("omits empty buckets", () => {
    const groups = groupSessions([session("a", 0.1, now)], now);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.label).toBe("Today");
  });

  it("returns nothing for an empty list", () => {
    expect(groupSessions([], now)).toEqual([]);
  });
});
