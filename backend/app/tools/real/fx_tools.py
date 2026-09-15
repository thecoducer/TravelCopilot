"""Open Exchange Rates currency conversion adapter."""

from __future__ import annotations

from typing import Any

from app.config import (
    ISO_CURRENCY_CODE_LENGTH,
    PROVIDER_OPEN_EXCHANGE_RATES,
    settings,
)
from app.services.external_api_client import ExternalAPIClient, get_external_api_client
from app.tools.real._helpers import invalid_request_result, provider_result, require_credential


class CurrencyConvertTool:
    name = "currency_convert"
    description = "Real currency conversion via FX rate provider (live rates, cached 12h)."

    def __init__(self, client: ExternalAPIClient | None = None) -> None:
        self._client = client or get_external_api_client()

    async def run(
        self,
        amount: float = 0.0,
        base: str = "",
        quote: str = "",
        **kwargs: object,
    ) -> dict[str, Any]:
        base_code = base.upper().strip()
        quote_code = quote.upper().strip()
        empty_result = {
            "amount_converted": amount,
            "rate": 1.0,
            "base": base_code,
            "quote": quote_code,
        }
        if not self._valid_currency(base_code) or not self._valid_currency(quote_code):
            return invalid_request_result("base and quote must be ISO 4217 codes", empty_result)
        if base_code == quote_code:
            return {**empty_result, "fetched_at": None}
        require_credential(settings.fx_api_key, PROVIDER_OPEN_EXCHANGE_RATES)
        response = await self._client.request_json(
            PROVIDER_OPEN_EXCHANGE_RATES,
            "GET",
            settings.open_exchange_rates_latest_url,
            params={
                "app_id": settings.fx_api_key,
                "base": base_code,
                "symbols": quote_code,
            },
        )
        rates = response.payload.get("rates", {})
        rate = rates.get(quote_code) if isinstance(rates, dict) else None
        if not isinstance(rate, (int, float)) or rate <= 0:
            return provider_result({}, response, empty_result)
        result = {
            "amount_converted": float(amount) * float(rate),
            "rate": float(rate),
            "base": base_code,
            "quote": quote_code,
            "provider_timestamp": response.payload.get("timestamp"),
        }
        return provider_result(result, response, empty_result)

    def _valid_currency(self, value: str) -> bool:
        return len(value) == ISO_CURRENCY_CODE_LENGTH and value.isalpha()
