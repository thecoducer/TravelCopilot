"use client";

import { useState, type ReactNode } from "react";
import { Menu } from "lucide-react";
import { AppSidebar } from "@/components/sidebar/app-sidebar";
import { UsernameDialog } from "@/components/onboarding/username-dialog";
import { useCurrentUser } from "@/hooks/use-current-user";

export function AppShell({ children }: { children: ReactNode }) {
  const { username, mounted } = useCurrentUser();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarHidden, setSidebarHidden] = useState(false);

  if (!mounted) {
    return <div className="h-dvh bg-canvas" aria-hidden />;
  }

  if (!username) {
    return <UsernameDialog />;
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      <div
        className={`shrink-0 overflow-hidden transition-[width] ease-in-out ${sidebarHidden ? "duration-[450ms] md:w-14" : "duration-300 md:w-[var(--sidebar-width)]"} max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-50 max-md:transition-transform ${
          sidebarOpen ? "max-md:translate-x-0" : "max-md:-translate-x-full"
        }`}
      >
        <AppSidebar
          collapsed={sidebarHidden}
          onShow={() => setSidebarHidden(false)}
          onHide={() => {
            setSidebarHidden(true);
            setSidebarOpen(false);
          }}
        />
      </div>
      {sidebarOpen ? (
        <div
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      ) : null}
      <div className="relative flex h-dvh min-w-0 flex-1 flex-col overflow-hidden bg-canvas/80">
        <button
          className="absolute left-4 top-4 z-10 inline-flex size-9 items-center justify-center rounded-lg border border-border bg-surface/90 text-muted shadow-sm backdrop-blur md:hidden"
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
