import { ChevronDown, ChevronUp } from "lucide-react";

type MoreExpanderProps = {
  expanded: boolean;
  onClick: () => void;
  collapsedLabel?: string;
  expandedLabel?: string;
};

export function MoreExpander({
  expanded,
  onClick,
  collapsedLabel = "Show all",
  expandedLabel = "Hide",
}: MoreExpanderProps) {
  return (
    <button
      type="button"
      className="relative z-10 inline-flex items-center gap-1 rounded-full border border-border-strong bg-surface px-4 py-2 text-sm font-semibold text-fg shadow-sm transition-colors hover:bg-accent-soft"
      onClick={onClick}
      aria-expanded={expanded}
    >
      {expanded ? expandedLabel : collapsedLabel}
      {expanded ? <ChevronUp size={16} aria-hidden="true" /> : <ChevronDown size={16} aria-hidden="true" />}
    </button>
  );
}
