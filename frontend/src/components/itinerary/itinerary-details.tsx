import Image from "next/image";
import { Accordion } from "@/components/ui/accordion";
import { cn } from "@/lib/utils";
import type {
  BudgetReport,
  Itinerary,
  RouteLeg,
  StayOption,
  TransportRecommendation,
  TripDays,
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

function StayCard({ stay }: { stay: StayOption }) {
  const image = stay.photos?.[0];
  return (
    <article className="flex gap-3 rounded-md border border-border bg-canvas p-3">
      {image ? (
        <Image
          className="size-[84px] shrink-0 rounded-sm object-cover"
          src={image}
          alt={stay.name ?? "Accommodation"}
          width={84}
          height={84}
          unoptimized
        />
      ) : null}
      <div className="min-w-0">
        <h5 className="mb-1 text-sm text-fg">{stay.name ?? "Accommodation option"}</h5>
        <div className="flex flex-wrap gap-2 text-xs text-muted">
          {stay.rating ? <span>★ {stay.rating.toFixed(1)}</span> : null}
          {stay.price_per_night ? <span>{money(stay.price_per_night, stay.currency_code)} / night</span> : null}
          {stay.hotel_style ? <span>{stay.hotel_style}</span> : null}
        </div>
        {stay.amenities && stay.amenities.length > 0 ? (
          <p className="my-1 text-xs text-faint">{stay.amenities.slice(0, 6).join(" · ")}</p>
        ) : null}
        {stay.free_cancellation_until ? (
          <p className="my-1 text-xs text-success">Free cancellation until {stay.free_cancellation_until}</p>
        ) : null}
        {stay.address ? <small className="my-1 block text-xs text-faint">{stay.address}</small> : null}
        {stay.booking_url ? (
          <a className="text-xs font-semibold text-accent hover:underline" href={stay.booking_url} target="_blank" rel="noreferrer">
            View booking
          </a>
        ) : null}
      </div>
    </article>
  );
}

type StopGroup = {
  location: string;
  stopId: string | null;
  first: TripDays;
  days: TripDays[];
};

/** Presentational grouping only — the itinerary data itself stays flat and day-wise. */
function groupDaysByStop(tripDays: TripDays[]): StopGroup[] {
  return tripDays.reduce<StopGroup[]>((groups, day) => {
    const current = groups.at(-1);
    if (current && current.location === day.location && current.stopId === (day.stop_id ?? null)) {
      current.days.push(day);
    } else {
      groups.push({
        location: day.location,
        stopId: day.stop_id ?? null,
        first: day,
        days: [day],
      });
    }
    return groups;
  }, []);
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
            <a className="text-xs font-semibold text-accent hover:underline" href={leg.booking_url} target="_blank" rel="noreferrer">
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
          <article key={index} className="rounded-md border border-border bg-canvas p-4">
            <div className="mb-2 flex items-center gap-2">
              <h5 className="text-[0.95rem] text-fg">{option.route_label ?? option.mode ?? (index === 0 ? "Recommended route" : "Alternative")}</h5>
              {index === 0 ? (
                <span className="rounded-full bg-success-soft px-2 py-px text-[0.68rem] font-bold uppercase text-success">
                  Recommended
                </span>
              ) : null}
              {money(option.total_cost, option.currency_code) ? (
                <span className="ml-auto font-semibold tabular-nums text-fg">{money(option.total_cost, option.currency_code)}</span>
              ) : null}
            </div>
            {option.rationale ? <p className="text-sm text-muted">{option.rationale}</p> : null}
            {option.non_obvious_insight ? (
              <p className="mb-2 mt-2 rounded-sm bg-accent-soft px-3 py-2 text-sm">💡 {option.non_obvious_insight}</p>
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
    <Accordion
      eyebrow="Costs"
      title="Budget breakdown"
      meta={`${money(budget.total_estimated_cost, budget.currency_code)} · ${budget.vs_budget_verdict}`}
    >
      <div className="flex flex-col gap-4">
        {categories.length > 0 ? (
          <div className="flex flex-col gap-2">
            {categories.map(([label, value]) => (
              <div key={label} className="grid grid-cols-[110px_1fr_auto] items-center gap-3">
                <span className="text-[0.82rem] capitalize text-muted">{label.replaceAll("_", " ")}</span>
                <span className="h-2 overflow-hidden rounded-full bg-border">
                  <span className="block h-full rounded-full bg-accent" style={{ width: `${(value / max) * 100}%` }} />
                </span>
                <span className="text-[0.82rem] tabular-nums text-fg">{money(value, budget.currency_code)}</span>
              </div>
            ))}
          </div>
        ) : null}

        <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm text-muted">
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
    </Accordion>
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
              <a className="text-xs font-semibold text-accent hover:underline" href={centre.booking_url} target="_blank" rel="noreferrer">
                Book an appointment
              </a>
            ) : null}
          </div>
        ) : null}

        {visa.apply_online_url ? (
          <a className="text-xs font-semibold text-accent hover:underline" href={visa.apply_online_url} target="_blank" rel="noreferrer">
            Apply online
          </a>
        ) : null}

        {visa.sources && visa.sources.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Sources</h5>
            <ul className="list-disc pl-4 text-sm">
              {visa.sources.map((source) => (
                <li key={source.url}>
                  <a className="text-accent hover:underline" href={source.url} target="_blank" rel="noreferrer">
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

function HotelsPanel({ itinerary }: { itinerary: Itinerary }) {
  const stopGroups = groupDaysByStop(itinerary.trip_days);
  const withStays = stopGroups.filter((group) => (group.first.stay_options?.options.length ?? 0) > 0);
  if (withStays.length === 0) return null;

  return (
    <Accordion eyebrow="Where you'll stay" title="Hotels by stop" meta={`${withStays.length} stop${withStays.length === 1 ? "" : "s"}`}>
      <div className="flex flex-col gap-4">
        {withStays.map((group) => {
          const permits = [...new Set(group.days.flatMap((day) => day.permits_required))];
          return (
            <div
              key={`${group.location}-${group.stopId ?? group.first.day_number}`}
              className="border-b border-border pb-3 last:border-0 last:pb-0"
            >
              <div className="mb-2 flex items-baseline justify-between">
                <h5 className="text-[0.95rem] text-fg">{group.location}</h5>
                <span className="text-sm text-muted">
                  {group.days.length} night{group.days.length === 1 ? "" : "s"}
                </span>
              </div>
              {permits.length > 0 ? <p className="text-xs text-faint">Permits: {permits.join(", ")}</p> : null}
              <div className="mt-2 grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-3">
                {(group.first.stay_options?.options ?? []).map((stay, index) => (
                  <StayCard key={`${stay.name ?? "stay"}-${index}`} stay={stay} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </Accordion>
  );
}

function SafetyPanel({ itinerary }: { itinerary: Itinerary }) {
  const safety = itinerary.safety_section;
  if (!safety) return null;
  const scams = safety.top_scams ?? [];
  const contacts = Object.entries(safety.emergency_contacts ?? {});

  return (
    <Accordion eyebrow="Stay safe" title="Safety report" meta={safety.advisory_level ?? undefined}>
      <div className="flex flex-col gap-4">
        {itinerary.safety_briefing ? <p className="text-sm text-fg">{itinerary.safety_briefing}</p> : null}
        {scams.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Common scams</h5>
            <ul className="flex list-disc flex-col gap-1 pl-4 text-[0.88rem] text-fg">
              {scams.map((scam) => (
                <li key={scam.name}>
                  <strong>{scam.name}</strong> — {scam.how_to_avoid}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {contacts.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Emergency contacts</h5>
            <ul className="flex list-disc flex-col gap-1 pl-4 text-[0.88rem] text-fg">
              {contacts.map(([label, number]) => (
                <li key={label}>
                  {label}: {number}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {safety.safe_areas && safety.safe_areas.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Safer areas</h5>
            <p className="text-[0.88rem] text-fg">{safety.safe_areas.join(", ")}</p>
          </div>
        ) : null}
        <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
          {safety.medical_facilities ? (
            <div>
              <h5 className={miniHeading}>Medical</h5>
              <p className="text-[0.88rem] text-fg">{safety.medical_facilities}</p>
            </div>
          ) : null}
          {safety.women_safety_notes ? (
            <div>
              <h5 className={miniHeading}>Women travellers</h5>
              <p className="text-[0.88rem] text-fg">{safety.women_safety_notes}</p>
            </div>
          ) : null}
          {safety.insurance_recommendation ? (
            <div>
              <h5 className={miniHeading}>Insurance</h5>
              <p className="text-[0.88rem] text-fg">{safety.insurance_recommendation}</p>
            </div>
          ) : null}
        </div>
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
      <HotelsPanel itinerary={itinerary} />
      <SafetyPanel itinerary={itinerary} />
      <PracticalPanel itinerary={itinerary} />
    </div>
  );
}
