/**
 * Frontend-owned types for the trip-planning SSE contract and rendered itinerary.
 * Mirrors backend/app/routers/trip.py, backend/app/models/itinerary.py,
 * backend/app/models/reports.py, and backend/app/models/clarification.py.
 */

export type PlanRequest = {
  query: string;
  session_id?: string;
};

export type ClarifyRequest = {
  answers: Record<string, string>;
};

// ── SSE event payloads ───────────────────────────────────────────────────────

export type AgentStartEvent = {
  agent: string;
  session_id: string;
};

export type AgentDoneEvent = {
  agent: string;
  layer: number;
  session_id: string;
  preview: string;
};

export type ClarificationPrompt = {
  field: string;
  question: string;
  reason: string;
  input_type: "text" | "date" | "number" | "select";
  options: string[];
  extracted_value: string | null;
};

export type NeedsClarificationEvent = {
  session_id: string;
  prompts: ClarificationPrompt[];
  round: number;
};

export type CompleteEvent = {
  itinerary_id: string;
  session_id: string;
  itinerary: Itinerary | null;
};

export type AgentUsage = {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  latency_ms: number;
};

export type UsageSummaryEvent = {
  session_id: string;
  total_tokens: number;
  total_cost_usd: number;
  total_latency_ms: number;
  per_agent: Record<string, AgentUsage>;
};

export type ErrorEvent = {
  message: string;
  session_id?: string;
};

export type TripStreamEvent =
  | { event: "agent_start"; data: AgentStartEvent }
  | { event: "agent_done"; data: AgentDoneEvent }
  | { event: "needs_clarification"; data: NeedsClarificationEvent }
  | { event: "complete"; data: CompleteEvent }
  | { event: "usage_summary"; data: UsageSummaryEvent }
  | { event: "error"; data: ErrorEvent };

// ── Itinerary rendering types (subset of backend/app/models/itinerary.py) ───

export type Place = {
  name: string;
  description: string;
  category: string;
  duration_minutes?: number;
  price_range: string;
  address: string;
  rating: number | null;
  review_count?: number | null;
  photos?: string[];
  google_maps_url?: string | null;
  more_images_url?: string | null;
  opening_hours?: {
    open: string;
    close: string;
    days: string[];
    notes: string | null;
  } | null;
};

export type ActivityOption = {
  place: Place;
  rank: number;
  recommendation_reason: string;
  best_for?: string[];
  estimated_duration_minutes?: number;
  best_time: string | null;
  crowd_warning: string | null;
  booking_url?: string | null;
};

export type TimeSlotOptions = {
  slot: string;
  options: ActivityOption[];
  notes: string | null;
  unresolved_note?: string | null;
};

export type FoodVenue = {
  name: string;
  category: string;
  cuisine: string;
  price_range: string;
  rating: number;
  address: string;
  lat?: number | null;
  lng?: number | null;
  google_maps_url?: string | null;
  photos?: string[];
  meal_types?: string[];
  dietary_tags?: string[];
  neighbourhood?: string | null;
  review_count?: number | null;
  booking_url?: string | null;
};

export type FoodOptions = {
  meal_type: string;
  options: FoodVenue[];
  notes: string | null;
};

export type Day = {
  date: string;
  day_number: number;
  location: string;
  morning: TimeSlotOptions;
  afternoon: TimeSlotOptions;
  evening: TimeSlotOptions;
  food: FoodOptions[];
  altitude_warning: string | null;
  is_travel_day: boolean;
  is_checkin_day?: boolean;
  is_checkout_day?: boolean;
};

export type StayOption = {
  name?: string;
  price_per_night?: number;
  rating?: number;
  address?: string;
  description?: string;
  photos?: string[];
  booking_url?: string;
  amenities?: string[];
  [key: string]: unknown;
};

export type StayOptions = {
  location: string;
  options: StayOption[];
  notes: string | null;
};

export type TripSegment = {
  location: string;
  days: Day[];
  stay_options: StayOptions | null;
  permits_required: string[];
  connectivity: string | null;
  drive_notes?: string | null;
  altitude_meters?: number | null;
  stop_id?: string | null;
  arrival_date?: string | null;
  departure_date?: string | null;
  check_in?: string | null;
  check_out?: string | null;
};

export type TransportRecommendation = {
  rationale?: string;
  mode?: string;
  [key: string]: unknown;
};

export type TransportSection = {
  recommended: TransportRecommendation | null;
  alternatives: TransportRecommendation[];
};

export type ApplicationCentre = {
  name: string;
  address: string;
  phone: string | null;
  opening_hours: string | null;
  booking_url: string | null;
};

export type VisaReport = {
  passport_country: string;
  destination_country: string;
  visa_required: boolean;
  visa_type: string | null;
  processing_timeline: string | null;
  fees: string | null;
  application_centre: ApplicationCentre | null;
  disclaimer: string;
};

export type BudgetReport = {
  currency_code: string;
  total_estimated_cost: number;
  total_in_source_currency: number | null;
  per_category_breakdown: Record<string, number>;
  vs_budget_verdict: string;
  cost_saving_tips: string[];
  per_person_cost: number | null;
};

export type ClarificationRequest = {
  field: string;
  question: string;
  required: boolean;
};

export type TripDates = {
  start_date?: string;
  end_date?: string;
  [key: string]: unknown;
};

export type Itinerary = {
  id: string | null;
  title: string;
  source: string;
  destination: string;
  destinations: string[];
  dates: TripDates | null;
  travelers: number;
  reality_banner: string | null;
  segments: TripSegment[];
  transport_section: TransportSection | null;
  safety_briefing: string | null;
  packing_tips: string[];
  connectivity_summary: string | null;
  visa_section: VisaReport | null;
  self_drive_section?: Record<string, unknown> | null;
  budget_breakdown: BudgetReport | null;
  clarifications_needed: ClarificationRequest[];
  language_tips: string | null;
  currency_tips: string | null;
};

// ── Planner UI state ─────────────────────────────────────────────────────────

export type PlannerStatus =
  | "idle"
  | "planning"
  | "awaiting_clarification"
  | "complete"
  | "downloading"
  | "error";

export type CompletedAgentActivity = {
  agent: string;
  label: string;
  preview: string;
  layer: number;
  elapsedMs: number;
};
