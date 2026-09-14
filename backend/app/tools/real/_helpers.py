"""Small shared helpers for real provider adapters."""

from __future__ import annotations

from typing import Any

from app.config import (
    TOOL_RESPONSE_STATUS_ERROR,
    TOOL_RESPONSE_STATUS_PARTIAL,
    TOOL_RUNTIME_ERROR_KEY,
    TOOL_RUNTIME_KEY,
    TOOL_RUNTIME_STATUS_KEY,
)
from app.services.external_api_client import ExternalResponse


def require_credential(credential: str, provider: str) -> None:
    if not credential.strip():
        raise RuntimeError(f"Missing credential for provider: {provider}")


def provider_result(
    payload: dict[str, Any],
    response: ExternalResponse,
    empty_result: dict[str, Any],
) -> dict[str, Any]:
    result = payload if response.error is None else empty_result
    runtime = response.runtime_metadata()
    if response.error is not None:
        runtime[TOOL_RUNTIME_KEY][TOOL_RUNTIME_STATUS_KEY] = TOOL_RESPONSE_STATUS_PARTIAL
        runtime[TOOL_RUNTIME_KEY][TOOL_RUNTIME_ERROR_KEY] = response.error
    return {**result, **runtime}


def invalid_request_result(error_message: str, empty_result: dict[str, Any]) -> dict[str, Any]:
    return {
        **empty_result,
        TOOL_RUNTIME_KEY: {
            TOOL_RUNTIME_STATUS_KEY: TOOL_RESPONSE_STATUS_ERROR,
            TOOL_RUNTIME_ERROR_KEY: {"type": "invalid_request", "message": error_message},
        },
    }
