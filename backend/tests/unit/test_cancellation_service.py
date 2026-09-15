import asyncio

import pytest

from app.services import cancellation_service


@pytest.mark.asyncio
async def test_cancel_stops_registered_task() -> None:
    started = asyncio.Event()

    async def active_task() -> None:
        cancellation_service.register("session-1")
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancellation_service.unregister("session-1")

    task = asyncio.create_task(active_task())
    await started.wait()

    assert "session-1" in cancellation_service.active_sessions()
    assert cancellation_service.cancel("session-1") is True

    with pytest.raises(asyncio.CancelledError):
        await task

    assert "session-1" not in cancellation_service.active_sessions()
    assert cancellation_service.cancel("session-1") is False
