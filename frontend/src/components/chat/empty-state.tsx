"use client";

const EXAMPLE_PROMPTS = [
  "3 days in Osaka from Kolkata, love street food",
  "Leh to Nubra to Pangong, 6 days, self-drive",
  "Weekend trip from Mumbai to Pune",
  "10 days in Japan for two, mid-range budget",
];

export function EmptyState({ onExampleClick }: { onExampleClick: (prompt: string) => void }) {
  return (
    <div className="mx-auto flex max-w-2xl flex-1 flex-col items-center justify-center gap-4 py-16 text-center">
      <h1 className="font-display text-3xl font-bold tracking-tight text-fg">
        Where are you headed?
      </h1>
      <p className="max-w-md text-muted">
        Tell me your trip in a sentence — I&apos;ll plan the route, stays, food, and budget.
      </p>
      <ul className="mt-2 grid w-full gap-2 sm:grid-cols-2">
        {EXAMPLE_PROMPTS.map((prompt) => (
          <li key={prompt}>
            <button
              type="button"
              className="w-full rounded-md border border-border bg-surface px-4 py-3 text-left text-sm text-fg transition-colors hover:border-accent hover:bg-accent-soft"
              onClick={() => onExampleClick(prompt)}
            >
              {prompt}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
