import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TopScamsPanel } from "@/components/itinerary/top-scams-panel";
import { ItineraryDetails } from "@/components/itinerary/itinerary-details";
import type { Itinerary } from "@/lib/types";

const scam = {
  name: "Fake taxi meter",
  description: "A driver may claim the meter is broken and demand an inflated fare.",
  how_to_avoid: "Confirm the fare before leaving or use a licensed taxi app.",
};
const scams = [scam];
const manyScams = [
  scam,
  { name: "Scam two", description: "Description two", how_to_avoid: "Avoid two" },
  { name: "Scam three", description: "Description three", how_to_avoid: "Avoid three" },
];

function itinerary(overrides: Partial<Itinerary> = {}): Itinerary {
  return {
    id: null,
    title: "Test trip",
    source: "Kolkata",
    dates: null,
    travelers: 1,
    trip_days: [],
    transport_section: null,
    safety_section: null,
    safety_briefing: null,
    visa_section: null,
    budget_breakdown: null,
    reality_banner: null,
    packing_tips: ["Comfortable shoes"],
    permits_required: [],
    connectivity_summary: "Wi-Fi is common in central areas.",
    language_tips: "Carry a translation app.",
    currency_tips: "Keep some cash on hand.",
    clarifications_needed: [],
    ...overrides,
  };
}

describe("TopScamsPanel", () => {
  it("renders scam details and avoidance guidance", () => {
    render(<TopScamsPanel scams={scams} />);

    expect(screen.getByRole("heading", { name: "Top scams to avoid" })).toBeInTheDocument();
    expect(screen.getByText("Fake taxi meter")).toBeInTheDocument();
    expect(screen.getByText(scam.description)).toBeInTheDocument();
    expect(screen.getByText(scam.how_to_avoid)).toBeInTheDocument();
  });

  it("renders nothing when no scams are available", () => {
    const { container } = render(<TopScamsPanel scams={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("hides the expander when two scams fit in the initial view", () => {
    render(<TopScamsPanel scams={[scam, { name: "Scam two", description: "Description two", how_to_avoid: "Avoid two" }]} />);

    expect(screen.queryByRole("button", { name: "Show all" })).not.toBeInTheDocument();
  });

  it("shows two scams initially and expands to show all", () => {
    render(<TopScamsPanel scams={manyScams} />);

    expect(screen.getByText("Fake taxi meter")).toBeInTheDocument();
    expect(screen.getByText("Scam two")).toBeInTheDocument();
    expect(screen.queryByText("Scam three")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show all" }));

    expect(screen.getByText("Scam three")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Hide" }));

    expect(screen.queryByText("Scam three")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show all" })).toBeInTheDocument();
  });
});

describe("ItineraryDetails", () => {
  it("shows practical details without a disclosure wrapper", () => {
    render(
      <ItineraryDetails
        itinerary={itinerary({
          safety_section: {
            destination: "Osaka",
            advisory_level: "low",
            top_scams: scams,
            women_safety_notes: "Use licensed taxis after dark.",
            medical_facilities: "Osaka City General Hospital has emergency care.",
          },
        })}
      />,
    );

    expect(screen.getByRole("heading", { name: "Top scams to avoid" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Practical details" })).toBeInTheDocument();
    expect(screen.getByText("Wi-Fi is common in central areas.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Read more" }));
    expect(screen.getByText("Comfortable shoes")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Women's safety notes" })).toBeInTheDocument();
    expect(screen.getByText("Use licensed taxis after dark.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Medical facilities" })).toBeInTheDocument();
    expect(screen.getByText("Osaka City General Hospital has emergency care.")).toBeInTheDocument();
    expect(screen.queryByText("Practical details")?.closest("details")).toBeNull();
  });

  it("hides Read more when fewer than two practical details are available", () => {
    render(
      <ItineraryDetails
        itinerary={itinerary({
          packing_tips: [],
          connectivity_summary: "Wi-Fi is common in central areas.",
          language_tips: null,
          currency_tips: null,
        })}
      />,
    );

    expect(screen.getByRole("heading", { name: "Practical details" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read more" })).not.toBeInTheDocument();
  });
});
