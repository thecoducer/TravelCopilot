"""BaseTool protocol — all tools must satisfy this interface."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BaseTool(Protocol):
    """Minimal contract every tool (mock or real) must satisfy."""

    name: str
    description: str

    async def run(self, **kwargs: object) -> dict[str, Any]: ...
