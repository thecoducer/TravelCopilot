import type { Itinerary, StayOption, TripSegment, TransportRecommendation } from "@/lib/types";
import Image from "next/image";
import styles from "./itinerary-details.module.css";

type ItineraryDetailsProps = {
  itinerary: Itinerary;
};

function displayValue(value: unknown): string | null {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.filter((item) => typeof item === "string").join(", ");
  return null;
}

function DetailList({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value).filter(([key, item]) => key !== "photos" && displayValue(item));
  if (entries.length === 0) return null;

  return (
    <dl className={styles.detailList}>
      {entries.map(([key, item]) => (
        <div key={key}>
          <dt>{key.replaceAll("_", " ")}</dt>
          <dd>{displayValue(item)}</dd>
        </div>
      ))}
    </dl>
  );
}

function StayCard({ stay }: { stay: StayOption }) {
  const image = stay.photos?.[0];
  return (
    <article className={styles.stayCard}>
      {image ? (
        <Image
          className={styles.stayImage}
          src={image}
          alt={stay.name ?? "Accommodation"}
          width={84}
          height={84}
          unoptimized
        />
      ) : null}
      <div>
        <h5>{stay.name ?? "Accommodation option"}</h5>
        <div className={styles.stayMeta}>
          {stay.rating ? <span>★ {stay.rating.toFixed(1)}</span> : null}
          {stay.price_per_night ? <span>{stay.price_per_night} per night</span> : null}
        </div>
        {stay.description ? <p>{stay.description}</p> : null}
        {stay.address ? <small>{stay.address}</small> : null}
        {stay.booking_url ? (
          <a href={stay.booking_url} target="_blank" rel="noreferrer">View booking</a>
        ) : null}
      </div>
    </article>
  );
}

function SegmentDetails({ segment }: { segment: TripSegment }) {
  const stayOptions = segment.stay_options?.options ?? [];
  const stayRecords = stayOptions.filter((option): option is StayOption => typeof option === "object" && option !== null);

  return (
    <section className={styles.segmentDetails}>
      <div className={styles.segmentFacts}>
        {segment.drive_notes ? <div><strong>Getting there</strong><span>{segment.drive_notes}</span></div> : null}
        {segment.connectivity ? <div><strong>Connectivity</strong><span>{segment.connectivity}</span></div> : null}
        {segment.altitude_meters ? <div><strong>Altitude</strong><span>{segment.altitude_meters.toLocaleString()} m</span></div> : null}
        {segment.check_in ? <div><strong>Check-in</strong><span>{segment.check_in}</span></div> : null}
        {segment.check_out ? <div><strong>Check-out</strong><span>{segment.check_out}</span></div> : null}
      </div>

      {segment.permits_required.length > 0 ? (
        <div className={styles.infoBlock}>
          <h5>Permits and requirements</h5>
          <ul>{segment.permits_required.map((permit) => <li key={permit}>{permit}</li>)}</ul>
        </div>
      ) : null}

      {stayRecords.length > 0 || segment.stay_options?.notes ? (
        <div className={styles.infoBlock}>
          <div className={styles.sectionHeader}>
            <h5>Hotels and stays</h5>
            {segment.stay_options?.notes ? <p>{segment.stay_options.notes}</p> : null}
          </div>
          <div className={styles.stayGrid}>{stayRecords.map((stay, index) => <StayCard key={`${stay.name ?? "stay"}-${index}`} stay={stay} />)}</div>
        </div>
      ) : null}
    </section>
  );
}

function TransportDetails({ itinerary }: { itinerary: Itinerary }) {
  const section = itinerary.transport_section;
  if (!section) return null;
  const recommendations = [section.recommended, ...section.alternatives].filter(
    (item): item is TransportRecommendation => Boolean(item),
  );

  return (
    <section className={styles.panel}>
      <div className={styles.sectionHeader}>
        <div><span className={styles.eyebrow}>Route logistics</span><h4>Transport details</h4></div>
        <span className={styles.count}>{recommendations.length} option{recommendations.length === 1 ? "" : "s"}</span>
      </div>
      <div className={styles.transportGrid}>
        {recommendations.map((recommendation, index) => (
          <article key={`${recommendation.mode ?? "transport"}-${index}`} className={styles.transportCard}>
            <h5>{recommendation.mode ?? (index === 0 ? "Recommended route" : "Alternative route")}</h5>
            {recommendation.rationale ? <p>{recommendation.rationale}</p> : null}
            <DetailList value={recommendation} />
          </article>
        ))}
      </div>
    </section>
  );
}

function TripFacts({ itinerary }: { itinerary: Itinerary }) {
  const dates = itinerary.dates;
  const dateEntries = dates
    ? Object.entries(dates).filter(([, value]) => displayValue(value))
    : [];
  const budget = itinerary.budget_breakdown;
  const visa = itinerary.visa_section;
  const selfDrive = itinerary.self_drive_section;

  if (dateEntries.length === 0 && !budget && !visa && !selfDrive) return null;

  return (
    <section className={styles.panel}>
      <span className={styles.eyebrow}>Trip essentials</span>
      <h4>Dates, budget and requirements</h4>
      <div className={styles.practicalGrid}>
        {dateEntries.length > 0 ? (
          <div>
            <h5>Travel dates</h5>
            <DetailList value={Object.fromEntries(dateEntries)} />
          </div>
        ) : null}
        {budget ? (
          <div>
            <h5>Budget breakdown</h5>
            <p>{budget.currency_code} {budget.total_estimated_cost.toLocaleString()} · {budget.vs_budget_verdict}</p>
            <DetailList value={budget.per_category_breakdown} />
            {budget.cost_saving_tips.length > 0 ? (
              <ul>{budget.cost_saving_tips.map((tip) => <li key={tip}>{tip}</li>)}</ul>
            ) : null}
          </div>
        ) : null}
        {visa ? (
          <div>
            <h5>Visa and entry</h5>
            <p>{visa.visa_required ? `Visa required${visa.visa_type ? ` · ${visa.visa_type}` : ""}` : "Visa not required"}</p>
            <DetailList value={visa as unknown as Record<string, unknown>} />
            {visa.application_centre ? (
              <p>Application centre: {visa.application_centre.name}, {visa.application_centre.address}</p>
            ) : null}
          </div>
        ) : null}
        {selfDrive ? (
          <div>
            <h5>Self-drive plan</h5>
            <DetailList value={selfDrive} />
          </div>
        ) : null}
      </div>
    </section>
  );
}

function PracticalDetails({ itinerary }: { itinerary: Itinerary }) {
  const sections = [
    itinerary.connectivity_summary ? { title: "Connectivity", value: itinerary.connectivity_summary } : null,
    itinerary.language_tips ? { title: "Language tips", value: itinerary.language_tips } : null,
    itinerary.currency_tips ? { title: "Money tips", value: itinerary.currency_tips } : null,
    itinerary.safety_briefing ? { title: "Safety briefing", value: itinerary.safety_briefing } : null,
  ].filter((item): item is { title: string; value: string } => item !== null);

  if (sections.length === 0 && itinerary.packing_tips.length === 0) return null;

  return (
    <section className={styles.panel}>
      <span className={styles.eyebrow}>Before you go</span>
      <h4>Practical details</h4>
      <div className={styles.practicalGrid}>
        {sections.map((section) => <div key={section.title}><h5>{section.title}</h5><p>{section.value}</p></div>)}
        {itinerary.packing_tips.length > 0 ? (
          <div><h5>Packing list</h5><ul>{itinerary.packing_tips.map((tip) => <li key={tip}>{tip}</li>)}</ul></div>
        ) : null}
      </div>
    </section>
  );
}

export function ItineraryDetails({ itinerary }: ItineraryDetailsProps) {
  return (
    <div className={styles.details}>
      <TripFacts itinerary={itinerary} />
      <TransportDetails itinerary={itinerary} />
      <section className={styles.panel}>
        <span className={styles.eyebrow}>Where you will stay</span>
        <h4>Hotels by stop</h4>
        <div className={styles.segmentList}>
          {itinerary.segments.map((segment) => (
            <div key={`${segment.location}-${segment.stop_id ?? "segment"}`}>
              <h5>{segment.location}</h5>
              <SegmentDetails segment={segment} />
            </div>
          ))}
        </div>
      </section>
      <PracticalDetails itinerary={itinerary} />
    </div>
  );
}
