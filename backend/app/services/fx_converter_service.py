"""FX Converter service — general utility for currency conversions and rate tracking."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from app.models.reports import FxRateEntry
from app.tools.factory import ToolFactory

logger = structlog.get_logger(__name__)


class FxConverter:
    """Helper class for FX currency conversions and tracking rate metadata."""

    def __init__(
        self,
        target_currency: str = "INR",
        fx_tool: Any | None = None,
        tool_factory: ToolFactory | None = None,
    ) -> None:
        """Initialise FxConverter.

        Args:
            target_currency: Default target/quote currency for conversions.
            fx_tool: Pre-instantiated FX tool (e.g. CurrencyConvertTool or MockCurrencyConvertTool).
            tool_factory: ToolFactory instance to resolve the FX tool if `fx_tool` is not provided.
        """
        self.target_currency = target_currency
        if fx_tool is not None:
            self._fx_tool = fx_tool
        else:
            factory = tool_factory or ToolFactory()
            self._fx_tool = factory.get("currency_convert")

        self.fx_rates_used: dict[str, FxRateEntry] = {}

    async def convert(
        self,
        amount: float,
        from_ccy: str,
        to_ccy: str | None = None,
    ) -> float:
        """Convert an amount from `from_ccy` to `to_ccy` (defaults to `self.target_currency`).

        Records the FX rate in `self.fx_rates_used` if a conversion occurs.
        Returns the converted amount (or original amount if zero, same currency, or on error).
        """
        dest_ccy = to_ccy or self.target_currency
        if amount == 0 or not from_ccy or from_ccy == dest_ccy:
            return float(amount)

        try:
            result = await self._fx_tool.run(amount=amount, base=from_ccy, quote=dest_ccy)
            rate = float(result.get("rate", 1.0))
            fetched_at_val = result.get("fetched_at")

            if isinstance(fetched_at_val, datetime):
                fetched_at_dt = fetched_at_val
            else:
                fetched_at_str = str(fetched_at_val or datetime.now(tz=UTC).isoformat())
                fetched_at_dt = datetime.fromisoformat(fetched_at_str.replace("Z", "+00:00"))

            self.fx_rates_used[f"{from_ccy}→{dest_ccy}"] = FxRateEntry(
                rate=rate,
                fetched_at=fetched_at_dt,
            )
            return float(result.get("amount_converted", amount))
        except Exception as exc:
            logger.warning(
                "fx_conversion_failed",
                from_ccy=from_ccy,
                to_ccy=dest_ccy,
                error=str(exc),
            )
            return float(amount)

    async def get_rate(self, from_ccy: str, to_ccy: str | None = None) -> float:
        """Fetch exchange rate from `from_ccy` to `to_ccy` without converting an explicit amount."""
        dest_ccy = to_ccy or self.target_currency
        if from_ccy == dest_ccy:
            return 1.0
        try:
            result = await self._fx_tool.run(amount=1.0, base=from_ccy, quote=dest_ccy)
            return float(result.get("rate", 1.0))
        except Exception:
            return 1.0

    def clear_rates(self) -> None:
        """Clear recorded FX rates history."""
        self.fx_rates_used.clear()

    @property
    def fx_disclaimer(self) -> str | None:
        """Return indicative FX rate disclaimer if any rates were recorded."""
        if self.fx_rates_used:
            return (
                "Exchange rates are indicative and fetched at planning time. "
                "Actual costs may vary with live rates."
            )
        return None

