import { ItineraryDayCard } from "@/components/itinerary/itinerary-day-card";
import { ItineraryHighlights } from "@/components/itinerary/itinerary-highlights";
import { ItineraryDetails } from "@/components/itinerary/itinerary-details";
import { PdfDownloadButton } from "@/components/itinerary/pdf-download-button";
import type { Itinerary } from "@/lib/types";
import styles from "./itinerary-response.module.css";

type ItineraryResponseProps = {
  itinerary: Itinerary;
  onDownloadPdf: () => void;
  isPdfDownloading: boolean;
  pdfError: string | null;
};

export function ItineraryResponse({
  itinerary,
  onDownloadPdf,
  isPdfDownloading,
  pdfError,
}: ItineraryResponseProps) {
  return (
    <section className={styles.wrapper}>
      <header className={styles.header}>
        <div>
          <h2 className={styles.title}>{itinerary.title}</h2>
          <p className={styles.route}>
            {itinerary.source} → {itinerary.destinations?.join(" → ") || itinerary.destination}
          </p>
          <p className={styles.meta}>
            {itinerary.travelers} traveler{itinerary.travelers === 1 ? "" : "s"}
          </p>
        </div>
        <PdfDownloadButton
          onDownload={onDownloadPdf}
          disabled={!itinerary.id}
          isDownloading={isPdfDownloading}
          error={pdfError}
        />
      </header>

      {itinerary.reality_banner ? (
        <p className={styles.banner}>{itinerary.reality_banner}</p>
      ) : null}

      <ItineraryHighlights
        transportSection={itinerary.transport_section}
        budgetBreakdown={itinerary.budget_breakdown}
        safetyBriefing={itinerary.safety_briefing}
        visaSection={itinerary.visa_section}
      />

      {itinerary.segments.map((segment) => (
        <div key={segment.location} className={styles.segment}>
          <h3 className={styles.segmentTitle}>{segment.location}</h3>
          <div className={styles.days}>
            {segment.days.map((day) => (
              <ItineraryDayCard key={`${segment.location}-${day.day_number}`} day={day} />
            ))}
          </div>
        </div>
      ))}

      <ItineraryDetails itinerary={itinerary} />
    </section>
  );
}
