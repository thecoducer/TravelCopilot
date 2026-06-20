"""Langfuse integration — LLM tracing and user feedback scoring.

Usage:
    handler = get_langfuse_handler(session_id="sess-123")
    if handler:
        result = await graph.ainvoke(state, config={"callbacks": [handler]})
        # Later: record user feedback
        await score_trip(trip_id="...", session_id="...", rating=1, comment="Great!")
"""

from __future__ import annotations

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def get_langfuse_handler(session_id: str = "") -> object | None:
    """Return a Langfuse CallbackHandler if keys are configured, else None.

    The returned handler is passed into every ``graph.ainvoke()`` call via
    ``config={"callbacks": [handler]}``.
    """
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.debug("langfuse_disabled", reason="Keys not configured")
        return None

    try:
        from langfuse.callback import CallbackHandler  # type: ignore[import]

        handler = CallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            session_id=session_id,
        )
        return handler
    except ImportError:
        logger.warning("langfuse_import_failed", hint="pip install langfuse")
        return None
    except Exception as exc:
        logger.warning("langfuse_init_failed", error=str(exc))
        return None


async def score_trip(
    trip_id: str,
    session_id: str,
    rating: int,  # 1 = positive, -1 = negative
    comment: str = "",
) -> None:
    """Post a user feedback score to Langfuse for a completed trip trace."""
    if not settings.langfuse_public_key:
        return
    try:
        from langfuse import Langfuse  # type: ignore[import]

        lf = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        lf.score(
            name="user_feedback",
            value=float(rating),
            trace_id=trip_id,
            comment=comment or None,
        )
        logger.info("langfuse_score_posted", trip_id=trip_id, rating=rating)
    except Exception as exc:
        logger.warning("langfuse_score_failed", error=str(exc))
