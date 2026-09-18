"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
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
  addSession: (session: SessionSummary) => void;
  updateSession: (sessionId: string, changes: Partial<SessionSummary>) => void;
  removeSession: (sessionId: string) => void;
};

const SessionsContext = createContext<SessionsContextValue | null>(null);

export function SessionsProvider({ children }: { children: ReactNode }) {
  const { username, mounted } = useCurrentUser();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const optimisticSessionsRef = useRef<SessionSummary[]>([]);
  const deletedSessionIdsRef = useRef<Set<string>>(new Set());

  const addSession = useCallback((session: SessionSummary) => {
    optimisticSessionsRef.current = [
      session,
      ...optimisticSessionsRef.current.filter(
        (existing) => existing.session_id !== session.session_id,
      ),
    ];
    setSessions((current) => {
      if (current.some((existing) => existing.session_id === session.session_id)) {
        return current;
      }
      return [session, ...current];
    });
  }, []);

  const updateSession = useCallback((sessionId: string, changes: Partial<SessionSummary>) => {
    const update = (session: SessionSummary): SessionSummary =>
      session.session_id === sessionId ? { ...session, ...changes } : session;

    optimisticSessionsRef.current = optimisticSessionsRef.current.map(update);
    setSessions((current) => current.map(update));
  }, []);

  const removeSession = useCallback((sessionId: string) => {
    deletedSessionIdsRef.current.add(sessionId);
    optimisticSessionsRef.current = optimisticSessionsRef.current.filter(
      (session) => session.session_id !== sessionId,
    );
    setSessions((current) => current.filter((session) => session.session_id !== sessionId));
  }, []);

  useEffect(() => {
    optimisticSessionsRef.current = [];
    deletedSessionIdsRef.current.clear();
  }, [username]);

  const refresh = useCallback(async () => {
    if (!username) {
      setSessions([]);
      return;
    }
    setLoading(true);
    try {
      const listedSessions = await listSessions(username);
      setSessions(mergeSessions(listedSessions, optimisticSessionsRef.current, deletedSessionIdsRef.current));
      optimisticSessionsRef.current = optimisticSessionsRef.current.filter(
        (optimistic) =>
          !listedSessions.some((listed) => listed.session_id === optimistic.session_id) &&
          !deletedSessionIdsRef.current.has(optimistic.session_id),
      );
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
          setSessions(mergeSessions(list, optimisticSessionsRef.current, deletedSessionIdsRef.current));
          optimisticSessionsRef.current = optimisticSessionsRef.current.filter(
            (optimistic) =>
              !list.some((listed) => listed.session_id === optimistic.session_id) &&
              !deletedSessionIdsRef.current.has(optimistic.session_id),
          );
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
    () => ({ sessions, loading, refresh, addSession, updateSession, removeSession }),
    [sessions, loading, refresh, addSession, updateSession, removeSession],
  );

  return <SessionsContext.Provider value={value}>{children}</SessionsContext.Provider>;
}

function mergeSessions(
  listedSessions: SessionSummary[],
  optimisticSessions: SessionSummary[],
  deletedSessionIds: Set<string>,
): SessionSummary[] {
  const visibleListedSessions = listedSessions.filter(
    (session) => !deletedSessionIds.has(session.session_id),
  );
  const listedIds = new Set(visibleListedSessions.map((session) => session.session_id));
  return [
    ...optimisticSessions.filter(
      (session) => !listedIds.has(session.session_id) && !deletedSessionIds.has(session.session_id),
    ),
    ...visibleListedSessions,
  ];
}

export function useSessions(): SessionsContextValue {
  const context = useContext(SessionsContext);
  if (!context) {
    throw new Error("useSessions must be used within a SessionsProvider");
  }
  return context;
}
