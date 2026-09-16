"use client";

import { CircleAlert, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type ErrorBannerProps = {
  message: string;
  className?: string;
};

export function ErrorBanner({ message, className }: ErrorBannerProps) {
  const [dismissedMessage, setDismissedMessage] = useState<string | null>(null);

  if (dismissedMessage === message) {
    return null;
  }

  return (
    <div
      role="alert"
      className={cn(
        "relative flex items-start gap-3 overflow-hidden rounded-lg border border-danger/35 bg-danger-soft px-4 py-3.5 text-danger shadow-sm",
        className,
      )}
    >
      <div className="absolute inset-y-0 left-0 w-1 bg-danger" aria-hidden="true" />
      <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
      <p className="min-w-0 flex-1 pr-2 font-mono text-[0.78rem] leading-relaxed sm:text-[0.82rem]">
        {message}
      </p>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="Dismiss error"
        onClick={() => setDismissedMessage(message)}
        className="-mr-1 -mt-1 size-8 shrink-0 rounded-md text-danger hover:bg-danger/10 hover:text-danger"
      >
        <X className="size-4" aria-hidden="true" />
      </Button>
    </div>
  );
}
