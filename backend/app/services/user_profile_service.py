"""Persistence helpers for user profiles (session- and username-scoped)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.models.user_profile import UserProfile


async def upsert_user_profile(session_id: str, profile: UserProfile) -> None:
    """Store a validated profile for a planning session."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("""
                INSERT INTO user_profiles (session_id, username, profile_json)
                VALUES (:session_id, :username, CAST(:profile AS jsonb))
                ON CONFLICT (session_id) DO UPDATE
                SET profile_json = CAST(EXCLUDED.profile_json AS jsonb),
                    username = EXCLUDED.username,
                    updated_at = NOW()
            """),
            {
                "session_id": session_id,
                "username": profile.username,
                "profile": profile.model_dump_json(),
            },
        )
        await db.commit()


async def upsert_profile_by_username(username: str, profile: UserProfile) -> None:
    """Store a profile keyed by username so it survives across sessions."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("""
                INSERT INTO user_profiles (session_id, username, profile_json)
                VALUES (:session_id, :username, CAST(:profile AS jsonb))
                ON CONFLICT (session_id) DO UPDATE
                SET profile_json = CAST(EXCLUDED.profile_json AS jsonb),
                    username = EXCLUDED.username,
                    updated_at = NOW()
            """),
            {
                "session_id": f"user:{username}",
                "username": username,
                "profile": profile.model_dump_json(),
            },
        )
        await db.commit()


async def get_profile_by_username(username: str) -> dict[str, Any] | None:
    """Return the stored profile JSON for a username, or None if absent."""
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text("SELECT profile_json FROM user_profiles WHERE username = :username LIMIT 1"),
            {"username": username},
        )
        result = row.fetchone()
        return result.profile_json if result else None
