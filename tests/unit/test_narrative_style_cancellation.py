"""A cancelled training task lets its database step finish first.

SQLite keeps a half-read statement's lock when a connection is dropped mid-query, so the
job's final status write then fails with "database is locked" (seen in CI).
"""

import asyncio

import pytest

from flint_graph.worker.activities.narrative_style import finish_then_cancel


@pytest.mark.anyio
async def test_cancelling_waits_for_the_running_database_step():
    started, release, finished = asyncio.Event(), asyncio.Event(), []

    async def step() -> int:
        started.set()
        await release.wait()
        finished.append("closed")
        return 1

    task = asyncio.create_task(finish_then_cancel(step))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done(), "cancellation must wait for the database step"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished == ["closed"]


@pytest.mark.anyio
async def test_a_step_result_or_error_passes_through_unchanged():
    async def value() -> str:
        return "ok"

    async def failing() -> None:
        raise ValueError("anatomy_review_failed")

    async def cancelled() -> None:
        raise asyncio.CancelledError

    assert await finish_then_cancel(value) == "ok"
    with pytest.raises(ValueError, match="anatomy_review_failed"):
        await finish_then_cancel(failing)
    with pytest.raises(asyncio.CancelledError):
        await finish_then_cancel(cancelled)
