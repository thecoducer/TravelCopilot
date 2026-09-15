"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { listSessions } from "@/lib/api";
import type { SessionSummary } from "@/lib/types";
import { useCurrentUser } from "@/hooks/use-current-user";

type SessionsContextValue = {
  sessions: SessionSummary[];
  loading: boolean;
  refresh: () => Promise<void>;
};

const SessionsContext = createContext<SessionsContextValue | null>(null);

export function SessionsProvider({ children }: { children: ReactNode }) {
  const { username, mounted } = useCurrentUser();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!username) {
      setSessions([]);
      return;
    }
    setLoading(true);
    try {
      setSessions(await listSessions(username));
    } catch {
      // Sidebar is non-critical; keep the last good list on failure.
    } finally {
      setLoading(false);
    }
  }, [username]);

  useEffect(() => {
    if (!mounted || !username) {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const list = await listSessions(username);
        if (!cancelled) {
          setSessions(list);
        }
      } catch {
        // Sidebar is non-critical.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mounted, username]);

  const value = useMemo(
    () => ({ sessions, loading, refresh }),
    [sessions, loading, refresh],
  );

  return <SessionsContext.Provider value={value}>{children}</SessionsContext.Provider>;
}

export function useSessions(): SessionsContextValue {
  const context = useContext(SessionsContext);
  if (!context) {
    throw new Error("useSessions must be used within a SessionsProvider");
  }
  return context;
}
