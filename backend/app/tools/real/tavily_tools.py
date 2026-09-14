"""Tavily Search adapter."""

from __future__ import annotations

from typing import Any

from app.config import (
    HTTP_AUTH_BEARER_PREFIX,
    HTTP_HEADER_AUTHORIZATION,
    HTTP_HEADER_CONTENT_TYPE,
    HTTP_HEADER_JSON,
    PROVIDER_TAVILY,
    settings,
)
from app.services.external_api_client import ExternalAPIClient, get_external_api_client
from app.tools.real._helpers import invalid_request_result, provider_result, require_credential


class TavilySearchTool:
    name = "tavily_search"
    description = "Real web search via Tavily API."

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        self._client = client or get_external_api_client()

    async def run(
        self,
        query: str = "",
        max_results: int | None = None,
        search_depth: str | None = None,
        language: str | None = None,
        include_domains: list[str] | None = None,
        **kwargs: object,
    ) -> dict[str, Any]:
        max_results = settings.tavily_default_max_results if max_results is None else max_results
        search_depth = search_depth or settings.tavily_default_search_depth
        language = language or settings.tavily_default_language
        empty_result: dict[str, Any] = {
            "query": query,
            "answer": None,
            "results": [],
            "usage": {},
        }
        if not query.strip():
            return invalid_request_result("query is required", empty_result)
        require_credential(settings.tavily_api_key, PROVIDER_TAVILY)
        payload = {
            "query": query,
            "search_depth": search_depth,
            "max_results": max(0, min(max_results, 20)),
            "include_answer": False,
            "include_raw_content": False,
            "include_usage": True,
            "include_domains": include_domains or [],
            "language": language,
        }
        response = await self._client.request_json(
            PROVIDER_TAVILY,
            "POST",
            settings.tavily_search_url,
            headers={
                HTTP_HEADER_AUTHORIZATION: f"{HTTP_AUTH_BEARER_PREFIX}{settings.tavily_api_key}",
                HTTP_HEADER_CONTENT_TYPE: HTTP_HEADER_JSON,
            },
            json_body=payload,
        )
        return provider_result(response.payload, response, empty_result)
