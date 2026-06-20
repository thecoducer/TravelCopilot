"""FastAPI user profile router.

PUT  /api/user/profile  → upsert UserProfile (stored in PostgreSQL)
GET  /api/user/profile  → read UserProfile by X-Session-ID header
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException

from app.models.user_profile import UserProfile

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/user", tags=["user"])


@router.put("/profile")
async def upsert_profile(
    profile: UserProfile,
    x_session_id: str = Header(..., alias="X-Session-ID"),
) -> dict[str, Any]:
    """Create or update the user profile for a session."""
    try:
        from sqlalchemy import text

        from app.db import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await db.execute(
                text("""
                    INSERT INTO user_profiles (session_id, profile_json)
                    VALUES (:session_id, CAST(:profile AS jsonb))
                    ON CONFLICT (session_id) DO UPDATE
                    SET profile_json = CAST(EXCLUDED.profile_json AS jsonb),
                        updated_at   = NOW()
                """),
                {"session_id": x_session_id, "profile": profile.model_dump_json()},
            )
            await db.commit()
        logger.info("upsert_profile_ok", session_id=x_session_id, user_id=profile.user_id)
        return {"status": "ok", "session_id": x_session_id}
    except Exception as exc:
        logger.warning("upsert_profile_db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.get("/profile")
async def get_profile(
    x_session_id: str = Header(..., alias="X-Session-ID"),
) -> dict[str, Any]:
    """Retrieve the user profile for the current session."""
    try:
        from sqlalchemy import text

        from app.db import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            row = await db.execute(
                text("SELECT profile_json FROM user_profiles WHERE session_id = :sid"),
                {"sid": x_session_id},
            )
            result = row.fetchone()
            if not result:
                raise HTTPException(
                    status_code=404,
                    detail="No profile found — call PUT /api/user/profile first",
                )
            return {"session_id": x_session_id, "profile": result.profile_json}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("get_profile_db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
