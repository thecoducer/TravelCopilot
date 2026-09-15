"use client";

import { useState, type ReactNode } from "react";
import { Menu } from "lucide-react";
import { AppSidebar } from "@/components/sidebar/app-sidebar";
import { UsernameDialog } from "@/components/onboarding/username-dialog";
import { useCurrentUser } from "@/hooks/use-current-user";

export function AppShell({ children }: { children: ReactNode }) {
  const { username, mounted } = useCurrentUser();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  if (!mounted) {
    return <div className="h-dvh bg-canvas" aria-hidden />;
  }

  if (!username) {
    return <UsernameDialog />;
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      <div
        className={`shrink-0 max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-50 max-md:transition-transform ${
          sidebarOpen ? "max-md:translate-x-0" : "max-md:-translate-x-full"
        }`}
      >
        <AppSidebar />
      </div>
      {sidebarOpen ? (
        <div
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      ) : null}
      <div className="relative flex h-dvh min-w-0 flex-1 flex-col overflow-hidden">
        <button
          className="absolute left-3 top-3 z-10 inline-flex size-10 items-center justify-center rounded-md border border-border bg-surface text-fg md:hidden"
          onClick={() => setSidebarOpen((open) => !open)}
          aria-label="Toggle sidebar"
        >
          <Menu size={20} />
        </button>
        {children}
      </div>
    </div>
  );
}
