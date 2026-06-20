"""Mock FX currency conversion tool — reads fx_rates.json fixture. (H)"""

from __future__ import annotations

from typing import Any

from app.tools.mock._helpers import load_fixture


class MockCurrencyConvertTool:
    name = "currency_convert"
    description = "Mock currency conversion — reads fx_rates.json fixture, no network calls."

    async def run(
        self,
        amount: float = 1.0,
        base: str = "INR",
        quote: str = "INR",
        **kwargs: object,
    ) -> dict[str, Any]:
        if base == quote:
            return {
                "amount": amount,
                "base": base,
                "quote": quote,
                "amount_converted": amount,
                "rate": 1.0,
                "fetched_at": "2026-06-19T00:00:00Z",
            }

        fx = load_fixture("fx_rates.json")
        key = f"{base}→{quote}"
        rate = fx.get("rates", {}).get(key)

        if rate is None:
            # Try reverse and invert
            rev_key = f"{quote}→{base}"
            rev_rate = fx.get("rates", {}).get(rev_key)
            rate = 1.0 / rev_rate if rev_rate else 1.0

        return {
            "amount": amount,
            "base": base,
            "quote": quote,
            "amount_converted": round(amount * rate, 4),
            "rate": rate,
            "fetched_at": fx.get("fetched_at", "2026-06-19T00:00:00Z"),
        }
