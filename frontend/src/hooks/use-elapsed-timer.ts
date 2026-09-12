import { useEffect, useState } from "react";

/**
 * Returns elapsed milliseconds since `startedAt`, ticking while `active` is
 * true. Stops updating (but keeps the last value) once `active` becomes false.
 */
export function useElapsedTimer(startedAt: number | null, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active || startedAt === null) {
      return;
    }
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [active, startedAt]);

  if (startedAt === null) {
    return 0;
  }
  return Math.max(0, now - startedAt);
}
