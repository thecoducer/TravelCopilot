"""Process-local cancellation for active trip planning streams."""

from __future__ import annotations

import asyncio
from typing import Any

_active_tasks: dict[str, asyncio.Task[Any]] = {}


def register(session_id: str) -> None:
    """Associate the current asyncio task with an active planning session."""
    task = asyncio.current_task()
    if task is None:
        return
    _active_tasks[session_id] = task


def cancel(session_id: str) -> bool:
    """Cancel an active planning task and return whether one was found."""
    task = _active_tasks.get(session_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def unregister(session_id: str) -> None:
    """Remove a session task without disturbing a newer task for the same session."""
    task = _active_tasks.get(session_id)
    if task is not None and task is asyncio.current_task():
        _active_tasks.pop(session_id, None)


def active_sessions() -> set[str]:
    """Return active session IDs for diagnostics and focused tests."""
    return {session_id for session_id, task in _active_tasks.items() if not task.done()}
