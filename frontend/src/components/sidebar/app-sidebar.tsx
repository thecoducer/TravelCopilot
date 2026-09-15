"use client";

import { useMemo, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { MessageSquarePlus, MoreHorizontal, Moon, Sun, Trash2, Pencil, User, LogOut } from "lucide-react";
import { deleteSession, renameSession } from "@/lib/api";
import type { SessionSummary } from "@/lib/types";
import { groupSessions } from "@/lib/session-grouping";
import { cn } from "@/lib/utils";
import { useSessions } from "@/hooks/use-sessions";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useTheme } from "@/hooks/use-theme";
import { TravelCopilotLogo } from "@/components/brand/travel-copilot-logo";

export function AppSidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const { sessions, refresh } = useSessions();
  const { username, clearUsername } = useCurrentUser();
  const { theme, toggleTheme } = useTheme();
  const [query, setQuery] = useState("");

  const activeSessionId = pathname?.startsWith("/c/") ? pathname.slice(3) : null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((session) => session.title.toLowerCase().includes(q));
  }, [sessions, query]);

  const groups = useMemo(() => groupSessions(filtered), [filtered]);

  async function handleRename(session: SessionSummary) {
    const next = window.prompt("Rename chat", session.title);
    if (!next || !username) return;
    await renameSession(username, session.session_id, next.trim());
    await refresh();
  }

  async function handleDelete(session: SessionSummary) {
    if (!username || !window.confirm("Delete this chat?")) return;
    await deleteSession(username, session.session_id);
    if (activeSessionId === session.session_id) {
      router.push("/");
    }
    await refresh();
  }

  // The /c/{id} URL is set via window.history.replaceState (to keep the SSE
  // stream alive), which desyncs the App Router — so router.push("/") no-ops.
  // A full navigation is the only reliable way to start a clean chat.
  function startNewChat() {
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign("/");
  }

  function switchUser() {
    clearUsername();
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign("/");
  }

  return (
    <aside className="flex h-dvh w-[280px] flex-col border-r border-border bg-surface">
      <div className="flex flex-col gap-3 border-b border-border p-4">
        <TravelCopilotLogo />
        <button
          className="inline-flex items-center justify-center gap-2 rounded-md border border-border-strong bg-canvas px-3 py-2 text-sm font-semibold text-fg transition-colors hover:border-accent hover:bg-accent-soft"
          onClick={startNewChat}
        >
          <MessageSquarePlus size={16} />
          New chat
        </button>
        <input
          className="rounded-md border border-border bg-canvas px-3 py-2 text-sm text-fg outline-none focus:border-accent"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search chats"
          aria-label="Search chats"
        />
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Chat history">
        {groups.length === 0 ? (
          <p className="p-4 text-center text-sm text-faint">No chats yet. Start planning a trip.</p>
        ) : (
          groups.map((group) => (
            <div key={group.label} className="mb-4">
              <h2 className="mb-1 px-2 text-[0.7rem] font-semibold uppercase tracking-wider text-faint">
                {group.label}
              </h2>
              <ul className="flex flex-col gap-0.5">
                {group.sessions.map((session) => (
                  <SessionRow
                    key={session.session_id}
                    session={session}
                    active={activeSessionId === session.session_id}
                    onOpen={() => router.push(`/c/${session.session_id}`)}
                    onRename={() => handleRename(session)}
                    onDelete={() => handleDelete(session)}
                  />
                ))}
              </ul>
            </div>
          ))
        )}
      </nav>

      <div className="flex items-center gap-2 border-t border-border p-3">
        <button
          className="flex flex-1 items-center gap-2 rounded-md p-2 hover:bg-canvas"
          onClick={() => router.push("/profile")}
          aria-label="Open profile"
        >
          <span className="inline-flex size-7 items-center justify-center rounded-full bg-accent text-[0.85rem] font-bold text-white">
            {username ? username.charAt(0).toUpperCase() : <User size={16} />}
          </span>
          <span className="truncate text-[0.88rem] font-semibold text-fg">{username ?? "Guest"}</span>
        </button>
        <button
          className="inline-flex size-[34px] items-center justify-center rounded-md border border-border text-muted hover:bg-canvas hover:text-fg"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button
          className="inline-flex size-[34px] items-center justify-center rounded-md border border-border text-muted hover:bg-canvas hover:text-fg"
          onClick={switchUser}
          aria-label="Switch user"
          title="Switch user"
        >
          <LogOut size={16} />
        </button>
      </div>
    </aside>
  );
}

function SessionRow({
  session,
  active,
  onOpen,
  onRename,
  onDelete,
}: {
  session: SessionSummary;
  active: boolean;
  onOpen: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <li
      className={cn(
        "group relative flex items-center rounded-md hover:bg-canvas",
        active && "bg-accent-soft",
      )}
    >
      <button
        className="min-w-0 flex-1 truncate px-3 py-2 text-left text-[0.88rem] text-fg"
        onClick={onOpen}
        title={session.title}
      >
        {session.title}
      </button>
      <div className="relative">
        <button
          className={cn(
            "mr-1 inline-flex items-center justify-center rounded-sm p-1 text-muted opacity-0 hover:bg-border group-hover:opacity-100",
            active && "opacity-100",
          )}
          onClick={() => setMenuOpen((open) => !open)}
          aria-label="Chat options"
        >
          <MoreHorizontal size={16} />
        </button>
        {menuOpen ? (
          <>
            <div className="fixed inset-0 z-20" onClick={() => setMenuOpen(false)} />
            <div
              className="absolute right-0 top-full z-[21] min-w-[140px] rounded-md border border-border-strong bg-surface p-1 shadow-md"
              role="menu"
            >
              <button
                role="menuitem"
                className="flex w-full items-center gap-2 rounded-sm p-2 text-left text-sm text-fg hover:bg-canvas"
                onClick={() => {
                  setMenuOpen(false);
                  onRename();
                }}
              >
                <Pencil size={14} />
                Rename
              </button>
              <button
                role="menuitem"
                className="flex w-full items-center gap-2 rounded-sm p-2 text-left text-sm text-danger hover:bg-canvas"
                onClick={() => {
                  setMenuOpen(false);
                  onDelete();
                }}
              >
                <Trash2 size={14} />
                Delete
              </button>
            </div>
          </>
        ) : null}
      </div>
    </li>
  );
}
