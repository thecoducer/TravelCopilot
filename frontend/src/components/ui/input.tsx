import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "w-full rounded-md border border-border-strong bg-canvas px-3 py-2 text-sm text-fg outline-none",
        "transition-colors placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/25",
        className,
      )}
      {...rest}
    />
  );
}
