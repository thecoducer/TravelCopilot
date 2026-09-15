import { ItineraryDayCard } from "@/components/itinerary/itinerary-day-card";
import { ItineraryDayNav } from "@/components/itinerary/itinerary-day-nav";
import { ItineraryHero } from "@/components/itinerary/itinerary-hero";
import { ItineraryHighlights } from "@/components/itinerary/itinerary-highlights";
import { ItineraryDetails } from "@/components/itinerary/itinerary-details";
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

  return (
    <section className="grid grid-cols-[180px_minmax(0,1fr)] items-start gap-5 max-[900px]:grid-cols-1">
      <aside className="relative">
        <ItineraryDayNav days={itinerary.trip_days} />
      </aside>

      <div className="flex min-w-0 flex-col gap-4">
        <ItineraryHero
          itinerary={itinerary}
          onDownloadPdf={onDownloadPdf}
          isPdfDownloading={isPdfDownloading}
          pdfError={pdfError}
        />

        <ItineraryHighlights
          transportSection={itinerary.transport_section}
          budgetBreakdown={itinerary.budget_breakdown}
          safetyBriefing={itinerary.safety_briefing}
          visaSection={itinerary.visa_section}
        />

        <div className="flex flex-col gap-4">
          {itinerary.trip_days.map((day, index) => {
            const isNewStop = day.location !== itinerary.trip_days[index - 1]?.location;
            return (
              <div
                key={day.day_number}
                id={`day-${day.day_number}`}
                data-day={day.day_number}
                className="scroll-mt-4"
              >
                {isNewStop ? (
                  <h3 className="mb-2 mt-4 font-display text-[1.15rem] font-bold tracking-tight text-fg">
                    {day.location}
                  </h3>
                ) : null}
                <ItineraryDayCard day={day} showStay={stayDays.has(day.day_number)} />
              </div>
            );
          })}
        </div>

        <ItineraryDetails itinerary={itinerary} />
      </div>
    </section>
  );
}
