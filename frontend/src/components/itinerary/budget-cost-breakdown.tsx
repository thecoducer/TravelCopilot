import type { BudgetReport } from "@/lib/types";

function money(value: number | null | undefined, currency?: string | null): string | null {
  if (value === null || value === undefined) return null;
  return `${currency ? `${currency} ` : ""}${Math.round(value).toLocaleString()}`;
}

function Checklist({ items }: { items: string[] }) {
  return (
    <ul className="flex list-disc flex-col gap-1 pl-4 text-[0.88rem] text-fg">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export function BudgetCostBreakdown({ budget }: { budget: BudgetReport | null }) {
  if (!budget) return null;

  const categories = Object.entries(budget.per_category_breakdown ?? {}).filter(([, value]) => value > 0);
  const hasContent =
    categories.length > 0 ||
    budget.total_estimated_cost > 0 ||
    budget.per_person_cost !== null && budget.per_person_cost > 0 ||
    budget.permit_costs !== null && budget.permit_costs !== undefined && budget.permit_costs > 0 ||
    Boolean(budget.vs_budget_verdict?.trim()) ||
    budget.cost_saving_tips.length > 0;

  if (!hasContent) return null;

  const max = Math.max(1, ...categories.map(([, value]) => value));

  return (
    <section className="flex flex-col gap-4 pb-8 pt-4">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <span className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-faint">Trip cost</span>
          <h3 className="mt-1 font-display text-[1.7rem] font-semibold tracking-tight text-fg sm:text-[1.9rem]">
            Cost breakdown
          </h3>
        </div>
        <div className="flex items-baseline gap-2 sm:flex-col sm:items-end sm:gap-0">
          <strong className="font-mono text-lg font-semibold tabular-nums text-fg">
            {money(budget.total_estimated_cost, budget.currency_code)}
          </strong>
          <span className="text-sm text-muted">{budget.vs_budget_verdict}</span>
          {budget.per_person_cost ? (
            <span className="font-mono text-sm tabular-nums text-muted">
              Per person: {money(budget.per_person_cost, budget.currency_code)}
            </span>
          ) : null}
        </div>
      </header>

      <div className="flex flex-col gap-5">
        {categories.length > 0 ? (
          <div className="flex flex-col gap-3">
            {categories.map(([label, value]) => (
              <div key={label} className="grid grid-cols-[minmax(100px,0.3fr)_1fr_auto] items-center gap-3">
                <span className="text-sm capitalize text-muted">{label.replaceAll("_", " ")}</span>
                <span className="h-2 overflow-hidden rounded-full bg-border">
                  <span className="block h-full rounded-full bg-chat-blue" style={{ width: `${(value / max) * 100}%` }} />
                </span>
                <span className="font-mono text-sm font-medium tabular-nums text-fg">
                  {money(value, budget.currency_code)}
                </span>
              </div>
            ))}
          </div>
        ) : null}

        {budget.permit_costs ? (
          <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted">
            <span>Permits: {money(budget.permit_costs, budget.currency_code)}</span>
          </div>
        ) : null}

        {budget.cost_saving_tips.length > 0 ? (
          <div>
            <h5 className="mb-2 text-[0.8rem] font-bold uppercase tracking-wide text-faint">Ways to save</h5>
            <Checklist items={budget.cost_saving_tips} />
          </div>
        ) : null}
      </div>
    </section>
  );
}