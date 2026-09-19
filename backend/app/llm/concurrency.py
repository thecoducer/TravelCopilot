"""Concurrency limits for asynchronous LLM calls."""

from __future__ import annotations

import asyncio

from app.llm.config import llm_settings

_llm_semaphore: asyncio.Semaphore | None = None
_llm_semaphore_loop: asyncio.AbstractEventLoop | None = None


def llm_semaphore() -> asyncio.Semaphore:
    """Return the per-event-loop semaphore limiting concurrent LLM calls."""
    global _llm_semaphore, _llm_semaphore_loop
    running_loop = asyncio.get_running_loop()
    if _llm_semaphore is None or _llm_semaphore_loop is not running_loop:
        _llm_semaphore = asyncio.Semaphore(llm_settings.concurrency)
        _llm_semaphore_loop = running_loop
    return _llm_semaphore
