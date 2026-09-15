"""FastAPI user router — auth-free username identity, profile, and sessions.

POST   /api/user                          → register or fetch a username
GET    /api/user/{username}/profile       → read the user's profile
PUT    /api/user/{username}/profile       → upsert the user's profile
GET    /api/user/{username}/sessions      → list the user's chat sessions
PATCH  /api/user/{username}/sessions/{id} → rename a session
DELETE /api/user/{username}/sessions/{id} → soft-delete a session

Legacy (session-scoped) profile endpoints are retained for backward compatibility:
PUT/GET /api/user/profile (X-Session-ID header)
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.models.user_profile import UserProfile
from app.services import trip_service, user_profile_service, user_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/user", tags=["user"])

_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")


class RegisterUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)


class RenameSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


def _validate_username(username: str) -> str:
    normalized = username.strip()
    if not _USERNAME_PATTERN.match(normalized):
        raise HTTPException(
            status_code=422,
            detail="Username must be 3-32 characters: letters, numbers, hyphens, underscores.",
        )
    return normalized


@router.post("")
async def register_user(request: RegisterUserRequest) -> dict[str, Any]:
    """Register a new username or return the existing one (no auth)."""
    username = _validate_username(request.username)
    try:
        await user_service.register_or_get_username(username)
    except Exception as exc:
        logger.warning("register_user_db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"username": username}


@router.get("/{username}/profile")
async def get_profile_by_username(username: str) -> dict[str, Any]:
    """Return the stored profile for a username (null profile if none yet)."""
    username = _validate_username(username)
    try:
        profile = await user_profile_service.get_profile_by_username(username)
    except Exception as exc:
        logger.warning("get_profile_db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"username": username, "profile": profile}


@router.put("/{username}/profile")
async def upsert_profile_by_username(username: str, profile: UserProfile) -> dict[str, Any]:
    """Create or update the profile for a username."""
    username = _validate_username(username)
    profile.username = username
    try:
        await user_profile_service.upsert_profile_by_username(username, profile)
    except Exception as exc:
        logger.warning("upsert_profile_db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    logger.info("upsert_profile_ok", username=username)
    return {"status": "ok", "username": username}


@router.get("/{username}/sessions")
async def list_user_sessions(username: str) -> dict[str, Any]:
    """List the user's chat sessions for the sidebar, newest first."""
    username = _validate_username(username)
    try:
        sessions = await trip_service.list_sessions(username)
    except Exception as exc:
        logger.warning("list_sessions_db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"username": username, "sessions": sessions}


@router.patch("/{username}/sessions/{session_id}")
async def rename_user_session(
    username: str, session_id: str, request: RenameSessionRequest
) -> dict[str, Any]:
    """Rename a session shown in the sidebar."""
    _validate_username(username)
    try:
        await trip_service.rename_session(session_id, request.title)
    except Exception as exc:
        logger.warning("rename_session_db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok", "session_id": session_id, "title": request.title}


@router.delete("/{username}/sessions/{session_id}")
async def delete_user_session(username: str, session_id: str) -> dict[str, Any]:
    """Soft-delete a session (reversible; keeps token/cost history)."""
    _validate_username(username)
    try:
        await trip_service.soft_delete_session(session_id)
    except Exception as exc:
        logger.warning("delete_session_db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok", "session_id": session_id}


# ── Legacy session-scoped profile endpoints (backward compatible) ────────────


@router.put("/profile")
async def upsert_profile(
    profile: UserProfile,
    x_session_id: str = Header(..., alias="X-Session-ID"),
) -> dict[str, Any]:
    """Create or update the user profile for a session."""
    try:
        await user_profile_service.upsert_user_profile(x_session_id, profile)
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
