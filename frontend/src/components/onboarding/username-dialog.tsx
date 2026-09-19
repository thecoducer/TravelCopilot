"use client";

import { useState, type FormEvent } from "react";
import { registerUser } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Input } from "@/components/ui/input";
import { useCurrentUser } from "@/hooks/use-current-user";
import { TravelCopilotLogo } from "@/components/brand/travel-copilot-logo";

const USERNAME_PATTERN = /^[a-zA-Z0-9_-]{3,32}$/;

/** Blocking first-load gate: no username, no app. Auth-free by design. */
export function UsernameDialog() {
  const { setUsername } = useCurrentUser();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const candidate = value.trim();
    if (!USERNAME_PATTERN.test(candidate)) {
      setError("Use 3–32 letters, numbers, hyphens or underscores.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const confirmed = await registerUser(candidate);
      setUsername(confirmed);
    } catch {
      setError("Could not save that name. Please try again.");
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-canvas/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="welcome-title"
    >
      <div className="w-full max-w-md rounded-lg border border-border bg-surface p-8 shadow-md">
        <TravelCopilotLogo className="mb-6" />
        <h1 id="welcome-title" className="font-display text-2xl font-bold tracking-tight text-fg">
          Welcome to Travel Copilot
        </h1>
        <p className="mb-6 mt-2 text-sm leading-relaxed text-muted">
          Pick a username so we can keep your trips and preferences together. No password needed.
        </p>
        <form className="flex flex-col gap-2" onSubmit={handleSubmit}>
          <label
            className="text-xs font-semibold uppercase tracking-wide text-faint"
            htmlFor="username-input"
          >
            Username
          </label>
          <Input
            id="username-input"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="e.g. alex_travels"
            autoFocus
            autoComplete="off"
            spellCheck={false}
            maxLength={32}
          />
          {error ? <ErrorBanner message={error} className="px-3 py-2" /> : null}
          <Button type="submit" disabled={submitting} className="mt-2 w-full">
            {submitting ? "Setting up…" : "Continue"}
          </Button>
        </form>
      </div>
    </div>
  );
}
