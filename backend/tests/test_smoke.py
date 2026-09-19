"""Smoke tests for P0-3 config and P0-5 logging."""

from __future__ import annotations

import contextlib
import io
import json
import logging
from collections.abc import Iterator

import pytest
import structlog
from pydantic import ValidationError

from app.config import Settings, settings
from app.llm.config import llm_settings


def test_settings_llm_provider() -> None:
    assert llm_settings.provider


def test_settings_llm_model() -> None:
    assert llm_settings.model


def test_mock_external_apis_is_bool() -> None:
    assert isinstance(settings.mock_external_apis, bool)


def test_parse_confidence_threshold() -> None:
    assert 0.0 < settings.parse_confidence_threshold <= 1.0


def test_clarification_fields_parsed() -> None:
    fields = settings.clarification_fields
    assert "destination" in fields
    assert "dates" in fields
    assert "travelers" in fields


def test_retryable_status_codes_parsed() -> None:
    configured_settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite://",
        redis_url="redis://localhost:6379/0",
        external_api_retryable_status_codes="408, 429, 503",
    )
    assert configured_settings.retryable_status_codes == (408, 429, 503)


def test_required_settings_fail_when_missing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR), pytest.raises(ValidationError):
        Settings(_env_file=None)

    assert "required_configuration_missing" in caplog.text
    assert "llm_provider" in caplog.text
    assert "database_url" in caplog.text


@contextlib.contextmanager
def _captured_logs() -> Iterator[io.StringIO]:
    """Capture what the configured formatter actually emits.

    Asserting on ``record.getMessage()`` instead would pass even if structlog and
    the stdlib formatter both rendered, producing one log line nested in another.
    The root handler writes to the real stderr captured at configure time, so a
    handler sharing its formatter is attached here instead.
    """
    stream = io.StringIO()
    root = logging.getLogger()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(root.handlers[0].formatter)
    root.addHandler(handler)
    try:
        yield stream
    finally:
        root.removeHandler(handler)


def _last_line(stream: io.StringIO) -> str:
    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    assert lines, "no log output was emitted"
    return lines[-1]


def test_structlog_json_output() -> None:
    """Verify structlog emits valid JSON."""
    log = structlog.get_logger("test")
    with _captured_logs() as stream:
        log.info("smoke_test", trace_id="t1", session_id="s1", agent_name="orchestrator")
    rendered = _last_line(stream)
    parsed = json.loads(rendered)
    assert parsed["event"] == "smoke_test"
    assert parsed["trace_id"] == "t1"
    # The payload is rendered exactly once, not wrapped in a second rendered line.
    assert rendered.count('"event": "smoke_test"') == 1


def test_structlog_includes_callsite_and_traceback() -> None:
    """Verify logs include file/line metadata and the traceback."""
    log = structlog.get_logger("test")

    with _captured_logs() as stream:
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("exception_test", session_id="s2")

    parsed = json.loads(_last_line(stream))
    assert parsed["event"] == "exception_test"
    assert parsed["session_id"] == "s2"
    assert "filename" in parsed
    assert "lineno" in parsed
    assert "exception" in parsed
    # Structured (dict_tracebacks-style) exception, not a flat string — aggregator-friendly.
    assert parsed["exception"][0]["exc_type"] == "ValueError"
    assert parsed["exception"][0]["exc_value"] == "boom"
    assert "locals" not in parsed["exception"][0]["frames"][0]
