"""Shared pooled HTTP execution for external provider adapters."""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.config import (
    EXTERNAL_API_DEFAULT_HTTP_HEADERS,
    TOOL_RESPONSE_STATUS_PARTIAL,
    TOOL_RESPONSE_STATUS_SUCCESS,
    TOOL_RUNTIME_DURATION_MS_KEY,
    TOOL_RUNTIME_ERROR_KEY,
    TOOL_RUNTIME_EXCHANGES_KEY,
    TOOL_RUNTIME_KEY,
    TOOL_RUNTIME_RETRY_COUNT_KEY,
    TOOL_RUNTIME_STATUS_KEY,
    settings,
)


@dataclass
class ExternalResponse:
    """Normalized execution details that adapters can add to their envelope."""

    payload: dict[str, Any]
    exchanges: list[dict[str, Any]] = field(default_factory=list)
    retry_count: int = 0
    duration_ms: int = 0
    error: dict[str, str] | None = None

    def runtime_metadata(self) -> dict[str, Any]:
        """Return recorder metadata without leaking provider transport details to agents."""
        metadata: dict[str, Any] = {
            TOOL_RUNTIME_EXCHANGES_KEY: self.exchanges,
            TOOL_RUNTIME_RETRY_COUNT_KEY: self.retry_count,
            TOOL_RUNTIME_DURATION_MS_KEY: self.duration_ms,
            TOOL_RUNTIME_STATUS_KEY: TOOL_RESPONSE_STATUS_SUCCESS
            if self.error is None
            else TOOL_RESPONSE_STATUS_PARTIAL,
        }
        if self.error is not None:
            metadata[TOOL_RUNTIME_ERROR_KEY] = self.error
        return {TOOL_RUNTIME_KEY: metadata}


class ExternalAPIClient:
    """Own one AsyncClient and bounded provider-specific concurrency."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._client_lock = asyncio.Lock()

    async def request_json(
        self,
        provider: str,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str | int | float | bool] | None = None,
        json_body: object | None = None,
    ) -> ExternalResponse:
        client = await self._get_client()
        semaphore = self._get_semaphore(provider)
        started_at = time.perf_counter()
        exchanges: list[dict[str, Any]] = []
        retry_count = 0
        async with semaphore:
            for attempt in range(1, settings.external_api_max_retries + 2):
                try:
                    response = await client.request(
                        method,
                        url,
                        headers={**EXTERNAL_API_DEFAULT_HTTP_HEADERS, **(headers or {})},
                        params=params,
                        json=json_body,
                    )
                    response_payload = self._response_payload(response)
                    exchanges.append(
                        self._exchange(
                            response,
                            response_payload,
                            attempt,
                            started_at,
                            headers,
                            params,
                            json_body,
                        )
                    )
                    if response.is_success:
                        return ExternalResponse(
                            payload=response_payload,
                            exchanges=exchanges,
                            retry_count=retry_count,
                            duration_ms=self._duration_ms(started_at),
                        )
                    if not self._is_retryable_status(response.status_code, attempt):
                        return self._failure_response(
                            exchanges, retry_count, started_at, response.status_code
                        )
                    retry_count += 1
                    await self._wait_before_retry(response, retry_count)
                except httpx.TransportError as exc:
                    exchanges.append(self._transport_exchange(exc, attempt, started_at))
                    if attempt > settings.external_api_max_retries:
                        return self._failure_response(
                            exchanges, retry_count, started_at, error_type=type(exc).__name__
                        )
                    retry_count += 1
                    await self._wait_before_retry(None, retry_count)
        return self._failure_response(exchanges, retry_count, started_at)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(
                            connect=settings.external_api_connect_timeout_seconds,
                            read=settings.external_api_read_timeout_seconds,
                            write=settings.external_api_write_timeout_seconds,
                            pool=settings.external_api_pool_timeout_seconds,
                        ),
                        limits=httpx.Limits(
                            max_keepalive_connections=settings.external_api_max_keepalive_connections,
                            max_connections=settings.external_api_max_connections,
                            keepalive_expiry=settings.external_api_keepalive_expiry_seconds,
                        ),
                    )
        return self._client

    def _get_semaphore(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._semaphores:
            self._semaphores[provider] = asyncio.Semaphore(
                settings.external_api_provider_concurrency
            )
        return self._semaphores[provider]

    def _response_payload(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = self._parse_text_payload(response.text)
        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    def _parse_text_payload(self, response_text: str) -> dict[str, Any]:
        lines = [line for line in response_text.splitlines() if line.strip()]
        if len(lines) > 1:
            elements = [self._parse_json_line(line) for line in lines]
            return {"elements": [element for element in elements if element is not None]}
        return {"text": response_text}

    def _parse_json_line(self, line: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else {"data": payload}

    def _exchange(
        self,
        response: httpx.Response,
        payload: dict[str, Any],
        attempt: int,
        started_at: float,
        request_headers: dict[str, str] | None,
        request_params: dict[str, str | int | float | bool] | None,
        request_body: object | None,
    ) -> dict[str, Any]:
        return {
            "request": {
                "method": response.request.method,
                "url": str(response.request.url),
                "headers": request_headers or {},
                "params": request_params or {},
                "json": request_body,
            },
            "response": payload,
            "http_status": response.status_code,
            "duration_ms": self._duration_ms(started_at),
            "attempt": attempt,
        }

    def _transport_exchange(
        self,
        exception: httpx.TransportError,
        attempt: int,
        started_at: float,
    ) -> dict[str, Any]:
        return {
            "request": {},
            "response": {"error": str(exception)},
            "http_status": None,
            "duration_ms": self._duration_ms(started_at),
            "attempt": attempt,
        }

    def _failure_response(
        self,
        exchanges: list[dict[str, Any]],
        retry_count: int,
        started_at: float,
        status_code: int | None = None,
        error_type: str | None = None,
    ) -> ExternalResponse:
        error_name = error_type or "http_error"
        error_message = error_name if status_code is None else f"HTTP {status_code}"
        return ExternalResponse(
            payload={},
            exchanges=exchanges,
            retry_count=retry_count,
            duration_ms=self._duration_ms(started_at),
            error={"type": error_name, "message": error_message},
        )

    def _is_retryable_status(self, status_code: int, attempt: int) -> bool:
        return (
            status_code in settings.retryable_status_codes
            and attempt <= settings.external_api_max_retries
        )

    async def _wait_before_retry(self, response: httpx.Response | None, retry_count: int) -> None:
        retry_after = self._retry_after_seconds(response)
        if retry_after is None:
            exponential_delay = settings.external_api_retry_base_delay_seconds * (
                2 ** (retry_count - 1)
            )
            retry_after = min(exponential_delay, settings.external_api_retry_max_delay_seconds)
            retry_after = random.uniform(0, retry_after)
        await asyncio.sleep(retry_after)

    def _retry_after_seconds(self, response: httpx.Response | None) -> float | None:
        if response is None:
            return None
        header_value = response.headers.get("Retry-After")
        if not header_value:
            return None
        try:
            return max(0.0, float(header_value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(header_value)
            except (TypeError, ValueError, IndexError):
                return None
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())

    def _duration_ms(self, started_at: float) -> int:
        return round((time.perf_counter() - started_at) * 1000)


_external_api_client: ExternalAPIClient | None = None


def get_external_api_client() -> ExternalAPIClient:
    global _external_api_client
    if _external_api_client is None:
        _external_api_client = ExternalAPIClient()
    return _external_api_client


async def close_external_api_client() -> None:
    global _external_api_client
    if _external_api_client is not None:
        await _external_api_client.close()
        _external_api_client = None
