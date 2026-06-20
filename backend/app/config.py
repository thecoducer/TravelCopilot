from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: str = "development"
    log_level: str = "info"

    # LLM — swap provider+model with two env vars, zero code changes
    # Examples:
    #   openai   / gpt-4o                        (default)
    #   anthropic/ claude-3-5-sonnet-20241022
    #   gemini   / gemini-1.5-pro
    #   ollama   / llama3                         (local)
    #   groq     / llama3-70b-8192
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"

    # Provider API keys — LiteLLM reads these as env vars automatically;
    # declare them here so pydantic-settings can validate + populate from .env
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""  # Gemini / Vertex AI
    groq_api_key: str = ""  # Groq (fast Llama inference)

    # Optional: custom base URL for local / self-hosted models (Ollama, vLLM, etc.)
    llm_api_base: str = ""  # e.g. http://localhost:11434  for Ollama

    # Mock flag — when True all tools return fixture data, no network calls
    mock_external_apis: bool = True

    # External Search APIs
    serpapi_key: str = ""
    tavily_api_key: str = ""

    # Maps & Places
    google_maps_api_key: str = ""
    google_places_api_key: str = ""

    # Weather
    openweathermap_api_key: str = ""

    # Currency exchange
    fx_api_key: str = ""

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
    clarification_required_fields: str = "destination,dates,travelers"
    parse_confidence_threshold: float = 0.6

    # Budget guard
    max_llm_spend_usd_per_trip: float = 1.00

    @property
    def clarification_fields(self) -> list[str]:
        return [f.strip() for f in self.clarification_required_fields.split(",")]


settings = Settings()
