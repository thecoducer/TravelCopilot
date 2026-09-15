"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { createPersistentStore, mountedStore } from "@/lib/persistent-store";

const usernameStore = createPersistentStore("travelcopilot.username");

type UserContextValue = {
  username: string | null;
  /** False until the first client-side render resolves the stored username. */
  mounted: boolean;
  setUsername: (username: string) => void;
  clearUsername: () => void;
};

const UserContext = createContext<UserContextValue | null>(null);

export function UserProvider({ children }: { children: ReactNode }) {
  const username = useSyncExternalStore(
    usernameStore.subscribe,
    usernameStore.getSnapshot,
    usernameStore.getServerSnapshot,
  );
  const mounted = useSyncExternalStore(
    mountedStore.subscribe,
    mountedStore.getSnapshot,
    mountedStore.getServerSnapshot,
  );

  const setUsername = useCallback((next: string) => {
    usernameStore.set(next);
  }, []);

  const clearUsername = useCallback(() => {
    usernameStore.clear();
  }, []);

  const value = useMemo(
    () => ({ username, mounted, setUsername, clearUsername }),
    [username, mounted, setUsername, clearUsername],
  );

  return <UserContext.Provider value={value}>{children}</UserContext.Provider>;
}

export function useCurrentUser(): UserContextValue {
  const context = useContext(UserContext);
  if (!context) {
    throw new Error("useCurrentUser must be used within a UserProvider");
  }
  return context;
}
