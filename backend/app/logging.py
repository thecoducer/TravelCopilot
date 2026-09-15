"""Structured logging configuration — single source of truth for all log output.

All log output — from app code (structlog) and third-party libraries
(LiteLLM, uvicorn, SQLAlchemy via stdlib logging) — flows through one
pipeline so each event appears exactly once, in a consistent shape.

Development: colourful ``ConsoleRenderer`` with Rich-rendered tracebacks
(file, line number, and syntax-highlighted source context).
Production:  JSON lines with a structured, machine-parseable ``exception`` field.
"""

from __future__ import annotations

import logging as stdlib_logging
from typing import cast

import structlog

from app.config import settings


def configure_logging() -> None:
    """Configure structlog + stdlib logging to share one rendering pipeline."""
    level_int = stdlib_logging.getLevelName(settings.log_level.upper())

    # Processors shared by both structlog and stdlib foreign-log chains.
    # NOTE: exc_info is deliberately left untouched here — it must reach the
    # final renderer raw so ConsoleRenderer's Rich formatter (dev) or
    # dict_tracebacks (prod) can render it. Pre-flattening it with
    # format_exc_info would make pretty tracebacks structurally impossible.
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.CallsiteParameterAdder(
            parameters=[
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.LINENO,
                structlog.processors.CallsiteParameter.MODULE,
                structlog.processors.CallsiteParameter.FUNC_NAME,
            ]
        ),
    ]

    final_processors: list[structlog.types.Processor]
    if settings.app_env == "development":
        final_processors = [
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.RichTracebackFormatter(
                    show_locals=False, width=120, extra_lines=2, word_wrap=True
                ),
            )
        ]
    else:
        # Structured, aggregator-friendly exception object instead of a flat string.
        # show_locals=False mirrors the dev-mode choice — avoid leaking secrets/tokens.
        final_processors = [
            structlog.processors.ExceptionRenderer(
                structlog.tracebacks.ExceptionDictTransformer(show_locals=False)
            ),
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=shared_processors + final_processors,
        wrapper_class=structlog.make_filtering_bound_logger(level_int),
        context_class=dict,
        # Route through stdlib so both structlog + stdlib share one handler.
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Single stdlib handler using structlog's ProcessorFormatter so foreign
    # logs (LiteLLM, uvicorn, SQLAlchemy) are also rendered consistently.
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=final_processors,
        foreign_pre_chain=shared_processors,
    )
    handler = stdlib_logging.StreamHandler()
    handler.setFormatter(formatter)

    root = stdlib_logging.getLogger()
    root.handlers.clear()  # remove any handlers added before us
    root.addHandler(handler)
    root.setLevel(level_int)

    # Silence extremely noisy debug-level libraries that flood logs with
    # HTTP wire frames, model-mapping warnings, etc.
    _silence = [
        "httpcore",
        "httpx",
        "hpack",
        "litellm",
        "LiteLLM",  # suppress per-request debug dumps
        "opentelemetry",
    ]
    for name in _silence:
        stdlib_logging.getLogger(name).setLevel(stdlib_logging.WARNING)

    # LiteLLM has a separate verbose flag that bypasses stdlib logging.
    try:
        import litellm as _litellm

        _litellm.set_verbose = False  # type: ignore[attr-defined]  # stops internal print() debug output
    except Exception:
        pass


def get_agent_logger(
    agent_name: str, session_id: str, **extra: object
) -> structlog.types.FilteringBoundLogger:
    """Return a logger pre-bound with ``agent`` + ``session_id`` (+ any extra fields)."""
    return cast(
        "structlog.types.FilteringBoundLogger",
        structlog.get_logger().bind(agent=agent_name, session_id=session_id, **extra),
    )
