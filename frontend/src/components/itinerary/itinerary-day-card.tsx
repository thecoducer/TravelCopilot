import type { Day } from "@/lib/types";
import Image from "next/image";
import styles from "./itinerary-day-card.module.css";

type ItineraryDayCardProps = {
  day: Day;
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
      className={styles.image}
      src={src}
      alt={alt}
      width={96}
      height={82}
      unoptimized
    />
  );
}

/** Renders every planned activity and food option for one day. */
export function ItineraryDayCard({ day }: ItineraryDayCardProps) {
  return (
    <article className={styles.card}>
      <header className={styles.header}>
        <h5 className={styles.title}>
          Day {day.day_number} — {day.location}
        </h5>
        <span className={styles.date}>{day.date}</span>
      </header>

      <div className={styles.badges}>
        {day.is_travel_day ? <span className={styles.badge}>Travel day</span> : null}
        {day.is_checkin_day ? <span className={styles.badge}>Check-in</span> : null}
        {day.is_checkout_day ? <span className={styles.badge}>Check-out</span> : null}
      </div>
      {day.altitude_warning ? <p className={styles.warning}>{day.altitude_warning}</p> : null}

      <div className={styles.slots}>
        {SLOTS.map(({ key, label }) => {
          const slot = day[key];
          if (slot.options.length === 0 && !slot.notes && !slot.unresolved_note) {
            return null;
          }
          return (
            <section key={key} className={styles.slot}>
              <div className={styles.slotHeading}>
                <span className={styles.slotLabel}>{label}</span>
                {slot.notes ? <span className={styles.slotNotes}>{slot.notes}</span> : null}
              </div>
              {slot.unresolved_note ? <p className={styles.unresolved}>{slot.unresolved_note}</p> : null}
              <div className={styles.options}>
                {slot.options.map((option) => (
                  <article key={`${option.rank}-${option.place.name}`} className={styles.option}>
                    <OptionImage src={option.place.photos?.[0]} alt={option.place.name} />
                    <div className={styles.optionBody}>
                      <div className={styles.optionTitleRow}>
                        <h6 className={styles.optionTitle}>{option.place.name}</h6>
                        <span className={styles.rank}>#{option.rank}</span>
                      </div>
                      <p className={styles.description}>{option.place.description}</p>
                      <div className={styles.metaRow}>
                        <span>{option.place.category}</span>
                        <span>{option.place.price_range}</span>
                        {option.place.rating ? <span>★ {option.place.rating.toFixed(1)}</span> : null}
                        {formatDuration(option.estimated_duration_minutes ?? option.place.duration_minutes) ? (
                          <span>{formatDuration(option.estimated_duration_minutes ?? option.place.duration_minutes)}</span>
                        ) : null}
                      </div>
                      <p className={styles.reason}>{option.recommendation_reason}</p>
                      {option.best_time || option.crowd_warning ? (
                        <p className={styles.note}>
                          {option.best_time ? `Best time: ${option.best_time}. ` : ""}
                          {option.crowd_warning ?? ""}
                        </p>
                      ) : null}
                      <div className={styles.links}>
                        {option.place.google_maps_url ? (
                          <a href={option.place.google_maps_url} target="_blank" rel="noreferrer">Maps</a>
                        ) : null}
                        {option.booking_url ? (
                          <a href={option.booking_url} target="_blank" rel="noreferrer">Book</a>
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

      {day.food.length > 0 ? (
        <section className={styles.foodSection}>
          <div className={styles.sectionHeading}>
            <h6>Food and cafes</h6>
            <span>Recommendations for this day</span>
          </div>
          <div className={styles.foodGrid}>
            {day.food.map((meal) => (
              <div key={meal.meal_type} className={styles.meal}>
                <h6 className={styles.mealTitle}>{meal.meal_type}</h6>
                {meal.notes ? <p className={styles.slotNotes}>{meal.notes}</p> : null}
                {meal.options.map((venue) => (
                  <article key={venue.name} className={styles.foodOption}>
                    <OptionImage src={venue.photos?.[0]} alt={venue.name} />
                    <div>
                      <strong>{venue.name}</strong>
                      <p>{venue.cuisine} · {venue.price_range} · ★ {venue.rating.toFixed(1)}</p>
                      <small>{venue.address}</small>
                      {venue.google_maps_url ? (
                        <a href={venue.google_maps_url} target="_blank" rel="noreferrer">Open in Maps</a>
                      ) : null}
                    </div>
                  </article>
                ))}
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </article>
  );
}
