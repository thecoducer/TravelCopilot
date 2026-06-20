"""Smoke tests for P0-3 config and P0-5 logging."""

from __future__ import annotations

import json

import structlog

from app.config import settings


def test_settings_llm_provider() -> None:
    assert settings.llm_provider == "openai"


def test_settings_llm_model() -> None:
    assert settings.llm_model == "gpt-4o"


def test_mock_external_apis_is_bool() -> None:
    assert isinstance(settings.mock_external_apis, bool)


def test_parse_confidence_threshold() -> None:
    assert 0.0 < settings.parse_confidence_threshold <= 1.0


def test_clarification_fields_parsed() -> None:
    fields = settings.clarification_fields
    assert "destination" in fields
    assert "dates" in fields
    assert "travelers" in fields


def test_structlog_json_output(capsys: object) -> None:
    """Verify structlog emits valid JSON."""
    log = structlog.get_logger("test")
    log.info("smoke_test", trace_id="t1", session_id="s1", agent_name="orchestrator")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    line = captured.out.strip().splitlines()[-1]
    parsed = json.loads(line)
    assert parsed["event"] == "smoke_test"
    assert parsed["trace_id"] == "t1"
