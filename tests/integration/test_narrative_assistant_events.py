"""Durable live turn progress: fenced, bounded, resumable and served by sequence (#171)."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from flint_graph.application.services.narrative_assistant import (
    abandon_turn,
    claim_turn,
    complete_turn,
    fail_turn,
    register_turn_workflow,
)
from flint_graph.application.services.narrative_assistant_events import (
    TurnEventItem,
    TurnEventsClosed,
    TurnEventWriter,
    append_turn_events,
)
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.db.models import NarrativeAssistantTurn
from flint_graph.infrastructure.db.narrative_assistant_models import NarrativeAssistantTurnEvent
from flint_graph.infrastructure.narrative_assistant import DeterministicNarrativeAssistant
from flint_graph.main import app
from flint_graph.narrative.assistant.turn import AssistantModelError, run_turn

REPLY = "Thunder rolls in before the ending."
PROPOSAL = json.dumps(
    {
        "reply": REPLY,
        "proposal": {
            "summary": "Add a storm",
            "operations": [
                {
                    "op": "upsert_node",
                    "id": "storm",
                    "node": {"type": "line", "text": "Thunder.", "next": "ending"},
                },
                {
                    "op": "upsert_node",
                    "id": "opening",
                    "node": {"type": "line", "text": "A new story begins.", "next": "storm"},
                },
            ],
        },
    }
)


@pytest.fixture
def assistant_settings(narrative_env):
    settings = Settings(env="test")
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def story_case(narrative_env, assistant_settings):
    client, factory, backend = narrative_env

    async def start(name: str = "Live turn fixture", auth=None):
        workspace = (await client.post("/v1/workspaces", headers=auth, json={"name": name})).json()
        headers = {**(auth or {}), "X-Tenant-ID": workspace["id"]}
        project = (
            await client.post(
                "/v1/narrative/projects",
                headers=headers,
                json={"name": name, "idempotency_key": str(uuid4())},
            )
        ).json()
        path = f"/v1/narrative/projects/{project['id']}/assistant"
        thread = (
            await client.post(
                f"{path}/threads",
                headers=headers,
                json={"title": "Storms", "idempotency_key": str(uuid4())},
            )
        ).json()
        return headers, project, path, thread

    async def ask(headers, project, path, thread, request="Add a storm."):
        response = await client.post(
            f"{path}/threads/{thread['id']}/turns",
            headers=headers,
            json={
                "request": request,
                "base_revision_id": project["head_revision_id"],
                "focus_node": "opening",
                "idempotency_key": str(uuid4()),
            },
        )
        assert response.status_code == 202
        return response.json()

    return client, factory, backend, start, ask


async def claim(factory, turn_id, token, attempt=1, run=None):
    run = run or uuid4()
    async with factory() as session:
        turn = await session.get(NarrativeAssistantTurn, UUID(turn_id))
        await register_turn_workflow(
            session, tenant_id=turn.tenant_id, turn_id=turn.id, workflow_run_id=run
        )
        work = await claim_turn(
            session,
            turn_id=turn.id,
            execution_token=token,
            workflow_run_id=run,
            activity_attempt=attempt,
        )
        await session.commit()
    return work, run


async def events(factory, turn_id) -> list[NarrativeAssistantTurnEvent]:
    async with factory() as session:
        return list(
            await session.scalars(
                select(NarrativeAssistantTurnEvent)
                .where(NarrativeAssistantTurnEvent.turn_id == UUID(turn_id))
                .order_by(NarrativeAssistantTurnEvent.sequence)
            )
        )


async def worked(factory, turn_id, *script, chunk_chars=5):
    token = uuid4()
    work, _ = await claim(factory, turn_id, token)
    assert work is not None
    writer = TurnEventWriter(factory, turn_id=UUID(turn_id), execution_token=token)
    result = await run_turn(
        DeterministicNarrativeAssistant(script, chunk_chars=chunk_chars),
        work.story,
        work.request,
        focus=work.focus,
        history=work.history,
        observer=writer,
    )
    await writer.flush()
    async with factory() as session:
        await complete_turn(
            session,
            turn_id=UUID(turn_id),
            execution_token=token,
            result=result,
            provider="deterministic",
        )
        await session.commit()


def frames(body: str) -> list[dict]:
    parsed = []
    for frame in body.split("\n\n"):
        data = [line[6:] for line in frame.split("\n") if line.startswith("data: ")]
        if data:
            parsed.append(json.loads("".join(data)))
    return parsed


@pytest.mark.anyio
async def test_a_worked_turn_records_ordered_steps_thinking_text_and_one_final_status(story_case):
    client, factory, _, start, ask = story_case
    headers, project, path, thread = await start()
    turn = await ask(headers, project, path, thread)
    await worked(factory, turn["id"], ("Where does the storm fit?", PROPOSAL))

    rows = await events(factory, turn["id"])
    assert [row.sequence for row in rows] == list(range(1, len(rows) + 1))
    assert {row.attempt for row in rows} == {1}
    assert rows[0].kind == "step" and rows[0].payload == {"name": "start", "state": "done"}
    assert rows[-1].kind == "status"
    assert rows[-1].payload == {"status": "completed", "error_code": None}
    assert [row.kind for row in rows].count("status") == 1
    steps = [(r.payload["name"], r.payload["state"]) for r in rows if r.kind == "step"]
    assert steps[:3] == [("start", "done"), ("context", "done"), ("model", "started")]
    assert ("drafting", "started") in steps and steps[-1] == ("validating", "done")
    # Coalesced deltas: far fewer rows than five-character chunks, same text.
    texts = [r for r in rows if r.kind == "text"]
    assert "".join(r.payload["text"] for r in texts) == REPLY
    assert len(texts) < len(REPLY) / 5
    thinking = "".join(r.payload["text"] for r in rows if r.kind == "thinking")
    assert thinking == "Where does the storm fit?"
    assert all(r.payload["call"] == 1 for r in rows if r.kind in ("text", "thinking"))

    url = f"{path}/threads/{thread['id']}/turns/{turn['id']}/events"
    listed = (await client.get(url, headers=headers, params={"after_sequence": 2})).json()
    assert [item["sequence"] for item in listed] == [r.sequence for r in rows[2:]]
    assert listed[0]["turn_id"] == turn["id"]
    page = (await client.get(url, headers=headers, params={"limit": 2})).json()
    assert [item["sequence"] for item in page] == [1, 2]

    streamed = await client.get(f"{url}/stream", headers=headers)
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert streamed.text.startswith("retry: 1000\n\n")
    assert [item["sequence"] for item in frames(streamed.text)] == [r.sequence for r in rows]
    assert f"id: {rows[-1].sequence}\nevent: status\n" in streamed.text
    resumed = await client.get(
        f"{url}/stream", headers={**headers, "Last-Event-ID": str(rows[-3].sequence)}
    )
    assert [item["sequence"] for item in frames(resumed.text)] == [r.sequence for r in rows[-2:]]
    # A client that already has the final event gets an immediately closed stream.
    caught_up = await client.get(
        f"{url}/stream?after_sequence={rows[-1].sequence}", headers=headers
    )
    assert frames(caught_up.text) == []


@pytest.mark.anyio
async def test_the_stream_follows_a_running_turn_until_its_status_commits(story_case):
    client, factory, _, start, ask = story_case
    headers, project, path, thread = await start()
    turn = await ask(headers, project, path, thread)
    token = uuid4()
    await claim(factory, turn["id"], token)
    url = f"{path}/threads/{thread['id']}/turns/{turn['id']}/events/stream?after_sequence=1"

    async def progress():
        await asyncio.sleep(0.4)
        for text in ["The ", "storm ", "arrives."]:
            async with factory() as session:
                await append_turn_events(
                    session,
                    turn_id=UUID(turn["id"]),
                    execution_token=token,
                    items=[TurnEventItem("text", {"call": 1, "text": text})],
                )
                await session.commit()
            await asyncio.sleep(0.3)
        async with factory() as session:
            await fail_turn(
                session,
                turn_id=UUID(turn["id"]),
                execution_token=token,
                error_code="provider_timeout",
            )
            await session.commit()

    writer = asyncio.create_task(progress())
    response = await asyncio.wait_for(client.get(url, headers=headers), timeout=20)
    await writer
    received = frames(response.text)
    assert [item["kind"] for item in received] == ["text", "text", "text", "status"]
    assert "".join(item["payload"].get("text", "") for item in received) == "The storm arrives."
    assert received[-1]["payload"] == {"status": "failed", "error_code": "provider_timeout"}


@pytest.mark.anyio
async def test_every_terminal_transition_appends_exactly_one_status_event(story_case):
    client, factory, _, start, ask = story_case
    headers, project, path, thread = await start()

    async def finals(turn_id):
        return [(r.kind, r.payload) for r in await events(factory, turn_id) if r.kind == "status"]

    queued = await ask(headers, project, path, thread, "Queued then stopped.")
    cancel = f"{path}/threads/{thread['id']}/turns/{queued['id']}/cancel"
    assert (await client.post(cancel, headers=headers)).json()["status"] == "cancelled"
    await client.post(cancel, headers=headers)
    assert await finals(queued["id"]) == [("status", {"status": "cancelled", "error_code": None})]

    stopped = await ask(headers, project, path, thread, "Stopped before the claim.")
    async with factory() as session:
        row = await session.get(NarrativeAssistantTurn, UUID(stopped["id"]))
        row.cancel_requested = True
        await session.commit()
    assert (await claim(factory, stopped["id"], uuid4()))[0] is None
    assert await finals(stopped["id"]) == [("status", {"status": "cancelled", "error_code": None})]

    abandoned = await ask(headers, project, path, thread, "Worker died.")
    _, run = await claim(factory, abandoned["id"], uuid4())
    for _ in range(2):
        async with factory() as session:
            await abandon_turn(
                session,
                turn_id=UUID(abandoned["id"]),
                workflow_run_id=run,
                error_code="worker_interrupted",
            )
            await session.commit()
    assert await finals(abandoned["id"]) == [
        ("status", {"status": "failed", "error_code": "worker_interrupted"})
    ]

    completed = await ask(headers, project, path, thread, "Complete it.")
    await worked(factory, completed["id"], PROPOSAL)
    async with factory() as session:
        stale = await fail_turn(
            session,
            turn_id=UUID(completed["id"]),
            execution_token=uuid4(),
            error_code="assistant_failed",
        )
        await session.commit()
    assert stale.status == "completed"
    assert await finals(completed["id"]) == [
        ("status", {"status": "completed", "error_code": None})
    ]


@pytest.mark.anyio
async def test_writes_are_fenced_to_the_owner_and_stop_on_cancellation(story_case):
    client, factory, _, start, ask = story_case
    headers, project, path, thread = await start()
    turn = await ask(headers, project, path, thread)
    first, second = uuid4(), uuid4()
    await claim(factory, turn["id"], first, attempt=1)
    async with factory() as session:
        turn_row = await session.get(NarrativeAssistantTurn, UUID(turn["id"]))
        run = turn_row.workflow_run_id
    async with factory() as session:
        # A retry of the same run takes over; the first execution is now stale.
        await claim_turn(
            session,
            turn_id=UUID(turn["id"]),
            execution_token=second,
            workflow_run_id=run,
            activity_attempt=2,
        )
        await session.commit()
    stale = TurnEventWriter(factory, turn_id=UUID(turn["id"]), execution_token=first)
    with pytest.raises(AssistantModelError) as raised:
        await stale.step("model", "started", {"call": 1})
    assert raised.value.code == "stale_execution"
    with pytest.raises(AssistantModelError):
        await stale.flush()
    rows = await events(factory, turn["id"])
    assert [(r.attempt, r.payload.get("name")) for r in rows] == [(1, "start"), (2, "start")]

    owner = TurnEventWriter(factory, turn_id=UUID(turn["id"]), execution_token=second)
    await owner.step("model", "started", {"call": 1})
    cancel = f"{path}/threads/{thread['id']}/turns/{turn['id']}/cancel"
    assert (await client.post(cancel, headers=headers)).json()["cancel_requested"] is True
    with pytest.raises(AssistantModelError) as raised:
        await owner.step("model", "done", {"call": 1})
    assert raised.value.code == "cancelled"
    async with factory() as session:
        with pytest.raises(TurnEventsClosed):
            await append_turn_events(
                session,
                turn_id=UUID(turn["id"]),
                execution_token=second,
                items=[TurnEventItem("text", {"call": 1, "text": "late"})],
            )


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.anyio
async def test_deltas_are_batched_split_and_bounded_per_kind_and_per_turn(story_case):
    _, factory, _, start, ask = story_case
    headers, project, path, thread = await start()
    turn = await ask(headers, project, path, thread)
    token = uuid4()
    await claim(factory, turn["id"], token)
    clock = Clock()
    writer = TurnEventWriter(
        factory,
        turn_id=UUID(turn["id"]),
        execution_token=token,
        interval=1.0,
        flush_chars=10_000,
        limits={"thinking": 9000, "text": 20},
        max_events=14,
        step_reserve=4,
        clock=clock,
    )
    for _ in range(30):
        await writer.thinking(1, "x" * 250)  # Not due yet: nothing written.
    assert len(await events(factory, turn["id"])) == 1
    for state in ("progress", "progress"):
        await writer.step("drafting", state, {"call": 1, "operations": 1})
    clock.now = 2.0
    await writer.text(1, "y" * 15)
    await writer.text(1, "z" * 15)
    await writer.text(1, "w")
    await writer.flush()
    rows = await events(factory, turn["id"])
    thinking = [r for r in rows if r.kind == "thinking"]
    assert [len(r.payload["text"]) for r in thinking] == [4000, 3500]
    progress = [r for r in rows if r.payload.get("state") == "progress"]
    assert len(progress) == 1, "An unflushed progress step is replaced, not repeated"
    assert "".join(r.payload["text"] for r in rows if r.kind == "text") == "y" * 15 + "z" * 5
    truncated = [r.payload for r in rows if r.payload.get("name") == "truncated"]
    assert truncated == [{"name": "truncated", "state": "done", "kind": "text", "call": 1}]

    # Deltas stop short of the row cap so later steps still fit.
    for _ in range(8):
        clock.now += 2.0
        await writer.thinking(1, "t" * 10)
    rows = await events(factory, turn["id"])
    assert len(rows) == 10 and rows[-1].kind == "thinking"
    for index in range(20):
        await writer.step("model", "started", {"call": index})
    rows = await events(factory, turn["id"])
    assert len(rows) == 14, "The per-turn row cap drops further progress"
    truncated = [r.payload["kind"] for r in rows if r.payload.get("name") == "truncated"]
    assert truncated == ["text", "thinking"]
    assert [r.payload.get("call") for r in rows[-3:]] == [0, 1, 2]
    async with factory() as session:
        await fail_turn(
            session, turn_id=UUID(turn["id"]), execution_token=token, error_code="provider_timeout"
        )
        await session.commit()
    rows = await events(factory, turn["id"])
    assert len(rows) == 15 and rows[-1].kind == "status", "The final status is always kept"


@pytest.mark.anyio
async def test_long_streams_flush_less_often_after_the_first_rows(story_case):
    _, factory, _, start, ask = story_case
    headers, project, path, thread = await start()
    turn = await ask(headers, project, path, thread)
    token = uuid4()
    await claim(factory, turn["id"], token)
    clock = Clock()
    writer = TurnEventWriter(
        factory,
        turn_id=UUID(turn["id"]),
        execution_token=token,
        interval=1.0,
        slow_interval=5.0,
        fast_flushes=2,
        clock=clock,
    )
    written = []
    for second in range(1, 13):
        clock.now = float(second)
        await writer.thinking(1, "x")
        written.append(len(await events(factory, turn["id"])) - 1)
    # Every second while fresh, then every five seconds.
    assert written == [1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 4]


@pytest.mark.anyio
async def test_reads_are_scoped_and_legacy_turns_close_their_stream(story_case):
    client, factory, _, start, ask = story_case
    headers, project, path, thread = await start()
    turn = await ask(headers, project, path, thread)
    await worked(factory, turn["id"], PROPOSAL)
    other_headers, _, other_path, other_thread = await start("Other workspace")
    url = f"{path}/threads/{thread['id']}/turns/{turn['id']}/events"
    for foreign in [
        (url, other_headers),
        (f"{path}/threads/{uuid4()}/turns/{turn['id']}/events", headers),
        (f"{path}/threads/{thread['id']}/turns/{uuid4()}/events", headers),
        (f"{other_path}/threads/{other_thread['id']}/turns/{turn['id']}/events", other_headers),
    ]:
        for suffix in ("", "/stream"):
            response = await client.get(foreign[0] + suffix, headers=foreign[1])
            assert response.status_code == 404, foreign[0] + suffix

    legacy = await ask(headers, project, path, thread, "Before live progress.")
    async with factory() as session:
        row = await session.get(NarrativeAssistantTurn, UUID(legacy["id"]))
        row.status = "completed"
        await session.commit()
    response = await asyncio.wait_for(
        client.get(
            f"{path}/threads/{thread['id']}/turns/{legacy['id']}/events/stream", headers=headers
        ),
        timeout=10,
    )
    assert response.status_code == 200 and frames(response.text) == []
