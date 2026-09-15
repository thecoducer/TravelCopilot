"""LangGraph checkpointer — provides persistent graph state across HTTP requests.

Production: ``AsyncPostgresSaver`` backed by the same Postgres as the app.
Tests:      ``MemorySaver`` (in-process, no DB required).

Usage::

    from app.checkpointer import get_checkpointer

    checkpointer = await get_checkpointer()          # singleton
    compiled = graph.compile(checkpointer=checkpointer)

The first call to ``get_checkpointer()`` runs ``checkpointer.setup()`` which
creates LangGraph's four checkpoint tables (idempotent — safe to call on every
startup).

Call ``close_checkpointer()`` during app shutdown to release the connection pool.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

_checkpointer: Any | None = None
_pool_ctx: Any | None = None  # async context manager held open to keep pool alive
_setup_lock = asyncio.Lock()


async def get_checkpointer() -> Any:
    """Return the application-level ``AsyncPostgresSaver`` singleton.

    Creates and initialises it on the first call.  Subsequent calls return the
    cached instance immediately.

    In langgraph-checkpoint-postgres ≥3, ``from_conn_string`` returns an async
    context manager.  We enter it here and store the CM reference so the
    connection pool stays alive for the application's lifetime.
    """
    global _checkpointer, _pool_ctx
    if _checkpointer is not None:
        return _checkpointer

    async with _setup_lock:
        if _checkpointer is not None:  # double-checked locking
            return _checkpointer

        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            # Strip the asyncpg dialect prefix — psycopg3 is used by the checkpoint library
            conn_str = settings.database_url.replace(
                "postgresql+asyncpg://", "postgresql://"
            ).replace("postgresql+psycopg2://", "postgresql://")

            # from_conn_string returns an _AsyncGeneratorContextManager in v3.
            # Enter it to get the actual saver; keep the CM reference alive so
            # the underlying connection pool is not garbage-collected.
            ctx = AsyncPostgresSaver.from_conn_string(conn_str)
            saver = await ctx.__aenter__()
            await saver.setup()
            _pool_ctx = ctx
            _checkpointer = saver
            logger.info("checkpointer_ready", backend="postgres")
        except Exception as exc:
            logger.warning(
                "checkpointer_postgres_unavailable",
                error=str(exc),
                fallback="memory",
            )
            # Graceful fallback to in-memory saver so the app still starts
            from langgraph.checkpoint.memory import MemorySaver

            _checkpointer = MemorySaver()
            logger.info("checkpointer_ready", backend="memory_fallback")

    return _checkpointer


async def close_checkpointer() -> None:
    """Release the connection pool.  Call once during app shutdown."""
    import contextlib

    global _checkpointer, _pool_ctx
    if _pool_ctx is not None:
        with contextlib.suppress(Exception):
            await _pool_ctx.__aexit__(None, None, None)
        _pool_ctx = None
    _checkpointer = None


def get_memory_checkpointer() -> Any:
    """Return a fresh in-memory checkpointer — for use in tests only."""
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


def reset_checkpointer() -> None:
    """Reset the singleton — for tests that need a clean state."""
    global _checkpointer
    _checkpointer = None
