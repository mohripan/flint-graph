"""GPU work reaches Temporal with no GPU worker running (#196, ADR 0070)."""

import asyncio
import inspect
import json
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from sqlalchemy import select
from test_narrative_assistant_actions import (
    BACKGROUND,
    actions,
    propose,
    queue,
    setup,  # noqa: F401
)
from test_narrative_assistant_api import ask, new_story, new_thread, turns, work
from test_narrative_characters_api import MemoryStore

from flint_graph.application.services import narrative_gpu_dispatch
from flint_graph.application.services.narrative_gpu_dispatch import (
    GpuDispatchers,
    dispatch_gpu_work,
)
from flint_graph.config import Settings
from flint_graph.infrastructure.db.models import NarrativeImageJob, OutboxMessage
from flint_graph.processes import (
    narrative_assistant_worker,
    narrative_image_worker,
    narrative_music_worker,
    narrative_pose_worker,
    narrative_style_worker,
    narrative_voice_worker,
)
from flint_graph.processes.narrative_gpu_dispatch import build_dispatchers

pytestmark = pytest.mark.anyio


class Queue:
    """Stands in for one Temporal task queue with nobody polling it."""

    def __init__(self, fail=False):
        self.started, self.closed_runs, self.fail = [], set(), fail

    async def start(self, payload):
        if self.fail:
            raise RuntimeError("temporal is away")
        self.started.append(payload)
        return uuid5(NAMESPACE_URL, json.dumps(payload, sort_keys=True))

    async def cancel(self, payload, *, run_id):
        return None

    async def closed(self, payload, *, run_id):
        return run_id in self.closed_runs


async def one_pass(factory, settings, store=None, recover=False, **queues):
    return await dispatch_gpu_work(
        factory,
        dispatchers=GpuDispatchers(**queues),
        settings=settings,
        store=store or MemoryStore(),
        recover=recover,
    )


async def test_a_chat_message_waits_on_its_queue_then_runs_when_a_worker_starts(
    narrative_env,
    setup,  # noqa: F811
):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    posted = await ask(client, headers, path, thread, project["head_revision_id"])
    assert posted.status_code == 202, posted.text
    assistant = Queue()
    done = await one_pass(factory, settings, store, assistant=assistant)
    assert done["assistant"] == 1
    assert len(assistant.started) == 1
    [waiting] = await turns(client, headers, path, thread)
    assert waiting["status"] == "queued", "nobody has run it yet, and nothing failed"
    # Dispatched once, however long the machine stays off.
    assert (await one_pass(factory, settings, store, assistant=assistant))["assistant"] == 0
    assert len(assistant.started) == 1
    # A worker that starts later picks it up.
    run = uuid5(NAMESPACE_URL, json.dumps(assistant.started[0], sort_keys=True))
    reply = json.dumps({"reply": "Hi.", "proposal": None})
    await work(factory, posted.json()["id"], reply, run=run)
    [answered] = await turns(client, headers, path, thread)
    assert answered["status"] == "completed"


async def test_a_pressed_action_becomes_a_queued_job_with_no_gpu_worker(
    narrative_env,
    setup,  # noqa: F811
):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    _, proposal = await propose(
        client, factory, headers, path, project["head_revision_id"], BACKGROUND
    )
    await queue(factory, headers, project, proposal)
    image = Queue()
    done = await one_pass(factory, settings, store, image=image)
    assert (done["actions"], done["image"]) == (1, 1), "on its queue by the end of the same pass"
    [started] = await actions(client, headers, path, proposal)
    assert (started["status"], started["image_job"]["status"]) == ("started", "queued")


async def test_nothing_the_creator_has_not_pressed_is_dispatched(
    narrative_env,
    setup,  # noqa: F811
):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    await propose(client, factory, headers, path, project["head_revision_id"], BACKGROUND)
    image = Queue()
    done = await one_pass(factory, settings, store, image=image)
    assert (done["actions"], done["image"], image.started) == (0, 0, [])


async def test_temporal_being_away_from_one_queue_holds_up_no_other(
    narrative_env,
    setup,  # noqa: F811
    monkeypatch,
):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    await ask(client, headers, path, thread, project["head_revision_id"])

    async def broken(*args, **kwargs):
        raise RuntimeError("no such queue")

    monkeypatch.setattr(narrative_gpu_dispatch, "relay_image_batch", broken)
    assistant = Queue()
    done = await one_pass(factory, settings, store, image=Queue(), assistant=assistant)
    assert "image" not in done
    assert done["assistant"] == 1


async def test_a_failed_start_stays_in_the_outbox_for_later(
    narrative_env,
    setup,  # noqa: F811
):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    await ask(client, headers, path, thread, project["head_revision_id"])
    assert (await one_pass(factory, settings, store, assistant=Queue(fail=True)))["assistant"] == 0
    async with factory() as session:
        waiting = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.aggregate_type == "narrative_assistant_turn")
        )
    assert waiting.status == "pending"
    assert waiting.attempt_count == 1


async def test_recovery_only_closes_a_job_whose_run_really_ended(
    narrative_env,
    setup,  # noqa: F811
):
    """A job waiting hours for the GPU has a live run, and must not be failed for waiting."""
    client, factory, _ = narrative_env
    settings, store = setup
    headers, _, path = await new_story(client)
    created = await client.post(
        f"{path}/assets/background-jobs",
        headers=headers,
        json={"description": "harbor", "count": 1, "idempotency_key": str(uuid4())},
    )
    assert created.status_code == 202, created.text
    job_id = UUID(created.json()["id"])
    image = Queue()
    await one_pass(factory, settings, store, image=image)
    async with factory() as session:
        job = await session.get(NarrativeImageJob, job_id)
        job.created_at = datetime.now(UTC) - timedelta(hours=3)
        run_id = job.workflow_run_id
        await session.commit()
    assert (await one_pass(factory, settings, store, recover=True, image=image))[
        "image.recover"
    ] == 0
    async with factory() as session:
        assert (await session.get(NarrativeImageJob, job_id)).status == "queued"
    image.closed_runs.add(run_id)
    assert (await one_pass(factory, settings, store, recover=True, image=image))[
        "image.recover"
    ] == 1
    async with factory() as session:
        assert (await session.get(NarrativeImageJob, job_id)).status == "failed"


async def test_two_dispatchers_during_a_rollout_register_one_run_per_job(
    narrative_env,
    setup,  # noqa: F811
):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, _, path = await new_story(client)
    created = await client.post(
        f"{path}/assets/background-jobs",
        headers=headers,
        json={"description": "harbor", "count": 1, "idempotency_key": str(uuid4())},
    )
    image = Queue()
    await asyncio.gather(*(one_pass(factory, settings, store, image=image) for _ in range(2)))
    # Row locks let one through. Were two to get there, Temporal's workflow ID is the same.
    assert len({json.dumps(item, sort_keys=True) for item in image.started}) == 1
    async with factory() as session:
        job = await session.get(NarrativeImageJob, UUID(created.json()["id"]))
    assert job.workflow_run_id == uuid5(NAMESPACE_URL, json.dumps(image.started[0], sort_keys=True))


def test_only_the_kinds_a_server_runs_get_a_dispatcher():
    plain = Settings(env="test").model_copy(update={"narrative_assistant_provider": "disabled"})
    assert build_dispatchers(object(), plain) == GpuDispatchers()
    on = plain.model_copy(
        update={
            "narrative_image_generation_enabled": True,
            "narrative_voice_generation_enabled": True,
            "narrative_music_generation_enabled": True,
            "narrative_style_training_enabled": True,
            "narrative_pose_generation_enabled": True,
            "narrative_assistant_provider": "ollama",
        }
    )
    built = build_dispatchers(object(), on)
    assert all(getattr(built, kind) is not None for kind in GpuDispatchers.__dataclass_fields__)


@pytest.mark.parametrize(
    "worker",
    [
        narrative_assistant_worker,
        narrative_image_worker,
        narrative_music_worker,
        narrative_pose_worker,
        narrative_style_worker,
        narrative_voice_worker,
    ],
)
def test_every_gpu_worker_can_leave_dispatch_to_the_always_on_tier(worker):
    source = inspect.getsource(worker)
    assert "narrative_gpu_execute_only" in source
    assert source.index("narrative_gpu_execute_only") < source.rindex("relay_") or (
        "maintain(" in source
        and source.index("narrative_gpu_execute_only") < source.rindex("await maintain(")
    )
