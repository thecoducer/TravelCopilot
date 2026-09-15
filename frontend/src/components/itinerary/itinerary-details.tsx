import { Accordion } from "@/components/ui/accordion";
import { cn } from "@/lib/utils";
import type {
  BudgetReport,
  Itinerary,
  RouteLeg,
  TransportRecommendation,
} from "@/lib/types";

type ItineraryDetailsProps = {
  itinerary: Itinerary;
};

const miniHeading = "mb-2 text-[0.8rem] font-bold uppercase tracking-wide text-faint";
const disclaimerClass = "text-xs leading-relaxed text-faint";

function money(value: number | null | undefined, currency?: string | null): string | null {
  if (value === null || value === undefined) return null;
  return `${currency ? `${currency} ` : ""}${Math.round(value).toLocaleString()}`;
}

function formatMinutes(minutes?: number | null): string | null {
  if (!minutes) return null;
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`;
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
              <a className="text-xs font-semibold text-chat-blue hover:text-chat-blue-hover hover:underline" href={leg.booking_url} target="_blank" rel="noreferrer">
              Book this leg
            </a>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function TransportPanel({ itinerary }: { itinerary: Itinerary }) {
  const section = itinerary.transport_section;
  if (!section) return null;
  const options = [section.recommended, ...section.alternatives].filter(
    (item): item is TransportRecommendation => Boolean(item),
  );
  if (options.length === 0) return null;

  return (
    <Accordion eyebrow="Route logistics" title="Transport" meta={`${options.length} option${options.length === 1 ? "" : "s"}`} defaultOpen>
      <div className="flex flex-col gap-4">
        {options.map((option, index) => (
          <article key={index} className="border-t border-border py-4 first:border-t-0">
            <div className="mb-2 flex items-center gap-2">
              <h5 className="text-[0.95rem] text-fg">{option.route_label ?? option.mode ?? (index === 0 ? "Recommended route" : "Alternative")}</h5>
              {index === 0 ? (
                <span className="rounded-full bg-success-soft px-2 py-px text-[0.68rem] font-bold uppercase text-success">
                  Recommended
                </span>
              ) : null}
              {money(option.total_cost, option.currency_code) ? (
                <span className="ml-auto font-mono font-semibold tabular-nums text-fg">{money(option.total_cost, option.currency_code)}</span>
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
    </Accordion>
  );
}

function BudgetPanel({ budget }: { budget: BudgetReport }) {
  const categories = Object.entries(budget.per_category_breakdown ?? {});
  const max = Math.max(1, ...categories.map(([, value]) => value));
  const fxRates = Object.entries(budget.fx_rates_used ?? {});

  return (
    <section className="flex flex-col gap-6 border-b border-border pb-8 pt-4">
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
                <span className="font-mono text-sm font-medium tabular-nums text-fg">{money(value, budget.currency_code)}</span>
              </div>
            ))}
          </div>
        ) : null}

        <div className="flex flex-wrap gap-x-5 gap-y-2 border-t border-border pt-4 text-sm text-muted">
          {budget.per_person_cost ? <span>Per person: {money(budget.per_person_cost, budget.currency_code)}</span> : null}
          {budget.permit_costs ? <span>Permits: {money(budget.permit_costs, budget.currency_code)}</span> : null}
        </div>

        {fxRates.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Exchange rates used</h5>
            <p className="text-[0.82rem] text-muted">
              {fxRates.map(([pair, entry]) => `${pair}: ${entry.rate}`).join(" · ")}
            </p>
            {budget.fx_disclaimer ? <small className={disclaimerClass}>{budget.fx_disclaimer}</small> : null}
          </div>
        ) : null}

        {budget.cost_saving_tips.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Ways to save</h5>
            <Checklist items={budget.cost_saving_tips} />
          </div>
        ) : null}
      </div>
    </section>
  );
}

function VisaPanel({ itinerary }: { itinerary: Itinerary }) {
  const visa = itinerary.visa_section;
  if (!visa) return null;
  const centre = visa.application_centre ?? visa.nearest_embassy;
  const confidenceClass = cn(
    "rounded-full px-2 py-px text-[0.72rem] font-semibold capitalize",
    visa.confidence === "high" && "bg-success-soft text-success",
    visa.confidence === "low" && "bg-danger-soft text-danger",
    (!visa.confidence || visa.confidence === "medium") && "bg-border text-muted",
  );

  return (
    <Accordion
      eyebrow="Entry requirements"
      title="Visa checklist"
      meta={visa.visa_required ? "Visa required" : "No visa"}
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm text-muted">
          {visa.visa_type ? <span>Type: {visa.visa_type}</span> : null}
          {visa.processing_timeline ? <span>Processing: {visa.processing_timeline}</span> : null}
          {visa.fees ? <span>Fees: {visa.fees}</span> : null}
          {visa.confidence ? <span className={confidenceClass}>{visa.confidence} confidence</span> : null}
        </div>

        {visa.documents_required && visa.documents_required.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Documents required</h5>
            <Checklist items={visa.documents_required} />
          </div>
        ) : null}

        {visa.application_process && visa.application_process.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Application steps</h5>
            <ol className="flex list-decimal flex-col gap-2 pl-4 text-[0.88rem] text-fg">
              {visa.application_process.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </div>
        ) : null}

        {visa.dos_and_donts && visa.dos_and_donts.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Do&apos;s and don&apos;ts</h5>
            <Checklist items={visa.dos_and_donts} />
          </div>
        ) : null}

        {centre ? (
          <div>
            <h5 className={miniHeading}>Where to apply</h5>
            <p className="text-[0.88rem] text-fg">
              {centre.name}
              {centre.address ? `, ${centre.address}` : ""}
            </p>
            {centre.booking_url ? (
              <a className="text-xs font-semibold text-chat-blue hover:text-chat-blue-hover hover:underline" href={centre.booking_url} target="_blank" rel="noreferrer">
                Book an appointment
              </a>
            ) : null}
          </div>
        ) : null}

        {visa.apply_online_url ? (
          <a className="text-xs font-semibold text-chat-blue hover:text-chat-blue-hover hover:underline" href={visa.apply_online_url} target="_blank" rel="noreferrer">
            Apply online
          </a>
        ) : null}

        {visa.sources && visa.sources.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Sources</h5>
            <ul className="list-disc pl-4 text-sm">
              {visa.sources.map((source) => (
                <li key={source.url}>
                    <a className="text-chat-blue hover:text-chat-blue-hover hover:underline" href={source.url} target="_blank" rel="noreferrer">
                    {source.title}
                  </a>
                  {source.published_or_fetched_date ? ` — ${source.published_or_fetched_date}` : ""}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {visa.last_verified_at ? (
          <small className={disclaimerClass}>Last verified: {visa.last_verified_at}</small>
        ) : null}
        <small className={disclaimerClass}>{visa.disclaimer}</small>
      </div>
    </Accordion>
  );
}

function PracticalPanel({ itinerary }: { itinerary: Itinerary }) {
  const facts = [
    itinerary.connectivity_summary ? { title: "Connectivity", value: itinerary.connectivity_summary } : null,
    itinerary.language_tips ? { title: "Language tips", value: itinerary.language_tips } : null,
    itinerary.currency_tips ? { title: "Money tips", value: itinerary.currency_tips } : null,
  ].filter((item): item is { title: string; value: string } => item !== null);

  if (facts.length === 0 && itinerary.packing_tips.length === 0) return null;

  return (
    <Accordion eyebrow="Before you go" title="Practical details">
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
          {facts.map((fact) => (
            <div key={fact.title}>
              <h5 className={miniHeading}>{fact.title}</h5>
              <p className="text-[0.88rem] text-fg">{fact.value}</p>
            </div>
          ))}
        </div>
        {itinerary.packing_tips.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Packing list</h5>
            <Checklist items={itinerary.packing_tips} />
          </div>
        ) : null}
      </div>
    </Accordion>
  );
}

export function ItineraryDetails({ itinerary }: ItineraryDetailsProps) {
  return (
    <div className="flex flex-col gap-3">
      <TransportPanel itinerary={itinerary} />
      {itinerary.budget_breakdown ? <BudgetPanel budget={itinerary.budget_breakdown} /> : null}
      <VisaPanel itinerary={itinerary} />
      <PracticalPanel itinerary={itinerary} />
    </div>
  );
}
