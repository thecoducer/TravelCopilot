import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type BadgeVariant = "default" | "accent" | "success" | "danger" | "outline";

const variants: Record<BadgeVariant, string> = {
  default: "bg-canvas text-muted border border-border",
  accent: "bg-accent-soft text-accent-hover",
  success: "bg-success-soft text-success",
  danger: "bg-danger-soft text-danger",
  outline: "border border-border-strong text-fg",
};

export function Badge({
  variant = "default",
  className,
  ...rest
}: HTMLAttributes<HTMLSpanElement> & { variant?: BadgeVariant }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold",
        variants[variant],
        className,
      )}
      {...rest}
    />
  );
}
