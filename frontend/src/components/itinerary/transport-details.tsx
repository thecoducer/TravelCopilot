import type { Itinerary, RouteLeg, TransportRecommendation } from "@/lib/types";

function money(value: number | null | undefined, currency?: string | null): string | null {
  if (value === null || value === undefined) return null;
  return `${currency ? `${currency} ` : ""}${Math.round(value).toLocaleString()}`;
}

function formatMinutes(minutes?: number | null): string | null {
  if (!minutes) return null;
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`;
}

function LegTimeline({ legs }: { legs: RouteLeg[] }) {
  return (
    <ol className="mt-2 flex list-none flex-col gap-3">
      {legs.map((leg, index) => (
        <li key={`${leg.origin}-${leg.destination}-${index}`} className="border-l-2 border-border-strong pl-3">
          <div className="flex flex-col gap-px">
            <strong className="text-sm text-fg">
              {leg.origin} → {leg.destination}
            </strong>
            <span className="text-xs text-muted">
              {[leg.mode, leg.operator, leg.flight_number].filter(Boolean).join(" · ")}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs tabular-nums text-muted">
            {leg.departure_time || leg.arrival_time ? (
              <span>
                {leg.departure_time ?? "?"} → {leg.arrival_time ?? "?"}
              </span>
            ) : null}
            {formatMinutes(leg.duration_minutes) ? <span>{formatMinutes(leg.duration_minutes)}</span> : null}
            {leg.seat_class ? <span>{leg.seat_class}</span> : null}
            {money(leg.cost, leg.currency_code) ? <span>{money(leg.cost, leg.currency_code)}</span> : null}
            {leg.layover_at ? <span>Layover: {leg.layover_at}</span> : null}
          </div>
          {leg.baggage_allowance ? <p className="mt-1 text-xs text-faint">Baggage: {leg.baggage_allowance}</p> : null}
          {leg.cancellation_policy ? (
            <p className="mt-1 text-xs text-faint">Cancellation: {leg.cancellation_policy}</p>
          ) : null}
          {leg.booking_url ? (
            <a
              className="text-xs font-semibold text-chat-blue hover:text-chat-blue-hover hover:underline"
              href={leg.booking_url}
              target="_blank"
              rel="noreferrer"
            >
              Book this leg
            </a>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

export function TransportDetails({ itinerary }: { itinerary: Itinerary }) {
  const section = itinerary.transport_section;
  if (!section) return null;
  const options = [section.recommended, ...section.alternatives].filter(
    (item): item is TransportRecommendation =>
      Boolean(
        item &&
          (item.route_label ||
            item.mode ||
            item.rationale ||
            item.total_cost !== null && item.total_cost !== undefined ||
            item.non_obvious_insight ||
            item.recommended_legs?.length),
      ),
  );
  if (options.length === 0) return null;

  return (
    <section className="flex flex-col gap-4 pb-8 pt-4">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <span className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-faint">
            Route logistics
          </span>
          <h3 className="mt-1 font-display text-[1.7rem] font-semibold tracking-tight text-fg sm:text-[1.9rem]">
            Transport
          </h3>
        </div>
        <span className="text-sm text-muted">
          {options.length} option{options.length === 1 ? "" : "s"}
        </span>
      </header>

      <div className="flex flex-col gap-4">
        {options.map((option, index) => (
          <article key={index} className="border-t border-border py-4 first:border-t-0">
            <div className="mb-2 flex items-center gap-2">
              <h5 className="text-[0.95rem] text-fg">
                {index === 0 ? "Recommended route" : "Alternative"}
              </h5>
              {money(option.total_cost, option.currency_code) ? (
                <span className="ml-auto font-mono font-semibold tabular-nums text-fg">
                  {money(option.total_cost, option.currency_code)}
                </span>
              ) : null}
            </div>
            {option.rationale ? <p className="text-sm text-muted">{option.rationale}</p> : null}
            {option.non_obvious_insight ? (
              <p className="mb-2 mt-2 border-l-2 border-accent px-3 py-2 text-sm">💡 {option.non_obvious_insight}</p>
            ) : null}
            {option.recommended_legs && option.recommended_legs.length > 0 ? (
              <LegTimeline legs={option.recommended_legs} />
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}