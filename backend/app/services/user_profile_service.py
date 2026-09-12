"""Persistence helpers for session-scoped user profiles."""

from __future__ import annotations

from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.models.user_profile import UserProfile


async def upsert_user_profile(session_id: str, profile: UserProfile) -> None:
    """Store a validated profile for a planning session."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("""
                INSERT INTO user_profiles (session_id, profile_json)
                VALUES (:session_id, CAST(:profile AS jsonb))
                ON CONFLICT (session_id) DO UPDATE
                SET profile_json = CAST(EXCLUDED.profile_json AS jsonb),
                    updated_at = NOW()
            """),
            {"session_id": session_id, "profile": profile.model_dump_json()},
        )
        await db.commit()
