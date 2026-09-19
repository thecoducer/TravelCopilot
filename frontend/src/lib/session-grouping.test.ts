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

function sessionAt(id: string, createdAt: string): SessionSummary {
  return {
    session_id: id,
    title: `Trip ${id}`,
    created_at: createdAt,
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

  it("uses calendar dates at midnight boundaries", () => {
    const now = new Date(2026, 8, 19, 0, 1, 0).getTime();
    const groups = groupSessions(
      [sessionAt("yesterday", new Date(2026, 8, 18, 23, 59, 0).toISOString())],
      now,
    );

    expect(groups.map((group) => group.label)).toEqual(["Yesterday"]);
    expect(groups[0]?.sessions[0]?.session_id).toBe("yesterday");
  });

  it("returns nothing for an empty list", () => {
    expect(groupSessions([], now)).toEqual([]);
  });
});
