import { ItineraryDayCard } from "@/components/itinerary/itinerary-day-card";
import { ItineraryHero } from "@/components/itinerary/itinerary-hero";
import { ItineraryHighlights } from "@/components/itinerary/itinerary-highlights";
import { ItineraryDetails } from "@/components/itinerary/itinerary-details";
import { PdfDownloadButton } from "@/components/itinerary/pdf-download-button";
import { groupItineraryDays } from "@/lib/day-grouping";
import { daysToShowStay } from "@/lib/stay-dedupe";
import type { Itinerary } from "@/lib/types";

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
  const stayDays = daysToShowStay(itinerary.trip_days);
  const dayGroups = groupItineraryDays(itinerary.trip_days);

  return (
    <section className="flex min-w-0 flex-col gap-4">
      <ItineraryHero
        itinerary={itinerary}
      />

      <ItineraryHighlights
        transportSection={itinerary.transport_section}
        visaSection={itinerary.visa_section}
        safetySection={itinerary.safety_section}
        safetyBriefing={itinerary.safety_briefing}
      />

      <div className="flex flex-col gap-10">
        {dayGroups.map(({ day, dayNumbers }) => {
          return (
            <div
              key={dayNumbers[0]}
              id={`day-${dayNumbers[0]}`}
              data-day={dayNumbers[0]}
              className="scroll-mt-4"
            >
              <ItineraryDayCard
                day={day}
                dayNumbers={dayNumbers}
                showStay={stayDays.has(day.day_number)}
              />
            </div>
          );
        })}
        <div className="h-px w-full bg-border" aria-hidden="true" />
      </div>

      <ItineraryDetails itinerary={itinerary} />

      <footer className="flex justify-center px-4 pb-8 pt-12">
        <PdfDownloadButton
          onDownload={onDownloadPdf}
          disabled={!itinerary.id}
          isDownloading={isPdfDownloading}
          error={pdfError}
        />
      </footer>
    </section>
  );
}
