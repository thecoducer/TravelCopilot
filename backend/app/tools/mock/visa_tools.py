"""Mock visa tools — application centre and embassy data from fixtures."""

from __future__ import annotations

from typing import Any

from app.tools.mock._helpers import find_fixture


class MockVisaCentreSearchTool:
    name = "visa_centre_search"
    description = "Mock visa centre lookup — returns fixture data, no network calls."

    async def run(
        self,
        passport_country: str = "",
        destination_country: str = "",
        home_city: str = "",
        **kwargs: object,
    ) -> dict[str, Any]:
        data = find_fixture("visa", passport_country, destination_country)
        if data is None:
            return {"application_centre": None, "sources": []}

        centre = data.get("application_centre")
        sources = data.get("sources", [])
        last_verified_at = data.get("last_verified_at")
        return {
            "application_centre": centre,
            "sources": sources,
            "last_verified_at": last_verified_at,
        }


class MockEmbassySearchTool:
    name = "embassy_search"
    description = "Mock embassy/consulate lookup — returns fixture data, no network calls."

    async def run(
        self,
        passport_country: str = "",
        destination_country: str = "",
        home_city: str = "",
        **kwargs: object,
    ) -> dict[str, Any]:
        data = find_fixture("visa", passport_country, destination_country)
        if data is None:
            return {"embassy": None}

        return {"embassy": data.get("nearest_embassy")}
