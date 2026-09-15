import type { TripDays } from "@/lib/types";
import Image from "next/image";

type ItineraryDayCardProps = {
  day: TripDays;
  /** Multi-night stays repeat the same hotel each day; render it only once per stop. */
  showStay?: boolean;
};

const SLOTS: Array<{ key: "morning" | "afternoon" | "evening"; label: string }> = [
  { key: "morning", label: "Morning" },
  { key: "afternoon", label: "Afternoon" },
  { key: "evening", label: "Evening" },
];

function formatDuration(minutes?: number) {
  if (!minutes) return null;
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`;
}

function OptionImage({ src, alt }: { src?: string; alt: string }) {
  if (!src) return null;
  return (
    <Image
      className="h-[82px] w-24 shrink-0 rounded-sm object-cover"
      src={src}
      alt={alt}
      width={96}
      height={82}
      unoptimized
    />
  );
}

const slotLabelClass = "text-[0.72rem] font-bold uppercase tracking-wide text-faint";
const noteClass = "text-xs text-faint";
const reasonClass = "text-xs text-muted";
const linkClass = "text-xs font-semibold text-accent hover:underline";

/** Renders everything the agents found for one day: activities, food, stay, transport, safety. */
export function ItineraryDayCard({ day, showStay = true }: ItineraryDayCardProps) {
  return (
    <article className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4">
      <header className="flex items-baseline justify-between gap-3">
        <h5 className="font-display text-[1.05rem] font-semibold text-fg">
          Day {day.day_number} — {day.location}
        </h5>
        <span className="text-sm text-muted">{day.date}</span>
      </header>

      <div className="flex flex-wrap gap-2">
        {day.is_travel_day ? <Badge>Travel day</Badge> : null}
        {day.is_checkin_day ? <Badge>Check-in</Badge> : null}
        {day.is_checkout_day ? <Badge>Check-out</Badge> : null}
        {day.estimated_cost ? (
          <Badge>
            ~{Math.round(day.estimated_cost).toLocaleString()} {day.currency_code}
          </Badge>
        ) : null}
      </div>
      {day.summary ? <p className="text-sm leading-relaxed text-muted">{day.summary}</p> : null}
      {day.altitude_warning ? <p className="text-sm text-danger">{day.altitude_warning}</p> : null}

      {day.transport_options.length > 0 ? (
        <section className="flex flex-col gap-2">
          <span className={slotLabelClass}>Transport</span>
          {day.transport_options.map((transfer, index) => (
            <div key={transfer.leg_id ?? index} className="rounded-md border border-border bg-canvas p-3">
              <strong className="text-sm text-fg">
                {transfer.origin} → {transfer.destination}
              </strong>
              {transfer.recommended?.rationale ? (
                <p className={reasonClass}>{transfer.recommended.rationale}</p>
              ) : null}
              {transfer.no_result ? (
                <p className={noteClass}>No bookable option found — arrange locally.</p>
              ) : null}
            </div>
          ))}
        </section>
      ) : null}

      <div className="flex flex-col gap-4">
        {SLOTS.map(({ key, label }) => {
          const slot = day[key];
          if (slot.options.length === 0 && !slot.notes && !slot.unresolved_note) {
            return null;
          }
          return (
            <section key={key} className="flex flex-col gap-2">
              <div className="flex items-baseline gap-2">
                <span className={slotLabelClass}>{label}</span>
                {slot.notes ? <span className="text-xs text-muted">{slot.notes}</span> : null}
              </div>
              {slot.unresolved_note ? <p className="text-xs text-danger">{slot.unresolved_note}</p> : null}
              <div className="flex flex-col gap-2">
                {slot.options.map((option) => (
                  <article
                    key={`${option.rank}-${option.place.name}`}
                    className="flex gap-3 rounded-md border border-border bg-canvas p-3"
                  >
                    <OptionImage src={option.place.photos?.[0]} alt={option.place.name} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <h6 className="text-[0.92rem] font-semibold text-fg">{option.place.name}</h6>
                        <span className="text-xs font-bold text-faint">#{option.rank}</span>
                      </div>
                      <p className="text-sm leading-relaxed text-muted">{option.place.description}</p>
                      <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted">
                        <span>{option.place.category}</span>
                        <span>{option.place.price_range}</span>
                        {option.place.rating ? <span>★ {option.place.rating.toFixed(1)}</span> : null}
                        {formatDuration(option.estimated_duration_minutes ?? option.place.duration_minutes) ? (
                          <span>{formatDuration(option.estimated_duration_minutes ?? option.place.duration_minutes)}</span>
                        ) : null}
                      </div>
                      <p className={reasonClass}>{option.recommendation_reason}</p>
                      {option.best_time || option.crowd_warning ? (
                        <p className={noteClass}>
                          {option.best_time ? `Best time: ${option.best_time}. ` : ""}
                          {option.crowd_warning ?? ""}
                        </p>
                      ) : null}
                      <div className="mt-1 flex gap-3">
                        {option.place.google_maps_url ? (
                          <a className={linkClass} href={option.place.google_maps_url} target="_blank" rel="noreferrer">Maps</a>
                        ) : null}
                        {option.booking_url ? (
                          <a className={linkClass} href={option.booking_url} target="_blank" rel="noreferrer">Book</a>
                        ) : null}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          );
        })}
      </div>

      {day.food_options.length > 0 ? (
        <section className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between gap-2">
            <h6 className="text-sm font-semibold text-fg">Food and cafes</h6>
            <span className="text-xs text-muted">Recommendations for this day</span>
          </div>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
            {day.food_options.map((meal) => (
              <div key={meal.meal_type} className="flex flex-col gap-1">
                <h6 className="text-[0.85rem] font-semibold capitalize text-fg">{meal.meal_type}</h6>
                {meal.notes ? <p className="text-xs text-muted">{meal.notes}</p> : null}
                {meal.options.map((venue) => (
                  <article key={venue.name} className="flex gap-3 rounded-md border border-border bg-canvas p-2">
                    <OptionImage src={venue.photos?.[0]} alt={venue.name} />
                    <div className="min-w-0">
                      <strong className="text-sm text-fg">{venue.name}</strong>
                      <p className="text-xs text-muted">{venue.cuisine} · {venue.price_range} · ★ {venue.rating.toFixed(1)}</p>
                      <small className="block text-xs text-faint">{venue.address}</small>
                      {venue.google_maps_url ? (
                        <a className={linkClass} href={venue.google_maps_url} target="_blank" rel="noreferrer">Open in Maps</a>
                      ) : null}
                    </div>
                  </article>
                ))}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {day.stay_options && day.stay_options.options.length > 0 && showStay ? (
        <section className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between gap-2">
            <h6 className="text-sm font-semibold text-fg">Where to stay</h6>
            <span className="text-xs text-muted">{day.stay_options.notes ?? day.stay_options.location}</span>
          </div>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
            {day.stay_options.options.map((stay) => (
              <article key={stay.name} className="flex gap-3 rounded-md border border-border bg-canvas p-2">
                <OptionImage src={stay.photos?.[0]} alt={stay.name ?? "Stay"} />
                <div className="min-w-0">
                  <strong className="text-sm text-fg">{stay.name}</strong>
                  <p className="text-xs text-muted">
                    {stay.price_per_night?.toLocaleString()} {stay.currency_code}/night
                    {stay.rating ? ` · ★ ${stay.rating.toFixed(1)}` : ""}
                  </p>
                  <small className="block text-xs text-faint">{stay.address}</small>
                  {stay.personalization_reason ? (
                    <p className={reasonClass}>{stay.personalization_reason}</p>
                  ) : null}
                  {stay.booking_url ? (
                    <a className={linkClass} href={stay.booking_url} target="_blank" rel="noreferrer">Book</a>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {day.safety_briefing ? (
        <section className="flex flex-col gap-2">
          <span className={slotLabelClass}>Safety</span>
          <p className={noteClass}>{day.safety_briefing.summary}</p>
          {day.permits_required.length > 0 ? (
            <p className={noteClass}>Permits: {day.permits_required.join(", ")}</p>
          ) : null}
          {day.connectivity ? <p className={noteClass}>{day.connectivity}</p> : null}
        </section>
      ) : null}
    </article>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-border bg-canvas px-2 py-0.5 text-xs font-semibold text-muted">
      {children}
    </span>
  );
}
