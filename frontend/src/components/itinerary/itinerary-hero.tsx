import { CalendarDays, MapPin, Users, Wallet } from "lucide-react";
import { PdfDownloadButton } from "@/components/itinerary/pdf-download-button";
import type { Itinerary } from "@/lib/types";

type ItineraryHeroProps = {
  itinerary: Itinerary;
  onDownloadPdf: () => void;
  isPdfDownloading: boolean;
  pdfError: string | null;
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
  onDownloadPdf,
  isPdfDownloading,
  pdfError,
}: ItineraryHeroProps) {
  const stops = itinerary.destinations?.length
    ? itinerary.destinations
    : [itinerary.destination];
  const dateRange = readDateRange(itinerary.dates);
  const budget = itinerary.budget_breakdown;
  const totalCost = budget
    ? `${budget.currency_code} ${Math.round(budget.total_estimated_cost).toLocaleString()}`
    : null;

  return (
    <header className="flex flex-col gap-4 rounded-lg border border-border bg-gradient-to-br from-accent-soft to-surface p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-wrap items-center gap-2">
          {itinerary.version && itinerary.version > 1 ? (
            <span className="rounded-full border border-accent bg-surface px-2 py-0.5 text-[0.72rem] font-bold text-accent-hover">
              v{itinerary.version}
            </span>
          ) : null}
          <h2 className="font-display text-[1.75rem] font-bold leading-tight tracking-tight text-fg">
            {itinerary.title}
          </h2>
        </div>
        <PdfDownloadButton
          onDownload={onDownloadPdf}
          disabled={!itinerary.id}
          isDownloading={isPdfDownloading}
          error={pdfError}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-muted">{itinerary.source}</span>
        {stops.map((stop) => (
          <span
            key={stop}
            className="rounded-full border border-border-strong bg-surface px-3 py-0.5 text-[0.82rem] font-semibold text-fg"
          >
            {stop}
          </span>
        ))}
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

      {itinerary.reality_banner ? (
        <p
          className="m-0 rounded-md border border-border-strong border-l-[3px] border-l-accent bg-surface px-4 py-3 text-[0.88rem] leading-relaxed text-fg"
          role="note"
        >
          {itinerary.reality_banner}
        </p>
      ) : null}
    </header>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-border bg-surface p-3">
      <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent">
        {icon}
      </span>
      <div>
        <dt className="text-[0.7rem] uppercase tracking-wide text-faint">{label}</dt>
        <dd className="mt-0.5 text-[0.9rem] font-semibold text-fg">{value}</dd>
      </div>
    </div>
  );
}
