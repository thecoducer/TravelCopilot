"""Persistence helpers for chat-turn history — one row per prompt/response."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

from app.db import AsyncSessionLocal

logger = structlog.get_logger(__name__)


async def append_turn(
    session_id: str,
    role: str,
    content: str,
    username: str | None = None,
    trip_id: str | None = None,
    intent: str | None = None,
) -> None:
    """Append a conversation turn.  Best-effort — never blocks the SSE stream."""
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("""
                    INSERT INTO chat_turns
                        (session_id, username, turn_index, role, content, trip_id, intent)
                    VALUES (
                        :session_id, :username,
                        COALESCE(
                            (
                                SELECT MAX(turn_index) + 1
                                FROM chat_turns WHERE session_id = :session_id
                            ),
                            0
                        ),
                        :role, :content, :trip_id, :intent
                    )
                """),
                {
                    "session_id": session_id,
                    "username": username,
                    "role": role,
                    "content": content[:8000],
                    "trip_id": trip_id,
                    "intent": intent,
                },
            )
            await db.commit()
    except Exception as exc:
        logger.warning("append_turn_failed", error=str(exc), session_id=session_id)


async def list_turns(session_id: str) -> list[dict[str, Any]]:
    """Return the ordered conversation history for a session."""
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            text("""
                SELECT turn_index, role, content, trip_id, intent, created_at
                FROM chat_turns
                WHERE session_id = :sid
                ORDER BY turn_index ASC
            """),
            {"sid": session_id},
        )
        return [
            {
                "turn_index": r.turn_index,
                "role": r.role,
                "content": r.content,
                "trip_id": str(r.trip_id) if r.trip_id else None,
                "intent": r.intent,
                "created_at": str(r.created_at),
            }
            for r in rows.fetchall()
        ]
