"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useRouter, usePathname } from "next/navigation";
import {
  LogOut,
  History,
  MessageSquarePlus,
  MoreHorizontal,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Search,
  Sun,
  Trash2,
  User,
  X,
} from "lucide-react";
import { deleteSession, renameSession } from "@/lib/api";
import type { SessionSummary } from "@/lib/types";
import { groupSessions } from "@/lib/session-grouping";
import { cn } from "@/lib/utils";
import { useSessions } from "@/hooks/use-sessions";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useTheme } from "@/hooks/use-theme";
import { TravelCopilotLogo } from "@/components/brand/travel-copilot-logo";

export function AppSidebar({
  collapsed = false,
  onHide,
  onShow,
}: {
  collapsed?: boolean;
  onHide: () => void;
  onShow: () => void;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { sessions, refresh } = useSessions();
  const { username, clearUsername } = useCurrentUser();
  const { theme, toggleTheme } = useTheme();
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);

  const activeSessionId = pathname?.startsWith("/c/") ? pathname.slice(3) : null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((session) => session.title.toLowerCase().includes(q));
  }, [sessions, query]);

  const groups = useMemo(() => groupSessions(filtered), [filtered]);

  useEffect(() => {
    if (!searchOpen) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setSearchOpen(false);
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [searchOpen]);

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

  function startNewChat() {
    router.push("/");
  }

  function switchUser() {
    clearUsername();
    router.push("/");
  }

  function openSession(sessionId: string) {
    setSearchOpen(false);
    router.push(`/c/${sessionId}`);
  }

  if (collapsed) {
    return (
      <aside className="group relative flex h-dvh w-full flex-col items-center border-r border-white/[0.08] bg-black py-4 text-white">
        <div className="relative mb-5 size-9">
          <TravelCopilotLogo
            showWordmark={false}
            className="absolute inset-0 transition-[opacity,transform] duration-300 ease-out group-hover:scale-95 group-hover:opacity-0"
          />
          <RailButton
            icon={<PanelLeftOpen size={18} />}
            label="Expand sidebar"
            onClick={onShow}
            className="absolute inset-0 opacity-0 transition-[opacity,transform] duration-300 ease-out group-hover:scale-100 group-hover:opacity-100"
          />
        </div>
        <div className="flex flex-col items-center gap-3">
          <RailButton icon={<MessageSquarePlus size={18} />} label="New chat" onClick={startNewChat} />
          <RailButton icon={<History size={18} />} label="Recent chats" onClick={onShow} />
          <RailButton icon={<Search size={18} />} label="Search chats" onClick={() => setSearchOpen(true)} />
        </div>
        <div className="mt-auto flex flex-col items-center gap-3">
          <button
            className="inline-flex size-7 items-center justify-center rounded-full bg-[#9b59b6] text-[0.65rem] font-bold text-white transition-transform hover:scale-105"
            onClick={() => router.push("/profile")}
            aria-label="Open profile"
            title="Open profile"
          >
            {username ? username.charAt(0).toUpperCase() : <User size={14} />}
          </button>
        </div>
        {searchOpen ? (
          <SearchDialog
            query={query}
            results={filtered}
            onQueryChange={setQuery}
            onClose={() => setSearchOpen(false)}
            onOpen={openSession}
          />
        ) : null}
      </aside>
    );
  }

  return (
    <aside className="relative flex h-dvh w-full flex-col border-r border-white/[0.08] bg-black text-white">
      <div className="flex items-center justify-between px-4 pb-4 pt-5">
        <TravelCopilotLogo className="[&>span]:text-white" />
        <div className="flex items-center gap-1">
          <button
            className="inline-flex size-8 items-center justify-center rounded-md text-white/70 transition-colors hover:bg-white/10 hover:text-white"
            onClick={() => setSearchOpen(true)}
            aria-label="Search chats"
            title="Search chats"
          >
            <Search size={18} />
          </button>
          <button
            className="inline-flex size-8 items-center justify-center rounded-md text-white/70 transition-colors hover:bg-white/10 hover:text-white"
            onClick={onHide}
            aria-label="Hide sidebar"
            title="Hide sidebar"
          >
            <PanelLeftClose size={18} />
          </button>
        </div>
      </div>
      <div className="px-3 pb-4 pt-3">
        <button
          className="group inline-flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[0.85rem] font-semibold text-white transition-colors hover:bg-white/[0.1]"
          onClick={startNewChat}
        >
          <span className="inline-flex size-6 items-center justify-center rounded-md bg-white text-black transition-transform group-hover:scale-105">
            <MessageSquarePlus size={15} />
          </span>
          New chat
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-2" aria-label="Chat history">
        {groups.length === 0 ? (
          <p className="p-4 text-center text-sm text-white/45">No chats yet. Start planning a trip.</p>
        ) : (
          groups.map((group) => (
            <div key={group.label} className="mb-4">
              <h2 className="mb-1 px-3 text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-white/35">
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

      <div className="flex items-center gap-2 border-t border-white/10 p-3">
        <button
          className="flex flex-1 items-center gap-2 rounded-lg p-2 text-left hover:bg-white/10"
          onClick={() => router.push("/profile")}
          aria-label="Open profile"
        >
          <span className="inline-flex size-7 items-center justify-center rounded-full bg-[#9b59b6] text-[0.72rem] font-bold text-white">
            {username ? username.charAt(0).toUpperCase() : <User size={16} />}
          </span>
          <span className="min-w-0 truncate text-[0.84rem] font-semibold text-white">{username ?? "Guest"}</span>
        </button>
        <button
          className="inline-flex size-[32px] items-center justify-center rounded-md text-white/55 hover:bg-white/10 hover:text-white"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button
          className="inline-flex size-[32px] items-center justify-center rounded-md text-white/55 hover:bg-white/10 hover:text-white"
          onClick={switchUser}
          aria-label="Switch user"
          title="Switch user"
        >
          <LogOut size={16} />
        </button>
      </div>
      {searchOpen ? (
        <SearchDialog
          query={query}
          results={filtered}
          onQueryChange={setQuery}
          onClose={() => setSearchOpen(false)}
          onOpen={openSession}
        />
      ) : null}
    </aside>
  );
}

function RailButton({
  icon,
  label,
  onClick,
  className,
}: {
  icon: ReactNode;
  label: string;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      className={`inline-flex size-9 items-center justify-center rounded-lg text-white/75 transition-colors hover:bg-white/10 hover:text-white ${className ?? ""}`}
      onClick={onClick}
      aria-label={label}
      title={label}
    >
      {icon}
    </button>
  );
}

function SearchDialog({
  query,
  results,
  onQueryChange,
  onClose,
  onOpen,
}: {
  query: string;
  results: SessionSummary[];
  onQueryChange: (query: string) => void;
  onClose: () => void;
  onOpen: (sessionId: string) => void;
}) {
  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-black/60 px-4 pt-[12vh]" onMouseDown={onClose}>
      <div
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-white/10 bg-black shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label="Search chats"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-white/10 px-4">
          <Search size={19} className="shrink-0 text-white/50" />
          <input
            autoFocus
            className="h-14 min-w-0 flex-1 bg-transparent text-[0.95rem] text-white outline-none placeholder:text-white/40"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Search chats"
            aria-label="Search chats"
          />
          <button
            className="inline-flex size-7 items-center justify-center rounded-md text-white/50 hover:bg-white/10 hover:text-white"
            onClick={onClose}
            aria-label="Close search"
          >
            <X size={17} />
          </button>
        </div>
        <div className="max-h-[min(55vh,420px)] overflow-y-auto p-2">
          {results.length === 0 ? (
            <p className="px-3 py-8 text-center text-sm text-white/45">No matching chats</p>
          ) : (
            results.slice(0, 12).map((session) => (
              <button
                key={session.session_id}
                className="flex w-full items-center rounded-lg px-3 py-3 text-left text-sm text-white transition-colors hover:bg-white/10"
                onClick={() => onOpen(session.session_id)}
              >
                <span className="min-w-0 flex-1 truncate">{session.title}</span>
                <span className="ml-4 shrink-0 text-xs text-white/35">
                  {new Date(session.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
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
        "group relative flex items-center rounded-lg transition-colors hover:bg-white/10",
        active && "bg-white/15 shadow-sm",
      )}
    >
      <button
        className="min-w-0 flex-1 truncate px-3 py-2 text-left text-[0.82rem] text-white/90"
        onClick={onOpen}
        title={session.title}
      >
        {session.title}
      </button>
      <div className="relative">
        <button
          className={cn(
            "mr-1 inline-flex items-center justify-center rounded-sm p-1 text-white/60 opacity-0 hover:bg-white/10 group-hover:opacity-100",
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
              className="absolute right-0 top-full z-[21] min-w-[140px] rounded-md border border-white/10 bg-[#1e2226] p-1 shadow-md"
              role="menu"
            >
              <button
                role="menuitem"
                className="flex w-full items-center gap-2 rounded-sm p-2 text-left text-sm text-white hover:bg-white/10"
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
                className="flex w-full items-center gap-2 rounded-sm p-2 text-left text-sm text-red-300 hover:bg-white/10"
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
