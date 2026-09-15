/**
 * Frontend-owned types for the trip-planning SSE contract and rendered itinerary.
 * Mirrors backend/app/routers/trip.py, backend/app/models/itinerary.py,
 * backend/app/models/reports.py, and backend/app/models/clarification.py.
 */

export type PlanRequest = {
  query: string;
  session_id?: string;
  username?: string;
  mode?: "new" | "followup";
};

export type ClarifyRequest = {
  answers: Record<string, string>;
};

// ── User identity, profile, and sessions ─────────────────────────────────────

export type SessionSummary = {
  session_id: string;
  title: string;
  created_at: string;
  has_itinerary: boolean;
};

export type ChatTurn = {
  turn_index: number;
  role: "user" | "assistant";
  content: string;
  trip_id: string | null;
  intent: string | null;
  created_at: string;
};

export type UserProfileData = {
  user_id: string;
  username?: string | null;
  display_name?: string | null;
  home_city?: string | null;
  nationality?: string | null;
  passport_country?: string | null;
  preferred_currency?: string;
  total_budget?: number | null;
  per_day_budget?: number | null;
  budget_currency?: string;
  dietary_restrictions?: string[];
  preferred_cuisines?: string[];
  food_preferences_configured?: boolean;
  accessibility_needs?: string[];
  interests?: string[];
  preferred_airlines?: string[];
  preferred_hotel_chains?: string[];
  hotel_style?: string | null;
  budget_tier?: string;
  travel_style?: string | null;
  fitness_level?: string | null;
  altitude_experience?: boolean | null;
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

export type StayOption = {
  name?: string;
  price_per_night?: number;
  currency_code?: string;
  rating?: number;
  review_count?: number;
  address?: string;
  city?: string;
  description?: string;
  photos?: string[];
  booking_url?: string;
  google_maps_url?: string | null;
  amenities?: string[];
  hotel_style?: string | null;
  price_tier?: string | null;
  personalization_reason?: string | null;
  price_disclaimer?: string | null;
  check_in?: string | null;
  check_out?: string | null;
  free_cancellation_until?: string | null;
};

export type StayOptions = {
  location: string;
  options: StayOption[];
  recommended: StayOption | null;
  notes: string | null;
  stop_id?: string | null;
  nights_at_location?: number;
  is_checkin_day?: boolean;
  is_checkout_day?: boolean;
  check_in?: string | null;
  check_out?: string | null;
};

export type TransportOptions = {
  origin: string;
  destination: string;
  leg_id?: string | null;
  leg_type?: string | null;
  departure_date?: string | null;
  recommended: TransportRecommendation | null;
  alternatives: TransportRecommendation[];
  notes?: string | null;
  mode_downgraded?: boolean;
  no_result?: boolean;
};

export type ScamEntry = {
  name: string;
  description: string;
  how_to_avoid: string;
};

export type ReviewSummary = {
  place_name: string;
  rating: number | null;
  review_count: number | null;
  pros: string[];
  cons: string[];
  sentiment: string | null;
  google_maps_url?: string | null;
};

/** One calendar day — self-describing, mirrors backend ``TripDays``. */
export type TripDays = {
  day_number: number;
  date: string;
  location: string;
  summary: string | null;
  morning: TimeSlotOptions;
  afternoon: TimeSlotOptions;
  evening: TimeSlotOptions;
  food_options: FoodOptions[];
  stay_options: StayOptions | null;
  transport_options: TransportOptions[];
  review_highlights: ReviewSummary[];
  permits_required: string[];
  altitude_meters: number | null;
  connectivity: string | null;
  drive_notes: string | null;
  estimated_cost: number | null;
  currency_code: string | null;
  stop_id?: string | null;
  leg_id?: string | null;
  is_travel_day: boolean;
  is_checkin_day?: boolean;
  is_checkout_day?: boolean;
};

export type TransportRecommendation = {
  rationale?: string;
  mode?: string;
  recommended_legs?: RouteLeg[];
  total_cost?: number | null;
  total_duration_minutes?: number | null;
  currency_code?: string | null;
  personalization_reason?: string | null;
  non_obvious_insight?: string | null;
  route_label?: string | null;
  [key: string]: unknown;
};

export type RouteLeg = {
  mode?: string;
  operator?: string | null;
  origin?: string;
  destination?: string;
  departure_time?: string | null;
  arrival_time?: string | null;
  duration_minutes?: number | null;
  cost?: number | null;
  currency_code?: string | null;
  booking_url?: string | null;
  seat_class?: string | null;
  flight_number?: string | null;
  stops?: number | null;
  layover_at?: string | null;
  baggage_allowance?: string | null;
  cancellation_policy?: string | null;
  price_disclaimer?: string | null;
};

export type TransportSection = {
  recommended: TransportRecommendation | null;
  alternatives: TransportRecommendation[];
  by_leg?: Record<string, TransportRecommendation>;
};

export type ApplicationCentre = {
  name: string;
  address: string;
  phone: string | null;
  opening_hours: string | null;
  booking_url: string | null;
  google_maps_url?: string | null;
};

export type VisaSource = {
  title: string;
  url: string;
  published_or_fetched_date?: string | null;
};

export type VisaReport = {
  passport_country: string;
  destination_country: string;
  visa_required: boolean;
  visa_type: string | null;
  application_process?: string[];
  documents_required?: string[];
  processing_timeline: string | null;
  fees: string | null;
  dos_and_donts?: string[];
  nearest_embassy?: ApplicationCentre | null;
  application_centre: ApplicationCentre | null;
  apply_online_url?: string | null;
  validity_notes?: string | null;
  sources?: VisaSource[];
  last_verified_at?: string | null;
  confidence?: string | null;
  disclaimer: string;
};

export type FxRateEntry = {
  rate: number;
  fetched_at?: string | null;
};

export type BudgetReport = {
  currency_code: string;
  total_estimated_cost: number;
  total_in_source_currency: number | null;
  fx_rates_used?: Record<string, FxRateEntry>;
  fx_disclaimer?: string | null;
  per_category_breakdown: Record<string, number>;
  per_day_breakdown?: number[];
  vs_budget_verdict: string;
  cost_saving_tips: string[];
  per_person_cost: number | null;
  permit_costs?: number | null;
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

export type SafetyReport = {
  destination: string;
  advisory_level: string;
  season_label?: string | null;
  crowd_level?: string | null;
  seasonal_weather_summary?: string | null;
  seasonal_risks?: string[];
  altitude_meters?: number | null;
  acclimatization_advice?: string | null;
  top_scams?: ScamEntry[];
  safe_areas?: string[];
  emergency_contacts?: Record<string, string>;
  women_safety_notes?: string | null;
  medical_facilities?: string | null;
  insurance_recommendation?: string | null;
};

export type Itinerary = {
  id: string | null;
  title: string;
  source: string;
  dates: TripDates | null;
  travelers: number;
  trip_days: TripDays[];
  transport_section: TransportSection | null;
  safety_section: SafetyReport | null;
  safety_briefing: string | null;
  visa_section: VisaReport | null;
  self_drive_section?: Record<string, unknown> | null;
  budget_breakdown: BudgetReport | null;
  reality_banner: string | null;
  packing_tips: string[];
  permits_required: string[];
  connectivity_summary: string | null;
  language_tips: string | null;
  currency_tips: string | null;
  clarifications_needed: ClarificationRequest[];
  version?: number;
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
