import type { SessionSummary } from "@/lib/types";

export type SessionGroup = { label: string; sessions: SessionSummary[] };

const DAY_MS = 86_400_000;

/** Buckets sessions into ChatGPT-style date groups, newest buckets first. */
export function groupSessions(
  sessions: SessionSummary[],
  now: number = Date.now(),
): SessionGroup[] {
  const today: SessionSummary[] = [];
  const yesterday: SessionSummary[] = [];
  const week: SessionSummary[] = [];
  const older: SessionSummary[] = [];

  for (const session of sessions) {
    const ageDays = (now - new Date(session.created_at).getTime()) / DAY_MS;
    if (ageDays < 1) today.push(session);
    else if (ageDays < 2) yesterday.push(session);
    else if (ageDays < 7) week.push(session);
    else older.push(session);
  }

  return (
    [
      { label: "Today", sessions: today },
      { label: "Yesterday", sessions: yesterday },
      { label: "Previous 7 days", sessions: week },
      { label: "Older", sessions: older },
    ] satisfies SessionGroup[]
  ).filter((group) => group.sessions.length > 0);
}
