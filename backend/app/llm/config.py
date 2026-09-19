"""Settings owned by the LLM provider and runtime."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.logging import log_configuration_validation_errors

_ENV_FILE = Path(__file__).resolve().parent.parent.parent.parent / ".env"


class LLMSettings(BaseSettings):
    """LLM provider credentials and execution controls."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    provider: str = Field(..., alias="LLM_PROVIDER", min_length=1)
    model: str = Field(..., alias="LLM_MODEL", min_length=1)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    api_base: str = Field(default="", alias="LLM_API_BASE")
    timeout_seconds: float = Field(default=60.0, alias="LLM_TIMEOUT_SECONDS")
    max_tokens: int = Field(default=4096, alias="LLM_MAX_TOKENS")
    num_retries: int = Field(default=2, alias="LLM_NUM_RETRIES")
    max_retries: int = Field(default=1, alias="LLM_MAX_RETRIES")
    structured_output_method: str = Field(
        default="function_calling", alias="LLM_STRUCTURED_OUTPUT_METHOD"
    )
    max_tokens_large: int = Field(default=0, alias="LLM_MAX_TOKENS_LARGE")
    large_output_agents: str = Field(default="", alias="LLM_LARGE_OUTPUT_AGENTS")
    structured_max_attempts: int = Field(default=0, alias="LLM_STRUCTURED_MAX_ATTEMPTS")
    concurrency: int = Field(default=0, alias="LLM_CONCURRENCY")

    @property
    def large_output_agent_names(self) -> frozenset[str]:
        """Return agents configured for the larger output token budget."""
        return frozenset(
            name.strip() for name in self.large_output_agents.split(",") if name.strip()
        )

    def max_tokens_for_agent(self, agent_name: str) -> int:
        """Return the configured token budget for one agent."""
        if agent_name in self.large_output_agent_names:
            return self.max_tokens_large
        return self.max_tokens


def _load_llm_settings() -> LLMSettings:
    try:
        return LLMSettings()
    except ValidationError as exc:
        log_configuration_validation_errors(exc.errors())
        raise


llm_settings = _load_llm_settings()
