import { useEffect, useState } from "react";

/**
 * Returns `baseMs` plus time elapsed since `runningSince`, ticking while it is
 * set. Frozen at `baseMs` while `runningSince` is `null` (e.g. paused for a
 * clarification prompt), so paused time is never counted as elapsed.
 */
export function useElapsedTimer(baseMs: number, runningSince: number | null): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (runningSince === null) {
      return;
    }
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [runningSince]);

  if (runningSince === null) {
    return baseMs;
  }
  return baseMs + Math.max(0, now - runningSince);
}
