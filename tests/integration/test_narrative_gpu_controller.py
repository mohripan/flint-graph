"""The controller against a fake machine and a real database (#197, #198, ADR 0070)."""

from datetime import UTC, datetime, timedelta

import pytest
from test_narrative_assistant_api import ask, new_story, new_thread
from test_narrative_package_v2_api import configure, v2  # noqa: F401

from flint_graph.application.services.narrative_gpu import record_gpu_state
from flint_graph.application.services.narrative_gpu_control import (
    GpuController,
    InstanceView,
    NoCapacity,
    Policy,
)
from flint_graph.config import Settings

pytestmark = pytest.mark.anyio
START = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


class Machine:
    def __init__(self, state="stopped", refuse=0):
        self.state, self.refuse, self.calls, self.launched = state, refuse, [], None

    async def describe(self):
        return InstanceView(self.state, self.launched)

    async def start(self):
        self.calls.append("start")
        if self.refuse:
            self.refuse -= 1
            raise NoCapacity
        self.state = "pending"

    async def stop(self):
        self.calls.append("stop")
        self.state = "stopping"


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now

    def move(self, **amount):
        self.now += timedelta(**amount)


SETTINGS = Settings(env="test").model_copy(
    update={
        "narrative_assistant_provider": "ollama",
        "narrative_image_generation_enabled": True,
        "narrative_gpu_sleeps": True,
    }
)


def controller(factory, machine, clock, **policy):
    return GpuController(
        factory,
        instance=machine,
        settings=SETTINGS,
        policy=Policy(**{"daily_cap": None, **policy}),
        clock=clock,
    )


async def beat(factory, clock, worker="assistant"):
    async with factory() as session:
        await record_gpu_state(session, worker, now=clock())
        await session.commit()


async def queue_a_message(client, factory):
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    posted = await ask(client, headers, path, thread, project["head_revision_id"])
    assert posted.status_code == 202, posted.text
    return headers, path, thread, posted.json()


async def finish(factory, turn):
    from uuid import UUID

    from flint_graph.infrastructure.db.models import NarrativeAssistantTurn

    async with factory() as session:
        row = await session.get(NarrativeAssistantTurn, UUID(turn["id"]))
        row.status = "completed"
        await session.commit()


async def test_a_quiet_stopped_machine_is_not_started(narrative_env):
    _, factory, _ = narrative_env
    machine, clock = Machine(), Clock()
    step = await controller(factory, machine, clock).tick()
    assert (step.state, machine.calls) == ("stopped", [])


async def test_a_full_day_in_the_life_of_the_machine(narrative_env):
    client, factory, _ = narrative_env
    machine, clock = Machine(), Clock()
    gpu = controller(factory, machine, clock)
    # A chat message wakes it; asking again while it boots does not start it twice.
    headers, path, thread, turn = await queue_a_message(client, factory)
    head = turn["base_revision_id"]
    assert (await gpu.tick()).state == "starting"
    assert machine.calls == ["start"]
    assert (await gpu.tick()).state == "starting"
    assert machine.calls == ["start"]
    # It boots and its workers come up.
    machine.state, machine.launched = "running", clock()
    await beat(factory, clock)
    assert (await gpu.tick()).state == "ready"
    # The reply finishes; it stays up through the idle period and not past it.
    await finish(factory, turn)
    clock.move(minutes=4, seconds=59)
    await beat(factory, clock)
    assert (await gpu.tick()).action is None
    clock.move(seconds=2)
    assert (await gpu.tick()).action is None, "the idle clock started at the first quiet look"
    clock.move(minutes=5)
    await beat(factory, clock)
    assert (await gpu.tick()).action == "stop"
    assert machine.calls == ["start", "stop"]
    # A message arriving as it goes down waits, then wakes it again. Nothing is lost.
    assert (await ask(client, headers, path, thread, head)).status_code == 202
    assert (await gpu.tick()).state == "stopping"
    machine.state = "stopped"
    assert (await gpu.tick()).action == "start"
    assert machine.calls == ["start", "stop", "start"]


async def test_no_capacity_backs_off_and_the_message_says_so(narrative_env):
    client, factory, _ = narrative_env
    machine, clock = Machine(refuse=2), Clock()
    gpu = controller(factory, machine, clock)
    await queue_a_message(client, factory)
    step = await gpu.tick()
    assert (step.state, step.detail) == ("unavailable", "no_capacity")
    assert machine.calls == ["start"]
    # Not again until the wait is over, and it grows.
    await gpu.tick()
    assert machine.calls == ["start"]
    clock.move(seconds=31)
    assert (await gpu.tick()).detail == "no_capacity"
    assert machine.calls == ["start", "start"]
    clock.move(seconds=31)
    await gpu.tick()
    assert machine.calls == ["start", "start"], "the second wait is a minute"
    clock.move(seconds=31)
    assert (await gpu.tick()).state == "starting"
    assert machine.calls == ["start", "start", "start"]


async def test_the_daily_cap_counts_real_running_time(narrative_env):
    client, factory, _ = narrative_env
    machine, clock = Machine("running"), Clock()
    machine.launched = clock()
    gpu = controller(factory, machine, clock, daily_cap=timedelta(hours=1), idle=timedelta(hours=9))
    await beat(factory, clock)
    assert (await gpu.tick()).state == "ready"
    clock.move(minutes=59)
    await beat(factory, clock)
    assert (await gpu.tick()).state == "ready"
    clock.move(minutes=2)
    await beat(factory, clock)
    step = await gpu.tick()
    assert (step.action, step.detail) == ("stop", "daily_cap")
    # Stopped, it stays stopped however much is queued.
    machine.state, machine.launched = "stopped", None
    await queue_a_message(client, factory)
    assert machine.calls == ["stop"]
    step = await gpu.tick()
    assert (step.state, step.detail, machine.calls) == ("unavailable", "daily_cap", ["stop"])


async def test_tomorrow_the_cap_starts_again(narrative_env):
    client, factory, _ = narrative_env
    machine, clock = Machine("running"), Clock()
    machine.launched = clock()
    gpu = controller(factory, machine, clock, daily_cap=timedelta(hours=1), idle=timedelta(hours=9))
    await beat(factory, clock)
    await gpu.tick()
    clock.move(minutes=61)
    await gpu.tick()
    machine.state, machine.launched = "stopped", None
    await queue_a_message(client, factory)
    clock.move(days=1)
    assert (await gpu.tick()).action == "start"


async def test_the_studio_reads_what_the_controller_recorded(v2, oidc_auth):  # noqa: F811
    client, factory, _, owner, _ = v2
    configure(narrative_image_generation_enabled=True, narrative_gpu_sleeps=True)
    machine = Machine()
    gpu = GpuController(
        factory,
        instance=machine,
        settings=SETTINGS,
        policy=Policy(),
    )
    await gpu.tick()
    seen = (await client.get("/v1/narrative/gpu", headers=owner)).json()
    assert seen["state"] == "asleep"
    machine.state = "pending"
    await gpu.tick()
    assert (await client.get("/v1/narrative/gpu", headers=owner)).json()["state"] == "starting"
