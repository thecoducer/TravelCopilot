"""Regression tests for hardened structured output and data-provenance guarantees."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.agents.local_experiences_agent import LocalExperiencesAgent
from app.llm import (
    StructuredOutputError,
    invoke_structured,
    reset_active_llm_run_id,
    set_active_llm_run_id,
)
from app.models.enums import DataSource, Sentiment
from app.models.reports import ReviewSummary


class _Schema(BaseModel):
    name: str


def _envelope(parsed: Any, *, error: Any = None, finish_reason: str = "stop") -> dict[str, Any]:
    raw = MagicMock()
    raw.response_metadata = {"finish_reason": finish_reason}
    return {"parsed": parsed, "parsing_error": error, "raw": raw}


def _llm_returning(*results: Any) -> MagicMock:
    chain = MagicMock()
    chain.ainvoke = AsyncMock(side_effect=list(results))
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=chain)
    return llm


class TestInvokeStructured:
    @pytest.mark.asyncio
    async def test_returns_parsed_model_on_first_attempt(self) -> None:
        llm = _llm_returning(_envelope(_Schema(name="ok")))
        result = await invoke_structured(
            llm, _Schema, [HumanMessage(content="go")], agent="test", max_attempts=2
        )
        assert result.name == "ok"

    @pytest.mark.asyncio
    async def test_repairs_a_failed_first_attempt(self) -> None:
        llm = _llm_returning(
            _envelope(None, error=ValueError("field required")),
            _envelope(_Schema(name="repaired")),
        )
        result = await invoke_structured(
            llm, _Schema, [HumanMessage(content="go")], agent="test", max_attempts=2
        )
        assert result.name == "repaired"

    @pytest.mark.asyncio
    async def test_truncated_output_is_not_accepted_as_success(self) -> None:
        """A cut-off completion that happens to parse must still be retried."""
        llm = _llm_returning(
            _envelope(_Schema(name="partial"), finish_reason="length"),
            _envelope(_Schema(name="complete")),
        )
        result = await invoke_structured(
            llm, _Schema, [HumanMessage(content="go")], agent="test", max_attempts=2
        )
        assert result.name == "complete"

    @pytest.mark.asyncio
    async def test_raises_typed_error_when_every_attempt_fails(self) -> None:
        llm = _llm_returning(
            _envelope(None, error=ValueError("bad")),
            _envelope(None, error=ValueError("bad")),
        )
        with pytest.raises(StructuredOutputError) as excinfo:
            await invoke_structured(
                llm, _Schema, [HumanMessage(content="go")], agent="test", max_attempts=2
            )
        assert excinfo.value.attempts == 2
        assert excinfo.value.schema_name == "_Schema"

    @pytest.mark.asyncio
    async def test_falls_back_when_double_binding_is_unsupported(self) -> None:
        """Test doubles expose only ``with_structured_output(schema)``."""
        chain = MagicMock()
        chain.ainvoke = AsyncMock(return_value=_Schema(name="plain"))
        llm = MagicMock()
        llm.with_structured_output = MagicMock(
            side_effect=lambda schema, **kwargs: (
                (_ for _ in ()).throw(TypeError()) if kwargs else chain
            )
        )
        result = await invoke_structured(
            llm, _Schema, [HumanMessage(content="go")], agent="test", max_attempts=1
        )
        assert result.name == "plain"


class TestInvokeStructuredUsageTracking:
    @pytest.mark.asyncio
    async def test_records_usage_for_the_active_run(self, monkeypatch) -> None:
        recorded: list[tuple[str, dict[str, Any]]] = []

        async def _fake_record(run_id: str, usage: dict[str, Any]) -> None:
            recorded.append((run_id, usage))

        monkeypatch.setattr("app.llm.structured_output.record_llm_call_usage", _fake_record)

        raw = MagicMock()
        raw.response_metadata = {"finish_reason": "stop"}
        raw.usage_metadata = {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}
        llm = _llm_returning({"parsed": _Schema(name="ok"), "parsing_error": None, "raw": raw})
        llm.model = "openrouter/some-model"

        token = set_active_llm_run_id("trip-usage-test")
        try:
            await invoke_structured(
                llm, _Schema, [HumanMessage(content="go")], agent="test", max_attempts=1
            )
        finally:
            reset_active_llm_run_id(token)

        assert recorded
        run_id, usage = recorded[0]
        assert run_id == "trip-usage-test"
        assert usage["input_tokens"] == 12
        assert usage["output_tokens"] == 8

    @pytest.mark.asyncio
    async def test_no_usage_recorded_without_an_active_run(self, monkeypatch) -> None:
        recorded: list[Any] = []
        monkeypatch.setattr(
            "app.llm.structured_output.record_llm_call_usage",
            lambda *a, **k: recorded.append((a, k)),
        )
        llm = _llm_returning(_envelope(_Schema(name="ok")))

        await invoke_structured(
            llm, _Schema, [HumanMessage(content="go")], agent="test", max_attempts=1
        )

        assert recorded == []


class TestDataProvenance:
    def test_fallback_experience_carries_no_invented_social_proof(self) -> None:
        agent = LocalExperiencesAgent(llm=MagicMock())
        experience = agent._build_fallback_experience("Thekkady", None)
        assert experience.rating is None
        assert experience.review_count is None
        assert experience.source == DataSource.FALLBACK
        assert experience.geo_source == DataSource.FALLBACK

    def test_fallback_experience_trusts_stop_coordinates(self) -> None:
        agent = LocalExperiencesAgent(llm=MagicMock())
        experience = agent._build_fallback_experience("Munnar", (10.08, 77.06))
        assert experience.geo_source == DataSource.PROVIDER
        assert experience.rating is None

    def test_review_summary_defaults_to_unknown_sentiment(self) -> None:
        """Absent evidence, a summary must not imply a positive reception."""
        assert ReviewSummary(place_name="Somewhere").sentiment == Sentiment.UNKNOWN
