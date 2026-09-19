"use client";

import { BudgetCostBreakdown } from "@/components/itinerary/budget-cost-breakdown";
import { ItineraryDayCard } from "@/components/itinerary/itinerary-day-card";
import { ItineraryHero } from "@/components/itinerary/itinerary-hero";
import { PracticalDetails } from "@/components/itinerary/practical-details";
import { TopScamsPanel } from "@/components/itinerary/top-scams-panel";
import { TransportDetails } from "@/components/itinerary/transport-details";
import { VisaDetails } from "@/components/itinerary/visa-details";
import { PdfDownloadButton } from "@/components/itinerary/pdf-download-button";
import type { Itinerary } from "@/lib/types";

type ItineraryDetailsProps = {
  itinerary: Itinerary;
  onDownloadPdf?: () => void;
  isPdfDownloading?: boolean;
  pdfError?: string | null;
};

export function ItineraryDetails({
  itinerary,
  onDownloadPdf,
  isPdfDownloading = false,
  pdfError = null,
}: ItineraryDetailsProps) {
  return (
    <section className="flex min-w-0 flex-col gap-4">
      <ItineraryHero itinerary={itinerary} />

      <div className="flex flex-col gap-10">
        {itinerary.trip_days.map((day) => (
          <div
            key={day.day_number}
            id={`day-${day.day_number}`}
            data-day={day.day_number}
            className="scroll-mt-4 [content-visibility:auto] [contain-intrinsic-size:auto_720px]"
          >
            <ItineraryDayCard day={day} />
          </div>
        ))}
      </div>

      <TransportDetails itinerary={itinerary} />

      <div className="flex flex-col gap-3">
        <BudgetCostBreakdown budget={itinerary.budget_breakdown} />
        <VisaDetails itinerary={itinerary} />
        <TopScamsPanel scams={itinerary.safety_section?.top_scams ?? []} />
        <PracticalDetails itinerary={itinerary} />
      </div>

      {onDownloadPdf ? (
        <footer className="flex justify-center px-4 pb-8 pt-12">
          <PdfDownloadButton
            onDownload={onDownloadPdf}
            disabled={!itinerary.id}
            isDownloading={isPdfDownloading}
            error={pdfError}
          />
        </footer>
      ) : null}
    </section>
  );
}
