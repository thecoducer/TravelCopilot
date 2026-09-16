import { CalendarDays, MapPin, Users, Wallet } from "lucide-react";
import type { Itinerary } from "@/lib/types";

type ItineraryHeroProps = {
  itinerary: Itinerary;
};

function readDateRange(dates: Itinerary["dates"]): string | null {
  if (!dates) return null;
  const record = dates as Record<string, unknown>;
  const start = record.departure ?? record.start_date;
  const end = record.return_date ?? record.end_date;
  if (typeof start !== "string") return null;
  return typeof end === "string" && end ? `${start} → ${end}` : start;
}

export function ItineraryHero({
  itinerary,
}: ItineraryHeroProps) {
  const dateRange = readDateRange(itinerary.dates);
  const budget = itinerary.budget_breakdown;
  const totalCost = budget
    ? `${budget.currency_code} ${Math.round(budget.total_estimated_cost).toLocaleString()}`
    : null;

  return (
    <header className="flex flex-col gap-5 pb-2">
      <div className="flex flex-col gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {itinerary.version && itinerary.version > 1 ? (
              <span className="border-b border-accent px-1 py-0.5 text-[0.72rem] font-bold text-accent-hover">
                v{itinerary.version}
              </span>
            ) : null}
            <h2 className="font-display text-[clamp(1.5rem,3vw,2.15rem)] font-bold leading-tight tracking-tight text-fg">
              {itinerary.title}
            </h2>
          </div>
        </div>
      </div>

      <dl className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
        {dateRange ? (
          <Stat icon={<CalendarDays size={15} />} label="Dates" value={dateRange} />
        ) : null}
        <Stat
          icon={<Users size={15} />}
          label="Travelers"
          value={`${itinerary.travelers} traveler${itinerary.travelers === 1 ? "" : "s"}`}
        />
        <Stat
          icon={<MapPin size={15} />}
          label="Days"
          value={`${itinerary.trip_days.length} day${itinerary.trip_days.length === 1 ? "" : "s"}`}
        />
        {totalCost ? (
          <Stat
            icon={<Wallet size={15} />}
            label={`Est. cost · ${budget?.vs_budget_verdict ?? ""}`.trim()}
            value={totalCost}
          />
        ) : null}
      </dl>

    </header>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 px-1 py-2 sm:px-0">
      <span className="inline-flex size-8 shrink-0 items-center justify-center text-accent">
        {icon}
      </span>
      <div>
        <dt className="text-[0.7rem] uppercase tracking-wide text-summary-heading">{label}</dt>
        <dd className="mt-0.5 font-mono text-[0.9rem] font-semibold text-fg">{value}</dd>
      </div>
    </div>
  );
}
