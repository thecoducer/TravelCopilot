import type { SessionSummary } from "@/lib/types";

export type SessionGroup = { label: string; sessions: SessionSummary[] };

const DAY_MS = 86_400_000;

function calendarDayDifference(now: number, createdAt: string): number {
  const currentDate = new Date(now);
  const createdDate = new Date(createdAt);
  const currentDay = Date.UTC(
    currentDate.getFullYear(),
    currentDate.getMonth(),
    currentDate.getDate(),
  );
  const createdDay = Date.UTC(
    createdDate.getFullYear(),
    createdDate.getMonth(),
    createdDate.getDate(),
  );
  return Math.floor((currentDay - createdDay) / DAY_MS);
}

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
    const ageDays = calendarDayDifference(now, session.created_at);
    if (ageDays === 0) today.push(session);
    else if (ageDays === 1) yesterday.push(session);
    else if (ageDays >= 2 && ageDays <= 7) week.push(session);
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
