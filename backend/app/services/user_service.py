"""Persistence helpers for the auth-free username identity."""

from __future__ import annotations

from sqlalchemy import text

from app.db import AsyncSessionLocal


async def register_or_get_username(username: str) -> None:
    """Insert the username if new; a no-op if it already exists."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO users (username) VALUES (:username) ON CONFLICT (username) DO NOTHING"
            ),
            {"username": username},
        )
        await db.commit()
