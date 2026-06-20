"""Mock rental and fuel price tools."""

from __future__ import annotations

from typing import Any

from app.tools.mock._helpers import find_fixture

# Typical petrol price in India (INR per litre)
_DEFAULT_FUEL_PRICE_INR = 104.0


class MockRentalSearchTool:
    name = "rental_search"
    description = "Mock rental search — returns fixture data, no network calls."

    async def run(
        self, destination: str = "", vehicle_type: str = "", **kwargs: object
    ) -> dict[str, Any]:
        data = find_fixture("rentals", destination)
        if data is None:
            return {"rentals": []}

        rentals = data.get("rentals", [])
        if vehicle_type:
            rentals = [r for r in rentals if r.get("type") == vehicle_type] or rentals
        return {"rentals": rentals}


class MockFuelPriceTool:
    name = "fuel_price"
    description = "Mock fuel price — returns a hardcoded price per litre, no network calls."

    async def run(
        self, destination: str = "", fuel_type: str = "petrol", **kwargs: object
    ) -> dict[str, Any]:
        return {
            "destination": destination,
            "fuel_type": fuel_type,
            "price_per_litre": _DEFAULT_FUEL_PRICE_INR,
            "currency_code": "INR",
            "source": "mock",
        }
