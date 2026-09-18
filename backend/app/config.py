from __future__ import annotations

from pathlib import Path
from typing import Final

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Shared tool-runtime constants. Keeping these values here makes provider adapters
# configurable without scattering protocol names, statuses, or retention policy.
TOOL_RESPONSE_SCHEMA_VERSION = 1
TOOL_RESPONSE_EXECUTION_MODE_KEY = "execution_mode"
TOOL_RESPONSE_REAL_MODE = "real"
TOOL_RESPONSE_STATUS_SUCCESS = "success"
TOOL_RESPONSE_STATUS_PARTIAL = "partial"
TOOL_RESPONSE_STATUS_ERROR = "error"
TOOL_RESPONSE_REPLAY_HIT = "replay_hit"
TOOL_RESPONSE_REPLAY_MISS = "replay_miss"
TOOL_RESPONSE_REPLAY_DISABLED = "replay_disabled"
TOOL_RESPONSE_META_KEY = "_meta"
TOOL_RESPONSE_ERROR_KEY = "error"
TOOL_RESPONSE_META_STATUS_KEY = "status"
TOOL_RESPONSE_META_PROVIDER_KEY = "provider"
TOOL_RESPONSE_META_REPLAY_KEY = "replay"
TOOL_RESPONSE_META_RETRY_COUNT_KEY = "retry_count"
TOOL_RESPONSE_META_DURATION_MS_KEY = "duration_ms"
TOOL_RESPONSE_META_REQUEST_FINGERPRINT_KEY = "request_fingerprint"
TOOL_RESPONSE_META_FETCHED_AT_KEY = "fetched_at"
TOOL_RESPONSE_META_ERROR_KEY = "error"
TOOL_RESPONSE_SCHEMA_VERSION_KEY = "schema_version"
TOOL_RESPONSE_TOOL_NAME_KEY = "tool_name"
TOOL_RESPONSE_PROVIDER_KEY = "provider"
TOOL_RESPONSE_RECORDED_AT_KEY = "recorded_at"
TOOL_RESPONSE_ARGUMENTS_KEY = "arguments"
TOOL_RESPONSE_EXCHANGES_KEY = "exchanges"
TOOL_RESPONSE_NORMALIZED_RESULT_KEY = "normalized_result"
TOOL_RESPONSE_STATUS_KEY = "status"
TOOL_RESPONSE_ERROR_FIELD_KEY = "error"
TOOL_RUNTIME_KEY = "__tool_runtime"
TOOL_RUNTIME_EXCHANGES_KEY = "exchanges"
TOOL_RUNTIME_RETRY_COUNT_KEY = "retry_count"
TOOL_RUNTIME_DURATION_MS_KEY = "duration_ms"
TOOL_RUNTIME_ERROR_KEY = "error"
TOOL_RUNTIME_STATUS_KEY = "status"
PROVIDER_APPLICATION = "application"
PROVIDER_SERPAPI = "serpapi"
PROVIDER_TAVILY = "tavily"
PROVIDER_GOOGLE = "google"
PROVIDER_OPEN_EXCHANGE_RATES = "open_exchange_rates"
TOOL_RESPONSE_FILENAME_SEPARATOR = "-"
TOOL_RESPONSE_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S.%fZ"
TOOL_RESPONSE_FINGERPRINT_PREFIX = "sha256:"
TOOL_RESPONSE_TEMP_SUFFIX = ".tmp"
TOOL_RESPONSE_JSON_SUFFIX = ".json"
TOOL_RESPONSE_REDACTED_VALUE = "[REDACTED]"
TOOL_RESPONSE_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
)
TOOL_RESPONSE_SENSITIVE_QUERY_KEYS = {
    "api_key",
    "app_id",
    "key",
    "access_token",
    "token",
    "secret",
}

EXTERNAL_API_DEFAULT_HTTP_HEADERS = {"Accept": "application/json"}
SERPAPI_FLIGHTS_ENGINE = "google_flights"
SERPAPI_FLIGHTS_AUTOCOMPLETE_ENGINE = "google_flights_autocomplete"
SERPAPI_HOTELS_ENGINE = "google_hotels"
SERPAPI_ONE_WAY_TYPE = "2"
ISO_CURRENCY_CODE_LENGTH = 3
HTTP_HEADER_AUTHORIZATION = "Authorization"
HTTP_HEADER_CONTENT_TYPE = "Content-Type"
HTTP_HEADER_JSON = "application/json"
HTTP_HEADER_GOOGLE_API_KEY = "X-Goog-Api-Key"
HTTP_HEADER_GOOGLE_FIELD_MASK = "X-Goog-FieldMask"
HTTP_AUTH_BEARER_PREFIX = "Bearer "
GOOGLE_GEOCODE_FIELD_MASK = (
    "results.placeId,results.location,results.formattedAddress,results.granularity"
)
GOOGLE_ROUTES_FIELD_MASK = "routes.duration,routes.distanceMeters,routes.description,routes.legs"
GOOGLE_MATRIX_FIELD_MASK = "originIndex,destinationIndex,status,condition,distanceMeters,duration"
GOOGLE_PLACES_SEARCH_FIELD_MASK = (
    "places.id,places.name,places.displayName,places.formattedAddress,places.location,"
    "places.primaryType,places.primaryTypeDisplayName,places.rating,places.userRatingCount,"
    "places.googleMapsUri,places.websiteUri,places.nationalPhoneNumber,places.photos,"
    "places.regularOpeningHours,places.businessStatus"
)
GOOGLE_PLACES_DETAILS_FIELD_MASK = (
    "id,name,displayName,formattedAddress,location,rating,userRatingCount,googleMapsUri,"
    "websiteUri,nationalPhoneNumber,regularOpeningHours,currentOpeningHours,reviews,photos,"
    "businessStatus"
)
GOOGLE_TRAVEL_MODE_DRIVE = "DRIVE"
GOOGLE_TRAVEL_MODE_TRANSIT = "TRANSIT"
GOOGLE_ROUTING_PREFERENCE_TRAFFIC_AWARE = "TRAFFIC_AWARE"
GOOGLE_ROUTE_MATRIX_OK_STATUS = "OK"
GOOGLE_ROUTE_MATRIX_ROUTE_EXISTS = "ROUTE_EXISTS"
REAL_PROVIDER_CREDENTIAL_NAMES: Final[dict[str, str]] = {
    "serpapi": "SERPAPI_KEY",
    "tavily": "TAVILY_API_KEY",
    "google": "GOOGLE_CLOUD_API_KEY",
    "fx": "FX_API_KEY",
}
TOOL_EMPTY_RESULT_SHAPES: Final[dict[str, dict[str, object]]] = {
    "search_flights": {"best_flights": [], "other_flights": []},
    "search_hotels": {"properties": []},
    "tavily_search": {"results": [], "answer": None},
    "search_places": {"places": []},
    "place_details": {"reviews": [], "photos": []},
    "search_transit": {"options": []},
    "search_road_routes": {"options": []},
    "search_taxi_info": {"options": []},
    "distance_matrix": {"rows": []},
    "geocode": {"status": "ERROR", "lat": None, "lng": None},
    "currency_convert": {"amount_converted": 0.0, "rate": 1.0},
    "visa_centre_search": {"application_centre": None, "sources": []},
    "embassy_search": {"embassy": None},
    "rental_search": {"rentals": []},
    "fuel_price": {"price_per_litre": None, "available": False, "sources": []},
}

# Resolve .env from the project root regardless of working directory.
# Local dev: backend/app/config.py → ../../.. → project root.
# Docker:    /app/app/config.py   → / (no file); vars are injected via compose env_file.
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: str = "development"
    log_level: str = "info"

    # LLM — swap provider+model with two env vars, zero code changes
    # Examples:
    #   openai      / gpt-4o                              (default)
    #   anthropic   / claude-3-5-sonnet-20241022
    #   gemini      / gemini-1.5-pro
    #   groq        / llama3-70b-8192
    #   openrouter  / nvidia/nemotron-3-ultra-550b-a55b:free
    #   ollama      / llama3                              (local)
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"

    # Provider API keys — LiteLLM reads these as env vars automatically;
    # declare them here so pydantic-settings can validate + populate from .env
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""  # Gemini / Vertex AI
    groq_api_key: str = ""  # Groq (fast Llama inference)
    openrouter_api_key: str = ""  # reads OPEN_ROUTER_API_KEY; LiteLLM expects OPENROUTER_API_KEY

    # Optional: custom base URL for local / self-hosted models (Ollama, vLLM, etc.)
    llm_api_base: str = ""  # e.g. http://localhost:11434  for Ollama

    # LLM runtime guards — reasoning-heavy models stall indefinitely without an explicit budget
    llm_timeout_seconds: float = 60.0
    llm_max_tokens: int = 4096
    llm_num_retries: int = 2  # LiteLLM-side retries
    llm_max_retries: int = 1  # LangChain-side tenacity retries
    # "json_schema" | "function_calling" | "json_mode"; blank uses the provider default
    llm_structured_output_method: str = "json_schema"

    # Token budget for agents whose schema produces large nested output. A single
    # global budget truncates them mid-object, which surfaces only as a parse error.
    llm_max_tokens_large: int = 0
    # Comma-separated agent names (see models.enums.AgentName) using the large budget.
    llm_large_output_agents: str = ""
    # Re-prompt attempts after a schema-validation or truncation failure.
    llm_structured_max_attempts: int = 0
    # Cap on simultaneous in-flight LLM calls across all agent fan-outs.
    llm_concurrency: int = 0

    # Execution mode switch: real invokes provider adapters; mock replays recordings only.
    mock_external_apis: bool = True

    # Local tool response capture and replay
    tool_response_recording_enabled: bool = False
    tool_response_dir: str = "backend/tool_responses"
    tool_response_retention_days: int = 30

    # Shared external HTTP runtime
    external_api_connect_timeout_seconds: float = 5.0
    external_api_read_timeout_seconds: float = 20.0
    external_api_write_timeout_seconds: float = 10.0
    external_api_pool_timeout_seconds: float = 5.0
    external_api_max_retries: int = 3
    external_api_max_keepalive_connections: int = 20
    external_api_max_connections: int = 100
    external_api_keepalive_expiry_seconds: float = 5.0
    external_api_provider_concurrency: int = 5
    external_api_retryable_status_codes: str = "408,429,500,502,503,504"
    external_api_retry_base_delay_seconds: float = 0.5
    external_api_retry_max_delay_seconds: float = 8.0

    @property
    def retryable_status_codes(self) -> tuple[int, ...]:
        """Parse the comma-separated HTTP statuses eligible for retries."""
        return tuple(
            int(value.strip())
            for value in self.external_api_retryable_status_codes.split(",")
            if value.strip().isdigit()
        )

    # External Search APIs
    serpapi_key: str = ""
    tavily_api_key: str = ""
    serpapi_search_url: str = "https://serpapi.com/search.json"
    serpapi_default_language: str = "en"
    serpapi_default_country: str = "us"
    serpapi_default_adults: int = 1
    serpapi_default_hotel_adults: int = 2
    tavily_search_url: str = "https://api.tavily.com/search"
    tavily_default_search_depth: str = "basic"
    tavily_default_max_results: int = 5
    tavily_default_language: str = "en"

    # Maps & Places
    google_cloud_api_key: str = ""
    google_places_search_url: str = "https://places.googleapis.com/v1/places:searchText"
    google_places_details_url: str = "https://places.googleapis.com/v1/places"
    google_routes_url: str = "https://routes.googleapis.com/directions/v2:computeRoutes"
    google_route_matrix_url: str = (
        "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
    )
    google_geocode_url: str = "https://geocode.googleapis.com/v4/geocode/address"
    google_routes_max_matrix_elements: int = 625
    google_routes_max_transit_matrix_elements: int = 100
    google_routes_max_matrix_address_count: int = 50

    # Currency exchange
    fx_api_key: str = ""
    open_exchange_rates_latest_url: str = "https://openexchangerates.org/api/latest.json"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/travelcopilot"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Langfuse
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "travelcopilot-backend"

    # Clarification gate
    # Values live in the env file; a missing key must fail loudly at startup rather
    # than silently defaulting to ""/0, which disables the gate entirely.
    clarification_required_fields: str = "source,destination,dates,trip_days,travelers,budget"
    # Per-field confidence thresholds (comma-separated field:threshold pairs).
    # Falls back to parse_confidence_threshold for fields not listed.
    clarification_field_thresholds: str = (
        "source:0.3,destination:0.7,dates:0.6,trip_days:0.7,travelers:0.4,budget:0.7"
    )
    clarification_allowed_fields: str = (
        "source,destination,dates,trip_days,travelers,budget,query,"
        "preferred_cuisines,dietary_restrictions,visa_application_city,flexibility_days"
    )
    clarification_max_questions: int = Field(default=6, ge=1)
    clarification_max_optional_questions: int = Field(default=3, ge=1)
    clarification_max_prompt_length: int = Field(default=500, ge=1)
    parse_confidence_threshold: float = Field(default=0.6, gt=0.0, le=1.0)
    # Maximum clarification rounds before proceeding with best-effort defaults
    max_clarification_rounds: int = Field(default=3, ge=1)
    # Skippable questions cost an extra interrupt/resume cycle, so they are opt-in.
    enable_optional_clarification: bool = False
    # Date-flexibility question asked through the optional clarification node.
    flexibility_days_field: str = "flexibility_days"
    flexibility_days_prompt: str = (
        "How flexible are your travel dates? Answer in days either side "
        "(for example 0, 2 or 3), or skip to keep the dates fixed."
    )
    flexibility_days_max: int = 7
    flexibility_days_default: int = 0

    # StopsDiscoveryAgent — max candidate access-gateway options to surface per route
    max_gateway_options: int = 2

    # Budget guard
    max_llm_spend_usd_per_trip: float = 1.00

    # Budget Planner defaults & fallback cost estimates
    default_currency: str = "INR"
    default_budget_tier: str = "mid"
    default_trip_days: int = 3
    budget_over_threshold_multiplier: float = 1.1
    budget_under_threshold_multiplier: float = 0.9
    fallback_daily_activity_cost_budget: float = 500.0
    fallback_daily_activity_cost_mid: float = 1500.0
    fallback_daily_activity_cost_luxury: float = 4000.0
    fallback_daily_food_ratio: float = 0.35

    # Connectivity + permits enrichment (ItineraryCompilerAgent)
    # Above this elevation a stop is treated as remote for connectivity purposes.
    connectivity_remote_altitude_meters: int = 2000
    permits_lookup_enabled: bool = True

    # ItineraryCompilerAgent — quality-gate limits and narrative constraints
    itinerary_max_gate_iterations: int = 3
    itinerary_max_activities_per_slot: int = 2
    itinerary_max_activities_per_day: int = 3
    itinerary_max_title_length: int = 140
    itinerary_max_scams_in_briefing: int = 3
    # Above this elevation an arrival/travel day carries an acclimatization warning.

    @property
    def fallback_daily_activity_costs(self) -> dict[str, float]:
        return {
            "budget": self.fallback_daily_activity_cost_budget,
            "mid": self.fallback_daily_activity_cost_mid,
            "luxury": self.fallback_daily_activity_cost_luxury,
        }

    @property
    def clarification_fields(self) -> list[str]:
        return [f.strip() for f in self.clarification_required_fields.split(",")]

    @property
    def large_output_agent_names(self) -> frozenset[str]:
        """Agents whose structured output needs ``llm_max_tokens_large``."""
        return frozenset(
            name.strip() for name in self.llm_large_output_agents.split(",") if name.strip()
        )

    def max_tokens_for_agent(self, agent_name: str) -> int:
        """Token budget for one agent, falling back to the global budget."""
        if agent_name in self.large_output_agent_names:
            return self.llm_max_tokens_large
        return self.llm_max_tokens

    @property
    def field_thresholds(self) -> dict[str, float]:
        """Parse clarification_field_thresholds into a field→threshold mapping."""
        import contextlib

        result: dict[str, float] = {}
        for entry in self.clarification_field_thresholds.split(","):
            entry = entry.strip()
            if ":" in entry:
                field, val = entry.split(":", 1)
                with contextlib.suppress(ValueError):
                    result[field.strip()] = float(val.strip())
        return result

    @property
    def clarification_allowed_field_names(self) -> list[str]:
        return [field.strip() for field in self.clarification_allowed_fields.split(",")]

    def missing_real_provider_credentials(self) -> dict[str, str]:
        if self.mock_external_apis:
            return {}
        credentials = {
            "serpapi": self.serpapi_key,
            "tavily": self.tavily_api_key,
            "google": self.google_cloud_api_key,
            "fx": self.fx_api_key,
        }
        return {
            provider: REAL_PROVIDER_CREDENTIAL_NAMES[provider]
            for provider, credential in credentials.items()
            if not credential.strip()
        }


settings = Settings()
