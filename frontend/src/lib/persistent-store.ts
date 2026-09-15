"use client";

/**
 * A tiny localStorage-backed external store for use with useSyncExternalStore.
 * Reading browser storage this way avoids setState-in-effect hydration hacks.
 */

type Listener = () => void;

export type PersistentStore = {
  subscribe: (listener: Listener) => () => void;
  getSnapshot: () => string | null;
  getServerSnapshot: () => null;
  set: (value: string) => void;
  clear: () => void;
};

export function createPersistentStore(key: string): PersistentStore {
  const listeners = new Set<Listener>();

  function read(): string | null {
    if (typeof window === "undefined") {
      return null;
    }
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function emit(): void {
    for (const listener of listeners) {
      listener();
    }
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      if (typeof window !== "undefined") {
        window.addEventListener("storage", listener);
      }
      return () => {
        listeners.delete(listener);
        if (typeof window !== "undefined") {
          window.removeEventListener("storage", listener);
        }
      };
    },
    getSnapshot: read,
    getServerSnapshot: () => null,
    set(value) {
      try {
        window.localStorage.setItem(key, value);
      } catch {
        // Ignore quota / privacy-mode failures.
      }
      emit();
    },
    clear() {
      try {
        window.localStorage.removeItem(key);
      } catch {
        // Ignore.
      }
      emit();
    },
  };
}

/** True only after client hydration — a lint-clean replacement for a mounted flag. */
export const mountedStore = {
  subscribe: () => () => {},
  getSnapshot: () => true,
  getServerSnapshot: () => false,
};
