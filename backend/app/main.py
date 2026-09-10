from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import settings


def configure_logging() -> None:
    """Configure structured logging.

    All log output — from app code (structlog) and third-party libraries
    (LiteLLM, uvicorn, SQLAlchemy via stdlib logging) — flows through a
    single pipeline so each event appears exactly once.

    Development: human-readable ConsoleRenderer (coloured, aligned).
    Production:  JSON lines.
    """
    level_int = logging.getLevelName(settings.log_level.upper())

    # Processors shared by both structlog and stdlib foreign-log chains.
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.CallsiteParameterAdder(
            parameters=[
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.LINENO,
                structlog.processors.CallsiteParameter.MODULE,
                structlog.processors.CallsiteParameter.FUNC_NAME,
            ]
        ),
    ]

    # Final renderer: pretty for dev, JSON for prod.
    if settings.app_env == "development":
        final_renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(
            colors=True, exception_formatter=structlog.dev.plain_traceback
        )
    else:
        final_renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [final_renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level_int),
        context_class=dict,
        # Route through stdlib so both structlog + stdlib share one handler.
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Single stdlib handler using structlog's ProcessorFormatter so foreign
    # logs (LiteLLM, uvicorn, SQLAlchemy) are also rendered consistently.
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=final_renderer,
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
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
        logging.getLogger(name).setLevel(logging.WARNING)

    # LiteLLM has a separate verbose flag that bypasses stdlib logging.
    try:
        import litellm as _litellm

        _litellm.set_verbose = False  # type: ignore[attr-defined]  # stops internal print() debug output
    except Exception:
        pass


def configure_otel(app: FastAPI) -> None:
    """Set up OpenTelemetry tracing via OTLP when configured."""
    if not settings.otel_exporter_otlp_endpoint:
        logger.info("otel_disabled", reason="OTEL_EXPORTER_OTLP_ENDPOINT not set")
        return

    resource = Resource(attributes={SERVICE_NAME: settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)


logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown hooks."""
    # ── Startup ──────────────────────────────────────────────────────────
    logger.info(
        "startup",
        llm_model=settings.llm_model,
        mock_apis=settings.mock_external_apis,
        env=settings.app_env,
    )

    # Initialise LangGraph checkpointer (creates checkpoint tables if needed)
    try:
        from app.checkpointer import get_checkpointer

        await get_checkpointer()
    except Exception as exc:
        logger.warning("checkpointer_init_failed", error=str(exc))

    # Initialize provider credentials and LiteLLM callbacks.
    try:
        from app.llm import init_llm

        init_llm()
    except Exception as exc:
        logger.warning("litellm_init_failed", error=str(exc))

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    logger.info("shutdown")
    try:
        from app.checkpointer import close_checkpointer

        await close_checkpointer()
    except Exception as exc:
        logger.warning("checkpointer_close_failed", error=str(exc))


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title="TravelCopilot API",
        description="Multi-Agent AI Trip Planner",
        version="0.1.0",
        lifespan=lifespan,
    )

    # ── CORS ───────────────────────────────────────────────────────────────
    origins = ["*"] if settings.app_env == "development" else ["https://app.travelcopilot.io"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request-ID middleware ──────────────────────────────────────────────
    @app.middleware("http")
    async def add_request_id(request: Request, call_next: object) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response: Response = await call_next(request)  # type: ignore[operator]
        response.headers["X-Request-ID"] = request_id
        return response

    configure_otel(app)

    # ── API routers ────────────────────────────────────────────────────────
    from app.routers.trip import router as trip_router
    from app.routers.user import router as user_router

    app.include_router(trip_router)
    app.include_router(user_router)

    # ── Health + Metrics endpoints ─────────────────────────────────────────
    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.app_env, "version": "0.1.0"}

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    async def metrics() -> Response:
        try:
            from prometheus_client import (
                CONTENT_TYPE_LATEST,
                generate_latest,
            )

            return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
        except ImportError:
            return Response(content="# prometheus_client not installed\n", media_type="text/plain")

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
