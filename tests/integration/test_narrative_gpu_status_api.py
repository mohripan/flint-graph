"""The Studio reads whether generation will wait for the GPU (ADR 0069)."""

import asyncio

import pytest
from sqlalchemy import select
from test_narrative_package_v2_api import configure, v2  # noqa: F401

from flint_graph.application.services.narrative_gpu import gpu_heartbeat, record_gpu_state
from flint_graph.infrastructure.db.models import NarrativeGpuStatus

pytestmark = pytest.mark.anyio


async def status(client, headers):
    response = await client.get("/v1/narrative/gpu", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_it_needs_a_signed_in_person(v2):  # noqa: F811
    client, *_ = v2
    assert (await client.get("/v1/narrative/gpu")).status_code == 401


async def test_a_running_worker_is_seen_and_a_stopped_machine_is_asleep(v2):  # noqa: F811
    client, factory, _, owner, _ = v2
    configure(
        narrative_image_generation_enabled=True,
        narrative_gpu_sleeps=True,
        narrative_gpu_wake_seconds=150,
    )
    assert (await status(client, owner)) == {
        "state": "unavailable",
        "detail": "controller_down",
        "wake_seconds": 150,
        "waiting": ["image"],
    }
    async with factory() as session:
        await record_gpu_state(session, "controller", "stopped")
        await session.commit()
    assert (await status(client, owner))["state"] == "asleep"
    async with factory() as session:
        await record_gpu_state(session, "controller", "unavailable", "no_capacity")
        await session.commit()
    seen = await status(client, owner)
    assert (seen["state"], seen["detail"]) == ("unavailable", "no_capacity")

    async with gpu_heartbeat(factory, "image", every=0.01):
        await asyncio.sleep(0.2)
    seen = await status(client, owner)
    assert (seen["state"], seen["waiting"]) == ("ready", [])


async def test_a_heartbeat_that_cannot_write_never_stops_the_worker(v2):  # noqa: F811
    def broken():
        raise RuntimeError("no database")

    async with gpu_heartbeat(broken, "image", every=0.01):
        await asyncio.sleep(0.05)


async def test_beats_keep_one_row_per_worker(v2):  # noqa: F811
    _, factory, *_ = v2
    async with gpu_heartbeat(factory, "voice", every=0.01):
        await asyncio.sleep(0.1)
    async with factory() as session:
        rows = list(
            await session.scalars(
                select(NarrativeGpuStatus).where(NarrativeGpuStatus.name == "voice")
            )
        )
    assert len(rows) == 1


async def test_an_unknown_state_is_refused(v2):  # noqa: F811
    _, factory, *_ = v2
    async with factory() as session:
        with pytest.raises(ValueError, match="Unknown GPU state"):
            await record_gpu_state(session, "controller", "sleepy")
