"""Unit tests for FxConverter service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.models.reports import FxRateEntry
from app.services.fx_converter_service import FxConverter
from app.tools.factory import ToolFactory


class MockFxTool:
    def __init__(self, rate: float = 1.82, raise_error: bool = False) -> None:
        self.rate = rate
        self.raise_error = raise_error
        self.calls: list[dict[str, Any]] = []

    async def run(self, amount: float = 1.0, base: str = "USD", quote: str = "INR", **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"amount": amount, "base": base, "quote": quote})
        if self.raise_error:
            raise RuntimeError("FX API connection failed")

        return {
            "amount": amount,
            "base": base,
            "quote": quote,
            "amount_converted": round(amount * self.rate, 2),
            "rate": self.rate,
            "fetched_at": "2026-09-12T10:00:00Z",
        }


@pytest.mark.asyncio
async def test_fx_converter_same_currency_no_op() -> None:
    tool = MockFxTool()
    converter = FxConverter(target_currency="INR", fx_tool=tool)

    converted = await converter.convert(100.0, "INR", "INR")
    assert converted == 100.0
    assert len(tool.calls) == 0
    assert len(converter.fx_rates_used) == 0
    assert converter.fx_disclaimer is None


@pytest.mark.asyncio
async def test_fx_converter_zero_amount_no_op() -> None:
    tool = MockFxTool()
    converter = FxConverter(target_currency="JPY", fx_tool=tool)

    converted = await converter.convert(0.0, "USD", "JPY")
    assert converted == 0.0
    assert len(tool.calls) == 0


@pytest.mark.asyncio
async def test_fx_converter_different_currency_conversion() -> None:
    tool = MockFxTool(rate=1.82)
    converter = FxConverter(target_currency="JPY", fx_tool=tool)

    converted = await converter.convert(1000.0, "INR", "JPY")
    assert converted == 1820.0
    assert len(tool.calls) == 1
    assert tool.calls[0] == {"amount": 1000.0, "base": "INR", "quote": "JPY"}

    key = "INR→JPY"
    assert key in converter.fx_rates_used
    rate_entry = converter.fx_rates_used[key]
    assert rate_entry.rate == 1.82
    assert isinstance(rate_entry.fetched_at, datetime)
    assert converter.fx_disclaimer is not None


@pytest.mark.asyncio
async def test_fx_converter_explicit_to_ccy() -> None:
    tool = MockFxTool(rate=0.012)
    converter = FxConverter(target_currency="INR", fx_tool=tool)

    converted = await converter.convert(100.0, "INR", to_ccy="USD")
    assert converted == 1.2
    assert tool.calls[0] == {"amount": 100.0, "base": "INR", "quote": "USD"}
    assert "INR→USD" in converter.fx_rates_used


@pytest.mark.asyncio
async def test_fx_converter_error_fallback() -> None:
    tool = MockFxTool(raise_error=True)
    converter = FxConverter(target_currency="EUR", fx_tool=tool)

    converted = await converter.convert(500.0, "USD", "EUR")
    assert converted == 500.0  # Fallbacks to original amount
    assert len(converter.fx_rates_used) == 0


@pytest.mark.asyncio
async def test_fx_converter_get_rate() -> None:
    tool = MockFxTool(rate=83.5)
    converter = FxConverter(target_currency="INR", fx_tool=tool)

    same_rate = await converter.get_rate("INR", "INR")
    assert same_rate == 1.0

    diff_rate = await converter.get_rate("USD", "INR")
    assert diff_rate == 83.5


@pytest.mark.asyncio
async def test_fx_converter_clear_rates() -> None:
    tool = MockFxTool(rate=1.5)
    converter = FxConverter(target_currency="EUR", fx_tool=tool)

    await converter.convert(100.0, "USD", "EUR")
    assert len(converter.fx_rates_used) == 1

    converter.clear_rates()
    assert len(converter.fx_rates_used) == 0
    assert converter.fx_disclaimer is None


@pytest.mark.asyncio
async def test_fx_converter_with_mock_tool_factory() -> None:
    factory = ToolFactory(mock=True)
    converter = FxConverter(target_currency="JPY", tool_factory=factory)

    converted = await converter.convert(1000.0, "INR", "JPY")
    assert converted > 0
    assert "INR→JPY" in converter.fx_rates_used
