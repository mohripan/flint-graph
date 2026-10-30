"""Project assistant threads, durable turns and reviewed proposals (no model in requests)."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from flint_graph.application.services.narrative_assistant import (
    claim_turn,
    complete_turn,
    fail_turn,
    register_turn_workflow,
)
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.db.models import NarrativeAssistantTurn, OutboxMessage, Tenant
from flint_graph.infrastructure.narrative_assistant import DeterministicNarrativeAssistant
from flint_graph.main import app
from flint_graph.narrative.assistant.turn import run_turn


@pytest.fixture
def assistant_settings(narrative_env):
    settings = Settings(env="test")
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


def proposal(next_scene: str = "ending", opening_text: str = "A new story begins.") -> str:
    return json.dumps(
        {
            "reply": "Here is a storm before the ending.",
            "proposal": {
                "summary": "Add a storm scene",
                "operations": [
                    {
                        "op": "upsert_node",
                        "id": "storm",
                        "node": {"type": "line", "text": "Thunder rolls.", "next": next_scene},
                    },
                    {
                        "op": "upsert_node",
                        "id": "opening",
                        "node": {"type": "line", "text": opening_text, "next": "storm"},
                    },
                ],
            },
        }
    )


async def new_story(client, name="Assistant fixture", auth=None):
    workspace = (await client.post("/v1/workspaces", headers=auth, json={"name": name})).json()
    headers = {**(auth or {}), "X-Tenant-ID": workspace["id"]}
    project = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": name, "idempotency_key": str(uuid4())},
        )
    ).json()
    return headers, project, f"/v1/narrative/projects/{project['id']}"


async def new_thread(client, headers, path):
    created = await client.post(
        f"{path}/assistant/threads",
        headers=headers,
        json={"title": "Storm ideas", "idempotency_key": str(uuid4())},
    )
    assert created.status_code == 201
    return created.json()


async def ask(client, headers, path, thread, base, request="Add a storm.", key=None):
    return await client.post(
        f"{path}/assistant/threads/{thread['id']}/turns",
        headers=headers,
        json={
            "request": request,
            "base_revision_id": base,
            "focus_node": "opening",
            "idempotency_key": key or str(uuid4()),
        },
    )


async def claim(factory, turn_id, token, run=None):
    # Production order: the relay registers the accepted run before any claim.
    run = run or uuid4()
    async with factory() as session:
        turn = await session.get(NarrativeAssistantTurn, UUID(turn_id))
        await register_turn_workflow(
            session, tenant_id=turn.tenant_id, turn_id=turn.id, workflow_run_id=run
        )
        claimed = await claim_turn(
            session,
            turn_id=UUID(turn_id),
            execution_token=token,
            workflow_run_id=run,
            activity_attempt=1,
        )
        await session.commit()
    return claimed


async def work(factory, turn_id, *script):
    token = uuid4()
    claimed = await claim(factory, turn_id, token)
    assert claimed is not None
    result = await run_turn(
        DeterministicNarrativeAssistant(script),
        claimed.story,
        claimed.request,
        focus=claimed.focus,
        history=claimed.history,
    )
    async with factory() as session:
        await complete_turn(
            session,
            turn_id=UUID(turn_id),
            execution_token=token,
            result=result,
            provider="deterministic",
        )
        await session.commit()
    return claimed


async def turns(client, headers, path, thread):
    response = await client.get(f"{path}/assistant/threads/{thread['id']}/turns", headers=headers)
    assert response.status_code == 200
    return response.json()


@pytest.mark.anyio
async def test_threads_are_project_scoped_and_creation_keys_replay(
    narrative_env, assistant_settings
):
    client, _, _ = narrative_env
    headers, project, path = await new_story(client)
    request = {"title": "Storm ideas", "idempotency_key": str(uuid4())}
    created = await client.post(f"{path}/assistant/threads", headers=headers, json=request)
    assert created.status_code == 201
    thread = created.json()
    assert thread["project_id"] == project["id"] and thread["title"] == "Storm ideas"
    replay = await client.post(f"{path}/assistant/threads", headers=headers, json=request)
    assert replay.status_code == 201 and replay.json() == thread
    changed = await client.post(
        f"{path}/assistant/threads", headers=headers, json={**request, "title": "Other"}
    )
    assert changed.status_code == 409
    listed = await client.get(f"{path}/assistant/threads", headers=headers)
    assert [row["id"] for row in listed.json()] == [thread["id"]]
    _, _, other_path = await new_story(client, name="Other story")
    foreign = await client.get(f"{other_path}/assistant/threads/{thread['id']}", headers=headers)
    assert foreign.status_code == 404


@pytest.mark.anyio
async def test_turns_queue_with_an_id_only_outbox_message_and_replay_their_key(
    narrative_env, assistant_settings
):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    key = str(uuid4())
    queued = await ask(client, headers, path, thread, project["head_revision_id"], key=key)
    assert queued.status_code == 202
    turn = queued.json()
    assert (turn["sequence"], turn["status"], turn["request"]) == (1, "queued", "Add a storm.")
    assert turn["proposal"] is None and turn["reply"] is None
    replay = await ask(client, headers, path, thread, project["head_revision_id"], key=key)
    assert replay.status_code == 202 and replay.json()["id"] == turn["id"]
    changed = await ask(
        client, headers, path, thread, project["head_revision_id"], "Different.", key=key
    )
    assert changed.status_code == 409
    async with factory() as session:
        message = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.topic == "narrative.assistant_turn_queued")
        )
    assert message is not None
    assert message.payload == {
        "schema_version": "1",
        "tenant_id": project["tenant_id"],
        "turn_id": turn["id"],
    }
    assert "storm" not in json.dumps(message.payload).lower()
    busy = await ask(client, headers, path, thread, project["head_revision_id"])
    assert busy.status_code == 429, "One active turn per workspace by default"
    _, foreign, _ = await new_story(client, name="Foreign")
    wrong_revision = await ask(client, headers, path, thread, foreign["head_revision_id"])
    assert wrong_revision.status_code == 404


@pytest.mark.anyio
async def test_disabled_assistant_rejects_new_turns_but_replays_accepted_ones(narrative_env):
    client, _, _ = narrative_env
    enabled = Settings(env="test")
    app.dependency_overrides[get_settings] = lambda: enabled
    try:
        headers, project, path = await new_story(client)
        thread = await new_thread(client, headers, path)
        key = str(uuid4())
        accepted = await ask(client, headers, path, thread, project["head_revision_id"], key=key)
        disabled = Settings(env="test", narrative_assistant_provider="disabled")
        app.dependency_overrides[get_settings] = lambda: disabled
        replay = await ask(client, headers, path, thread, project["head_revision_id"], key=key)
        assert replay.status_code == 202 and replay.json()["id"] == accepted.json()["id"]
        refused = await ask(client, headers, path, thread, project["head_revision_id"])
        assert refused.status_code == 503
        assert refused.json()["type"].endswith("assistant-unavailable")
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.anyio
async def test_completed_turn_shows_reply_and_reviewable_proposal_with_history(
    narrative_env, assistant_settings
):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    first = (await ask(client, headers, path, thread, project["head_revision_id"])).json()
    claimed = await work(factory, first["id"], proposal())
    assert claimed.history == ()
    assert claimed.story["nodes"]["opening"]["next"] == "ending"
    [turn] = await turns(client, headers, path, thread)
    assert (turn["status"], turn["reply"]) == ("completed", "Here is a storm before the ending.")
    summary = turn["proposal"]
    assert (summary["status"], summary["summary"]) == ("ready", "Add a storm scene")
    assert summary["touched"] == ["nodes.opening", "nodes.storm"]
    detail = (
        await client.get(f"{path}/assistant/proposals/{summary['id']}", headers=headers)
    ).json()
    assert detail["base_revision_id"] == project["head_revision_id"]
    assert [op["id"] for op in detail["operations"]] == ["storm", "opening"]
    assert detail["diagnostics"] == [] and detail["accepted_revision_id"] is None
    second = (await ask(client, headers, path, thread, project["head_revision_id"], "More.")).json()
    assert second["sequence"] == 2
    claimed = await work(
        factory, second["id"], json.dumps({"reply": "Nothing to add.", "proposal": None})
    )
    assert [(item.role, item.content) for item in claimed.history] == [
        ("user", "Add a storm."),
        ("assistant", "Here is a storm before the ending."),
    ]
    later = await turns(client, headers, path, thread)
    assert later[1]["proposal"] is None and later[1]["reply"] == "Nothing to add."


@pytest.mark.anyio
async def test_accepting_creates_one_revision_on_head_and_replays_its_key(
    narrative_env, assistant_settings
):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    turn = (await ask(client, headers, path, thread, project["head_revision_id"])).json()
    await work(factory, turn["id"], proposal())
    proposal_id = (await turns(client, headers, path, thread))[0]["proposal"]["id"]
    key = {"idempotency_key": str(uuid4())}
    accept = f"{path}/assistant/proposals/{proposal_id}/accept"
    created = await client.post(accept, headers=headers, json=key)
    assert created.status_code == 201
    revision = created.json()
    assert revision["parent_revision_id"] == project["head_revision_id"]
    assert not revision["conflicted"] and revision["revision_number"] == 2
    story = json.loads(revision["story_json"])
    assert story["nodes"]["opening"]["next"] == "storm"
    assert story["nodes"]["opening"]["text_id"] == "opening_text"
    head = (await client.get(path, headers=headers)).json()["head_revision_id"]
    assert head == revision["id"]
    replay = await client.post(accept, headers=headers, json=key)
    assert replay.status_code == 201 and replay.json()["id"] == revision["id"]
    other_key = await client.post(accept, headers=headers, json={"idempotency_key": str(uuid4())})
    assert other_key.status_code == 409
    detail = (await client.get(f"{path}/assistant/proposals/{proposal_id}", headers=headers)).json()
    assert (detail["status"], detail["accepted_revision_id"]) == ("accepted", revision["id"])
    rejected = await client.post(
        f"{path}/assistant/proposals/{proposal_id}/reject", headers=headers
    )
    assert rejected.status_code == 409


async def save_ending(client, headers, path, base, text):
    current = (await client.get(f"{path}/revisions/{base}", headers=headers)).json()
    story = json.loads(current["story_json"])
    story["nodes"]["ending"]["text"] = text
    saved = await client.post(
        f"{path}/revisions",
        headers=headers,
        json={
            "base_revision_id": base,
            "idempotency_key": str(uuid4()),
            "story_json": json.dumps(story),
            "notices": "",
        },
    )
    assert saved.status_code == 201
    return saved.json()


@pytest.mark.anyio
async def test_stale_proposals_rebase_when_untouched_and_conflict_when_overlapping(
    narrative_env, assistant_settings
):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    base = project["head_revision_id"]
    turn = (await ask(client, headers, path, thread, base)).json()
    await work(factory, turn["id"], proposal())
    proposal_id = (await turns(client, headers, path, thread))[-1]["proposal"]["id"]
    unrelated = await save_ending(client, headers, path, base, "The storm passes.")
    rebased = await client.post(
        f"{path}/assistant/proposals/{proposal_id}/accept",
        headers=headers,
        json={"idempotency_key": str(uuid4())},
    )
    assert rebased.status_code == 201
    revision = rebased.json()
    assert revision["parent_revision_id"] == unrelated["id"] and not revision["conflicted"]
    story = json.loads(revision["story_json"])
    assert story["nodes"]["ending"]["text"] == "The storm passes."
    assert story["nodes"]["opening"]["next"] == "storm"

    second = (await ask(client, headers, path, thread, revision["id"], "Again.")).json()
    await work(factory, second["id"], proposal("ending", "A darker dawn."))
    overlapping = (await turns(client, headers, path, thread))[-1]["proposal"]["id"]
    current = (await client.get(f"{path}/revisions/{revision['id']}", headers=headers)).json()
    changed = json.loads(current["story_json"])
    changed["nodes"]["opening"]["text"] = "Someone else rewrote the opening."
    manual = await client.post(
        f"{path}/revisions",
        headers=headers,
        json={
            "base_revision_id": revision["id"],
            "idempotency_key": str(uuid4()),
            "story_json": json.dumps(changed),
            "notices": "",
        },
    )
    assert manual.status_code == 201
    conflict = await client.post(
        f"{path}/assistant/proposals/{overlapping}/accept",
        headers=headers,
        json={"idempotency_key": str(uuid4())},
    )
    assert conflict.status_code == 409
    error = conflict.json()["errors"][0]
    assert error["code"] == "stale_revision"
    assert error["observed_head_revision_id"] == manual.json()["id"]
    head = (await client.get(path, headers=headers)).json()["head_revision_id"]
    assert head == manual.json()["id"], "The current story is unchanged"
    kept = (
        await client.get(f"{path}/revisions/{error['conflict_revision_id']}", headers=headers)
    ).json()
    assert kept["conflicted"] and json.loads(kept["story_json"])["nodes"]["opening"]["text"] == (
        "A darker dawn."
    )


@pytest.mark.anyio
async def test_invalid_and_rejected_proposals_are_never_accepted(narrative_env, assistant_settings):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    base = project["head_revision_id"]
    broken = proposal("nowhere")
    turn = (await ask(client, headers, path, thread, base)).json()
    await work(factory, turn["id"], broken, broken, broken)
    invalid = (await turns(client, headers, path, thread))[0]["proposal"]
    assert invalid["status"] == "invalid"
    detail = (
        await client.get(f"{path}/assistant/proposals/{invalid['id']}", headers=headers)
    ).json()
    assert detail["diagnostics"] == [{"code": "unknown_reference", "location": "nodes.storm.next"}]
    refused = await client.post(
        f"{path}/assistant/proposals/{invalid['id']}/accept",
        headers=headers,
        json={"idempotency_key": str(uuid4())},
    )
    assert refused.status_code == 409
    second = (await ask(client, headers, path, thread, base, "Again.")).json()
    await work(factory, second["id"], proposal())
    ready = (await turns(client, headers, path, thread))[1]["proposal"]["id"]
    reject = f"{path}/assistant/proposals/{ready}/reject"
    assert (await client.post(reject, headers=headers)).json()["status"] == "rejected"
    assert (await client.post(reject, headers=headers)).status_code == 200
    assert (
        await client.post(
            f"{path}/assistant/proposals/{ready}/accept",
            headers=headers,
            json={"idempotency_key": str(uuid4())},
        )
    ).status_code == 409


@pytest.mark.anyio
async def test_cancellation_and_stale_executions_are_fenced(narrative_env, assistant_settings):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    base = project["head_revision_id"]
    queued = (await ask(client, headers, path, thread, base)).json()
    cancel = f"{path}/assistant/threads/{thread['id']}/turns/{queued['id']}/cancel"
    assert (await client.post(cancel, headers=headers)).json()["status"] == "cancelled"
    assert (await client.post(cancel, headers=headers)).json()["status"] == "cancelled"
    async with factory() as session:
        assert (
            await claim_turn(
                session,
                turn_id=UUID(queued["id"]),
                execution_token=uuid4(),
                workflow_run_id=uuid4(),
                activity_attempt=1,
            )
            is None
        )

    running = (await ask(client, headers, path, thread, base, "Again.")).json()
    token = uuid4()
    claimed = await claim(factory, running["id"], token)
    assert claimed is not None
    result = await run_turn(DeterministicNarrativeAssistant([proposal()]), claimed.story, "Again.")
    async with factory() as session:
        stale = await complete_turn(
            session,
            turn_id=UUID(running["id"]),
            execution_token=uuid4(),
            result=result,
            provider="deterministic",
        )
        await session.commit()
    assert stale.status == "running", "A replaced or stale execution cannot complete the turn"
    requested = await client.post(
        f"{path}/assistant/threads/{thread['id']}/turns/{running['id']}/cancel", headers=headers
    )
    assert requested.json()["status"] == "running" and requested.json()["cancel_requested"]
    async with factory() as session:
        done = await complete_turn(
            session,
            turn_id=UUID(running["id"]),
            execution_token=token,
            result=result,
            provider="deterministic",
        )
        await session.commit()
    assert done.status == "cancelled"
    final = (await turns(client, headers, path, thread))[-1]
    assert final["status"] == "cancelled" and final["proposal"] is None

    failing = (await ask(client, headers, path, thread, base, "Fail.")).json()
    token = uuid4()
    assert await claim(factory, failing["id"], token) is not None
    async with factory() as session:
        failed = await fail_turn(
            session,
            turn_id=UUID(failing["id"]),
            execution_token=token,
            error_code="provider_timeout",
        )
        await session.commit()
    assert (failed.status, failed.error_code) == ("failed", "provider_timeout")


@pytest.mark.anyio
async def test_viewers_read_threads_but_cannot_write_or_decide(narrative_env, oidc_auth):
    client, factory, _ = narrative_env
    owner = {"Authorization": "Bearer " + oidc_auth("assistant-owner")}
    headers, project, path = await new_story(client, auth=owner)
    added = await client.post(
        f"/v1/workspaces/{project['tenant_id']}/members",
        headers=owner,
        json={
            "oidc_issuer": "https://keycloak.example/realms/flintgraph",
            "oidc_subject": "assistant-viewer",
            "role": "viewer",
        },
    )
    assert added.status_code == 201
    configured = app.dependency_overrides[get_settings]().model_copy(
        update={"narrative_assistant_provider": "deterministic"}
    )
    app.dependency_overrides[get_settings] = lambda: configured
    viewer = {**headers, "Authorization": "Bearer " + oidc_auth("assistant-viewer")}
    thread = await new_thread(client, headers, path)
    turn = (await ask(client, headers, path, thread, project["head_revision_id"])).json()
    await work(factory, turn["id"], proposal())
    proposal_id = (await turns(client, headers, path, thread))[0]["proposal"]["id"]
    for read in [
        f"{path}/assistant/threads",
        f"{path}/assistant/threads/{thread['id']}",
        f"{path}/assistant/threads/{thread['id']}/turns",
        f"{path}/assistant/threads/{thread['id']}/turns/{turn['id']}/events",
        f"{path}/assistant/threads/{thread['id']}/turns/{turn['id']}/events/stream",
        f"{path}/assistant/proposals/{proposal_id}",
    ]:
        assert (await client.get(read, headers=viewer)).status_code == 200
    assert (
        await client.post(
            f"{path}/assistant/threads",
            headers=viewer,
            json={"title": "x", "idempotency_key": str(uuid4())},
        )
    ).status_code == 403
    assert (await ask(client, viewer, path, thread, project["head_revision_id"])).status_code == 403
    for write in ["accept", "reject"]:
        assert (
            await client.post(
                f"{path}/assistant/proposals/{proposal_id}/{write}",
                headers=viewer,
                json={"idempotency_key": str(uuid4())},
            )
        ).status_code == 403
    assert (
        await client.post(
            f"{path}/assistant/threads/{thread['id']}/turns/{turn['id']}/cancel", headers=viewer
        )
    ).status_code == 403


@pytest.mark.anyio
async def test_postgres_concurrent_turns_share_the_workspace_limit(narrative_env, oidc_auth):
    client, factory, backend = narrative_env
    if backend != "postgres":
        pytest.skip("Requires the actual workspace admission lock")
    configured = app.dependency_overrides[get_settings]().model_copy(
        update={"narrative_assistant_provider": "deterministic"}
    )
    app.dependency_overrides[get_settings] = lambda: configured
    owner = {"Authorization": "Bearer " + oidc_auth("assistant-admission-owner")}
    headers, project, path = await new_story(client, auth=owner)
    writers = []
    for subject in ["assistant-admit-one", "assistant-admit-two"]:
        assert (
            await client.post(
                f"/v1/workspaces/{project['tenant_id']}/members",
                headers=owner,
                json={
                    "oidc_issuer": "https://keycloak.example/realms/flintgraph",
                    "oidc_subject": subject,
                    "role": "member",
                },
            )
        ).status_code == 201
        actor = {**headers, "Authorization": "Bearer " + oidc_auth(subject)}
        # Separate threads: only the workspace lock can serialize these admissions.
        writers.append((actor, await new_thread(client, actor, path)))
    tasks = []
    async with factory() as blocker:
        await blocker.scalar(
            select(Tenant)
            .where(Tenant.id == UUID(project["tenant_id"]))
            .with_for_update(key_share=True)
        )
        blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        try:
            tasks = [
                asyncio.create_task(ask(client, actor, path, thread, project["head_revision_id"]))
                for actor, thread in writers
            ]
            async with asyncio.timeout(5):
                while True:
                    async with factory() as observer:
                        waiting = await observer.scalar(
                            text(
                                "WITH RECURSIVE waiting(pid) AS ("
                                "SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
                                "AND :blocker=ANY(pg_blocking_pids(pid)) UNION "
                                "SELECT a.pid FROM pg_stat_activity a JOIN waiting w "
                                "ON w.pid=ANY(pg_blocking_pids(a.pid)) "
                                "WHERE a.datname=current_database()) "
                                "SELECT count(DISTINCT pid) FROM waiting"
                            ),
                            {"blocker": blocker_pid},
                        )
                    if waiting == 2:
                        break
                    await asyncio.sleep(0.02)
        finally:
            await blocker.rollback()
            replies = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
    assert sorted(reply.status_code for reply in replies) == [202, 429]
    async with factory() as session:
        active = await session.scalars(
            select(NarrativeAssistantTurn.id).where(
                NarrativeAssistantTurn.tenant_id == UUID(project["tenant_id"])
            )
        )
        assert len(list(active)) == 1
