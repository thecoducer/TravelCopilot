"""Real Tavily search tool stub."""

from __future__ import annotations

from typing import Any


class TavilySearchTool:
    name = "tavily_search"
    description = "Real web search via Tavily API."

    async def run(self, **kwargs: object) -> dict[str, Any]:
        raise NotImplementedError(
            "TavilySearchTool requires TAVILY_API_KEY — implement in Phase 5."
        )
