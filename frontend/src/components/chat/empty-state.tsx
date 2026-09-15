import { Compass, MapPinned, Sparkles, WalletCards } from "lucide-react";

const PLANNING_LAYERS = [
  { icon: MapPinned, label: "Route", detail: "Stops and travel time" },
  { icon: Compass, label: "Stays", detail: "Places that fit your pace" },
  { icon: Sparkles, label: "Local finds", detail: "Food and experiences" },
  { icon: WalletCards, label: "Budget", detail: "Costs you can trust" },
];

const EXAMPLE_PROMPTS = [
  { label: "Food-led city break", text: "3 days in Osaka from Kolkata, love street food" },
  { label: "Himalayan road trip", text: "Leh to Nubra to Pangong, 6 days, self-drive" },
  { label: "Easy weekend escape", text: "Weekend trip from Mumbai to Pune" },
  { label: "Longer Japan journey", text: "10 days in Japan for two, mid-range budget" },
];

export function EmptyState() {
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col justify-center py-12 sm:py-16">
      <div className="max-w-2xl">
        <p className="mb-5 text-[0.68rem] font-bold uppercase tracking-[0.22em] text-chat-blue">
          Travel Copilot
        </p>
        <h1 className="font-display text-4xl font-bold leading-[1.05] tracking-tight text-fg sm:text-5xl">
          Plan the trip. Keep the good parts.
        </h1>
        <p className="mt-5 max-w-xl text-base leading-7 text-muted sm:text-lg">
          Share where you want to go, when you want to go, and what matters to you. Your route,
          stays, local finds, and budget will come together in one considered plan.
        </p>
      </div>

      <div className="mt-10 grid border-y border-border sm:grid-cols-4">
        {PLANNING_LAYERS.map(({ icon: Icon, label, detail }, index) => (
          <div
            key={label}
            className={`flex gap-3 py-4 sm:flex-col sm:gap-2 sm:px-4 sm:py-5 ${
              index > 0 ? "border-t border-border sm:border-l sm:border-t-0" : ""
            }`}
          >
            <Icon size={18} className="mt-0.5 shrink-0 text-chat-blue" aria-hidden="true" />
            <div>
              <p className="text-sm font-semibold text-fg">{label}</p>
              <p className="text-xs text-muted">{detail}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-10">
        <p className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-faint">
          Start with something as simple as
        </p>
        <ul className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
          {EXAMPLE_PROMPTS.map(({ label, text }) => (
            <li key={text} className="border-l-2 border-chat-blue/35 pl-4">
              <p className="text-xs font-semibold text-muted">{label}</p>
              <p className="mt-1 text-sm leading-6 text-fg/85">{text}</p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
