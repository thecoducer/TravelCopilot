"""Mock Tavily search tool — returns fixture data in real Tavily API format.

Real Tavily format: {query, answer, results: [{title, url, content, score, published_date}]}
Fixtures for scams are stored in Tavily format directly.
"""

from __future__ import annotations

from typing import Any

from app.tools.mock._helpers import find_fixture

_SCAM_KEYWORDS = {"scam", "safety", "danger", "crime", "fraud", "theft", "pickpocket"}
_VISA_KEYWORDS = {"visa", "passport", "entry", "embassy", "consulate", "application", "schengen"}
_FOOD_KEYWORDS = {"food", "restaurant", "eat", "dining", "street food", "cafe"}


def _detect_intent(query: str) -> str:
    lower = query.lower()
    if any(k in lower for k in _SCAM_KEYWORDS):
        return "scams"
    if any(k in lower for k in _VISA_KEYWORDS):
        return "visa"
    if any(k in lower for k in _FOOD_KEYWORDS):
        return "food"
    return "context"


class MockTavilySearchTool:
    name = "tavily_search"
    description = "Mock Tavily web search — real Tavily API format, no network calls."

    async def run(self, query: str = "", destination: str = "", **kwargs: object) -> dict[str, Any]:
        intent = _detect_intent(query)
        dest_slug = (destination or "").lower().split(",")[0].strip()

        # Scam fixtures are already in Tavily format — return directly
        if intent == "scams" and dest_slug:
            data = find_fixture("scams", dest_slug)
            if data:
                return data

        # Generic fallback in Tavily format
        return {
            "query": query,
            "follow_up_questions": None,
            "answer": f"Mock {intent} information for {destination or 'destination'}.",
            "images": [],
            "results": [
                {
                    "title": f"Mock {intent} result for {destination or 'destination'}",
                    "url": f"https://example.com/{intent}/{dest_slug}",
                    "content": (
                        f"This is mock {intent} information for {destination}. "
                        "Real content would appear here in production."
                    ),
                    "score": 0.80,
                    "published_date": "2026-06-01",
                }
            ],
            "response_time": 0.5,
        }
