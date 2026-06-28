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
    """Configure structlog for JSON output with shared context fields."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    logging.basicConfig(
        format="%(message)s",
        level=logging.getLevelName(settings.log_level.upper()),
    )


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

    # Register Langfuse as LiteLLM success callback (best-effort)
    if settings.langfuse_public_key:
        try:
            import litellm

            litellm.success_callback = ["langfuse"]
            litellm.failure_callback = ["langfuse"]
            logger.info("litellm_langfuse_registered")
        except Exception as exc:
            logger.warning("litellm_langfuse_failed", error=str(exc))

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
            from prometheus_client import (  # type: ignore[import]
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
