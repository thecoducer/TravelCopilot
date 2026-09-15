"use client";

import type { ReactNode } from "react";
import { ThemeProvider } from "@/hooks/use-theme";
import { UserProvider } from "@/hooks/use-current-user";
import { SessionsProvider } from "@/hooks/use-sessions";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider>
      <UserProvider>
        <SessionsProvider>{children}</SessionsProvider>
      </UserProvider>
    </ThemeProvider>
  );
}
