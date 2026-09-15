import type { SVGProps } from "react";

export function TravelCopilotLogo({
  showWordmark = true,
  className,
  ...props
}: SVGProps<SVGSVGElement> & { showWordmark?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className ?? ""}`}>
      <svg
        width="34"
        height="34"
        viewBox="0 0 34 34"
        fill="none"
        role="img"
        aria-label="Travel Copilot logo"
        {...props}
      >
        <rect x="1.5" y="1.5" width="31" height="31" rx="9" fill="var(--accent)" />
        <circle cx="17" cy="17" r="9.5" stroke="white" strokeWidth="1.5" opacity="0.9" />
        <path
          d="M11.5 22.5 15.2 13l7.3-2.8-3.2 7.7-7.8 4.6Z"
          fill="white"
          fillOpacity="0.95"
        />
        <path d="m15.2 13 4.1 4.9" stroke="var(--accent)" strokeWidth="1.5" />
        <circle cx="15.2" cy="13" r="1.4" fill="white" />
        <circle cx="19.3" cy="17.9" r="1.4" fill="var(--accent)" />
      </svg>
      {showWordmark ? (
        <span className="font-display text-[1.05rem] font-bold tracking-tight text-fg">
          Travel Copilot
        </span>
      ) : null}
    </span>
  );
}
