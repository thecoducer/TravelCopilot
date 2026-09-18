"""Persistence helpers for trip planning — all trip-table SQL lives here."""

from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.models.reports import RunUsage

logger = structlog.get_logger(__name__)

_CROWD_LEVEL_TO_REALITY_SCORE: dict[str, int] = {
    "Low": 85,
    "Moderate": 65,
    "High": 45,
    "Extreme": 20,
}


async def persist_trip(
    session_id: str,
    trip_id: str,
    query: str,
    state: dict[str, Any],
    itinerary: Any,
    run_usage: RunUsage | None = None,
    username: str | None = None,
) -> None:
    """Persist the completed trip to the database.  Best-effort — never blocks SSE."""
    try:
        itinerary_json = itinerary.model_dump_json() if itinerary else None
        is_intl = state.get("is_international", False)
        title = _derive_title(itinerary, query)

        reality_score = None
        ctx = state.get("safety_report")
        if ctx and hasattr(ctx, "crowd_level"):
            reality_score = _CROWD_LEVEL_TO_REALITY_SCORE.get(ctx.crowd_level, 50)

        token_usage_json = json.dumps(run_usage.model_dump() if run_usage else {})

        async with AsyncSessionLocal() as session:
            await session.execute(
                text("""
                    INSERT INTO trips
                        (id, session_id, username, title, query, is_international,
                         itinerary_json, reality_score, token_usage_json)
                    VALUES
                        (:id, :session_id, :username, :title, :query, :is_international,
                         CAST(:itinerary AS jsonb), :reality_score,
                         CAST(:token_usage AS jsonb))
                    ON CONFLICT (id) DO UPDATE
                    SET itinerary_json = CAST(EXCLUDED.itinerary_json AS jsonb),
                        token_usage_json = CAST(EXCLUDED.token_usage_json AS jsonb),
                        title = COALESCE(EXCLUDED.title, trips.title),
                        updated_at = NOW()
                """),
                {
                    "id": trip_id,
                    "session_id": session_id,
                    "username": username,
                    "title": title,
                    "query": query[:2000],
                    "is_international": is_intl,
                    "itinerary": itinerary_json,
                    "reality_score": reality_score,
                    "token_usage": token_usage_json,
                },
            )
            await session.commit()
    except Exception as exc:
        logger.warning("trip_persist_failed", error=str(exc), session_id=session_id)


def _derive_title(itinerary: Any, query: str) -> str:
    """Sidebar label: prefer the itinerary title, fall back to a truncated query."""
    title = getattr(itinerary, "title", None)
    if isinstance(title, str) and title.strip():
        return title.strip()[:120]
    trimmed = query.strip()
    return (trimmed[:60] + "…") if len(trimmed) > 60 else trimmed or "New trip"


async def get_latest_trip_id(session_id: str) -> str | None:
    """Return the most recent trip id for a session, or None if absent."""
    try:
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                text(
                    "SELECT id FROM trips WHERE session_id = :sid ORDER BY created_at DESC LIMIT 1"
                ),
                {"sid": session_id},
            )
            result = row.fetchone()
            return str(result.id) if result else None
    except Exception as exc:
        logger.warning("get_latest_trip_id_failed", error=str(exc), session_id=session_id)
        return None


async def get_latest_itinerary(session_id: str) -> dict[str, Any] | None:
    """Return the latest itinerary row for a session, or None if absent."""
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text(
                "SELECT id, itinerary_json, created_at "
                "FROM trips WHERE session_id = :sid "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"sid": session_id},
        )
        result = row.fetchone()
        if not result:
            return None
        return {
            "id": str(result.id),
            "itinerary": result.itinerary_json,
            "created_at": str(result.created_at),
        }


async def update_itinerary_days(trip_id: str, trip_days: list[dict[str, Any]]) -> None:
    """Persist drag-drop day reorders by patching the itinerary JSON."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE trips"
                " SET itinerary_json = itinerary_json || :patch, updated_at = NOW()"
                " WHERE id = :id"
            ),
            {"id": trip_id, "patch": json.dumps({"trip_days": trip_days})},
        )
        await db.commit()


async def get_usage_json(trip_id: str) -> dict[str, Any] | None:
    """Return the stored per-run usage JSON for a trip, or None if the trip is absent."""
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text("SELECT token_usage_json FROM trips WHERE id = :id"),
            {"id": trip_id},
        )
        result = row.fetchone()
        if not result:
            return None
        return result.token_usage_json or {}


async def get_public_itinerary(slug: str) -> dict[str, Any] | None:
    """Return a public shared itinerary by slug, or None if not found."""
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text("SELECT id, itinerary_json FROM trips WHERE slug = :slug AND public = TRUE"),
            {"slug": slug},
        )
        result = row.fetchone()
        if not result:
            return None
        return {"id": str(result.id), "itinerary": result.itinerary_json}


async def get_itinerary_json_for_pdf(trip_id: str) -> Any | None:
    """Return the raw itinerary JSON for PDF rendering, or None if absent/empty."""
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text("SELECT itinerary_json FROM trips WHERE id = :id"),
            {"id": trip_id},
        )
        result = row.fetchone()
        if not result or not result.itinerary_json:
            return None
        return result.itinerary_json


async def list_sessions(username: str, limit: int = 100) -> list[dict[str, Any]]:
    """Return a user's sessions (latest trip per session) for the sidebar, newest first."""
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            text("""
                SELECT DISTINCT ON (session_id)
                    session_id, title, query, created_at,
                    (itinerary_json IS NOT NULL) AS has_itinerary
                FROM trips
                WHERE username = :username AND deleted_at IS NULL
                ORDER BY session_id, created_at DESC
            """),
            {"username": username},
        )
        sessions = [
            {
                "session_id": r.session_id,
                "title": r.title or (r.query or "New trip"),
                "created_at": str(r.created_at),
                "has_itinerary": bool(r.has_itinerary),
            }
            for r in rows.fetchall()
        ]
    sessions.sort(key=lambda s: s["created_at"], reverse=True)
    return sessions[:limit]


async def get_session_detail(session_id: str) -> dict[str, Any] | None:
    """Return the latest trip for a session with its title, or None if absent."""
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text("""
                SELECT id, title, query, itinerary_json, created_at
                FROM trips
                WHERE session_id = :sid AND deleted_at IS NULL
                ORDER BY created_at DESC LIMIT 1
            """),
            {"sid": session_id},
        )
        result = row.fetchone()
        if not result:
            return None
        return {
            "id": str(result.id),
            "session_id": session_id,
            "title": result.title or (result.query or "New trip"),
            "itinerary": result.itinerary_json,
            "created_at": str(result.created_at),
        }


async def rename_session(session_id: str, title: str) -> None:
    """Update the display title for every trip row in a session."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE trips SET title = :title, updated_at = NOW() WHERE session_id = :sid"),
            {"sid": session_id, "title": title[:120]},
        )
        await db.commit()


async def delete_session(username: str, session_id: str) -> bool:
    """Permanently delete a user's chat, including turns and saved itineraries."""
    async with AsyncSessionLocal() as db:
        ownership = await db.execute(
            text("SELECT 1 FROM trips WHERE session_id = :sid AND username = :username LIMIT 1"),
            {"sid": session_id, "username": username},
        )
        if not ownership.fetchone():
            return False

        await db.execute(
            text("DELETE FROM chat_turns WHERE session_id = :sid"),
            {"sid": session_id},
        )
        await db.execute(
            text("DELETE FROM trips WHERE session_id = :sid AND username = :username"),
            {"sid": session_id, "username": username},
        )
        await db.commit()
    return True
