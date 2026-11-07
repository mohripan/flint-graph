"""The assistant really generates, once the creator presses Generate (ADR 0061, ADR 0068)."""

import json
from uuid import UUID, uuid4

import pytest
from test_narrative_assistant_api import ask, new_story, new_thread, turns, work
from test_narrative_characters_api import MemoryStore, queue_job, run_job

from flint_graph.api.dependencies import get_narrative_artifact_store
from flint_graph.application.services.audit import AuditActor
from flint_graph.application.services.narrative_assistant_actions import (
    dispatch_actions,
    queue_action,
    reconcile_actions,
    start_action,
)
from flint_graph.application.services.narrative_assistant_log import read_thread_log
from flint_graph.config import Settings, get_settings
from flint_graph.domain.errors import DomainError
from flint_graph.infrastructure.db.models import NarrativeImageJob
from flint_graph.main import app
from flint_graph.narrative.assistant.log import conversation_from_log, fold_thread

pytestmark = pytest.mark.anyio

BACKGROUND = {"op": "generate_backgrounds", "description": "rainy street at night"}


@pytest.fixture
def setup(narrative_env):
    settings = Settings(
        env="test", narrative_image_generation_enabled=True, narrative_voice_generation_enabled=True
    )
    store = MemoryStore()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_narrative_artifact_store] = lambda: store
    yield settings, store
    app.dependency_overrides.pop(get_settings, None)
    app.dependency_overrides.pop(get_narrative_artifact_store, None)


async def with_character(client, headers, path, project, character="mira", voice=None):
    """A saved story with a character and two lines she speaks, plus narration."""
    revision = (
        await client.get(f"{path}/revisions/{project['head_revision_id']}", headers=headers)
    ).json()
    story = json.loads(revision["story_json"])
    story["characters"][character] = {"name": character.capitalize()}
    story["nodes"]["hello"] = {
        "type": "line",
        "text_id": "hello_text",
        "speaker": character,
        "text": "Good   evening.",
        "next": "ending",
    }
    story["nodes"]["sound"] = {
        "type": "line",
        "text_id": "sound_text",
        "speaker": character,
        "text": "She laughs.",
        "voice": {"mode": "vocalization", "text": "fufu"},
        "next": "ending",
    }
    saved = await client.post(
        f"{path}/revisions",
        headers=headers,
        json={
            "base_revision_id": revision["id"],
            "idempotency_key": str(uuid4()),
            "story_json": json.dumps(story),
            "notices": "",
        },
    )
    assert saved.status_code == 201, saved.text
    if voice:
        chosen = await client.put(
            f"{path}/characters/{character}/voice",
            headers=headers,
            json={"base_version": 0, "voice": voice},
        )
        assert chosen.status_code == 200, chosen.text
    return saved.json()["id"]


async def propose(client, factory, headers, path, head, *operations, thread=None, **sent):
    thread = thread or await new_thread(client, headers, path)
    posted = await client.post(
        f"{path}/assistant/threads/{thread['id']}/turns",
        headers=headers,
        json={
            "request": "Do it.",
            "base_revision_id": head,
            "focus_node": None,
            "idempotency_key": str(uuid4()),
            **sent,
        },
    )
    assert posted.status_code == 202, posted.text
    await work(
        factory,
        posted.json()["id"],
        json.dumps(
            {
                "reply": "Here.",
                "proposal": {"summary": "Generate things", "operations": list(operations)},
            }
        ),
    )
    listed = await turns(client, headers, path, thread)
    return thread, listed[-1]["proposal"]["id"]


async def actions(client, headers, path, proposal):
    response = await client.get(f"{path}/assistant/proposals/{proposal}/actions", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def press(client, headers, path, proposal, index=0):
    return await client.post(
        f"{path}/assistant/proposals/{proposal}/actions/{index}", headers=headers
    )


async def cancel(client, headers, path, proposal, index=0):
    return await client.post(
        f"{path}/assistant/proposals/{proposal}/actions/{index}/decline", headers=headers
    )


async def queue(factory, headers, project, proposal, index=0):
    """What a press does when it finds the queue full."""
    async with factory() as session:
        await queue_action(
            session,
            tenant_id=UUID(headers["X-Tenant-ID"]),
            project_id=UUID(project["id"]),
            proposal_id=UUID(proposal),
            index=index,
        )
        await session.commit()


async def log_kinds(client, headers, path, thread):
    response = await client.get(f"{path}/assistant/threads/{thread['id']}/events", headers=headers)
    return [event["kind"] for event in response.json()]


async def test_nothing_runs_until_the_creator_presses_generate(narrative_env, setup):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    # A tab opened before ADR 0068 still sends the old setting; it no longer does anything.
    thread, proposal = await propose(
        client, factory, headers, path, project["head_revision_id"], BACKGROUND, auto_generate=True
    )
    [before] = await actions(client, headers, path, proposal)
    assert (before["status"], before["image_job"], before["needs_accept"]) == (
        "offered",
        None,
        False,
    )
    assert await dispatch_actions(factory, settings=settings, store=store) == 0
    jobs = await client.get(f"{path}/assets/background-jobs", headers=headers)
    assert jobs.json()["jobs"] == []

    first, second = [await press(client, headers, path, proposal) for _ in range(2)]
    assert first.status_code == second.status_code == 202, first.text
    assert first.json()["image_job"]["id"] == second.json()["image_job"]["id"]
    assert first.json()["status"] == "started"
    assert first.json()["quote"] is None, "the card has done its job"
    made = first.json()["image_job"]
    assert (made["purpose"], made["count"]) == ("background", 4)
    assert "action.started" in await log_kinds(client, headers, path, thread)
    assert await dispatch_actions(factory, settings=settings, store=store) == 0
    jobs = await client.get(f"{path}/assets/background-jobs", headers=headers)
    assert len(jobs.json()["jobs"]) == 1


async def test_cancel_stops_it_and_a_change_of_mind_still_works(narrative_env, setup):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    thread, proposal = await propose(
        client, factory, headers, path, project["head_revision_id"], BACKGROUND
    )
    cancelled = await cancel(client, headers, path, proposal)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "declined"
    assert cancelled.json()["quote"]["button"] == "Generate backgrounds"
    # Pressing it twice changes nothing, and nothing started.
    assert (await cancel(client, headers, path, proposal)).status_code == 200
    assert (await log_kinds(client, headers, path, thread)).count("action.declined") == 1
    assert await dispatch_actions(factory, settings=settings, store=store) == 0

    async with factory() as session:
        state = fold_thread(await read_thread_log(session, thread_id=UUID(thread["id"])))
    told = conversation_from_log(state, before_turn=2).recent[-1].content
    assert "cancelled this" in told

    changed = await press(client, headers, path, proposal)
    assert changed.status_code == 202, changed.text
    assert changed.json()["status"] == "started"
    # Once it is running, Cancel on a card cannot pretend it did not start.
    assert (await cancel(client, headers, path, proposal)).status_code == 409


async def test_a_cancel_beats_the_dispatcher_however_they_race(narrative_env, setup):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    _, proposal = await propose(
        client, factory, headers, path, project["head_revision_id"], BACKGROUND
    )
    await queue(factory, headers, project, proposal)
    assert (await cancel(client, headers, path, proposal)).status_code == 200
    assert await dispatch_actions(factory, settings=settings, store=store) == 0
    # The dispatcher read its queue just before the cancel landed.
    async with factory() as session:
        await start_action(
            session,
            tenant_id=UUID(headers["X-Tenant-ID"]),
            project_id=UUID(project["id"]),
            proposal_id=UUID(proposal),
            index=0,
            author_user_id=uuid4(),
            actor=AuditActor(user_id=None),
            settings=settings,
            store=store,
            queued=True,
        )
        await session.commit()
    [still] = await actions(client, headers, path, proposal)
    assert (still["status"], still["image_job"]) == ("declined", None)


async def test_an_action_on_a_new_character_waits_for_accept(narrative_env, setup):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    character = {"op": "upsert_character", "id": "ren", "name": "Ren"}
    sprite = {
        "op": "generate_character_images",
        "character": "ren",
        "appearance": "white hair, blue coat",
        "character_type": "boy",
        "framing": "full_body",
        "transparent": True,
    }
    _, proposal = await propose(
        client, factory, headers, path, project["head_revision_id"], character, sprite
    )
    [waiting] = await actions(client, headers, path, proposal)
    assert (waiting["index"], waiting["status"], waiting["needs_accept"]) == (1, "offered", True)
    assert waiting["quote"]["kind"] == "Sprite of Ren", "the name comes from the proposal"
    assert await dispatch_actions(factory, settings=settings, store=store) == 0
    assert (await press(client, headers, path, proposal, 1)).status_code == 409

    accepted = await client.post(
        f"{path}/assistant/proposals/{proposal}/accept",
        headers=headers,
        json={"idempotency_key": str(uuid4())},
    )
    assert accepted.status_code == 201, accepted.text
    [released] = await actions(client, headers, path, proposal)
    assert (released["status"], released["needs_accept"]) == ("offered", False)
    assert released["quote"] is not None, "it still asks after the proposal is accepted"
    assert await dispatch_actions(factory, settings=settings, store=store) == 0
    started = (await press(client, headers, path, proposal, 1)).json()
    job = started["image_job"]
    assert (job["character_id"], job["transparent"]) == ("ren", True)
    assert job["hires"] is not None, "assistant sprites stay high resolution"


async def test_rejecting_a_proposal_skips_what_has_not_started(narrative_env, setup):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    _, proposal = await propose(
        client, factory, headers, path, project["head_revision_id"], BACKGROUND
    )
    rejected = await client.post(f"{path}/assistant/proposals/{proposal}/reject", headers=headers)
    assert rejected.status_code == 200
    [skipped] = await actions(client, headers, path, proposal)
    assert skipped["status"] == "skipped"
    assert await dispatch_actions(factory, settings=settings, store=store) == 0
    url = f"{path}/assistant/proposals/{proposal}/actions/0"
    assert (await client.post(url, headers=headers)).status_code == 409
    assert (await press(client, headers, path, proposal)).status_code == 409


async def test_a_full_queue_waits_instead_of_failing(narrative_env, setup):
    client, factory, _ = narrative_env
    settings, store = setup
    busy = settings.model_copy(update={"narrative_image_max_active_jobs_per_workspace": 1})
    app.dependency_overrides[get_settings] = lambda: busy
    headers, project, path = await new_story(client)
    _, proposal = await propose(
        client, factory, headers, path, project["head_revision_id"], BACKGROUND, BACKGROUND
    )
    assert (await press(client, headers, path, proposal, 0)).status_code == 202
    assert (await press(client, headers, path, proposal, 1)).status_code == 202
    assert await dispatch_actions(factory, settings=busy, store=store) == 0
    first, second = await actions(client, headers, path, proposal)
    assert (first["status"], second["status"]) == ("started", "pending")
    # The queue clears; the waiting action starts on its own.
    async with factory() as session:
        job = await session.get(NarrativeImageJob, UUID(first["image_job"]["id"]))
        job.status = "cancelled"
        await session.commit()
    assert await dispatch_actions(factory, settings=busy, store=store) == 1
    _, second = await actions(client, headers, path, proposal)
    assert second["status"] == "started"


async def test_a_finished_job_is_logged_once_and_the_model_hears_about_it(narrative_env, setup):
    client, factory, _ = narrative_env
    _, store = setup
    headers, project, path = await new_story(client)
    head = project["head_revision_id"]
    thread, proposal = await propose(client, factory, headers, path, head, BACKGROUND)
    await press(client, headers, path, proposal)
    [started] = await actions(client, headers, path, proposal)
    job_id = started["image_job"]["id"]
    from flint_graph.application.narrative_image_workflow import ImageJobPayload

    payload = ImageJobPayload(schema_version="1", tenant_id=headers["X-Tenant-ID"], job_id=job_id)
    assert (await run_job(factory, store, payload))["status"] == "completed"

    assert await reconcile_actions(factory) == 1
    assert await reconcile_actions(factory) == 0
    [done] = await actions(client, headers, path, proposal)
    assert done["status"] == "finished"
    assert len(done["image_job"]["assets"]) == 4
    kinds = await log_kinds(client, headers, path, thread)
    assert kinds.count("job.finished") == 1

    chosen = done["image_job"]["assets"][1]
    approved = await client.post(f"{path}/assets/{chosen['id']}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    # Approving again is not a second event.
    await client.post(f"{path}/assets/{chosen['id']}/approve", headers=headers)
    kinds = await log_kinds(client, headers, path, thread)
    assert kinds.count("asset.approved") == 1

    async with factory() as session:
        state = fold_thread(await read_thread_log(session, thread_id=UUID(thread["id"])))
    told = conversation_from_log(state, before_turn=2).recent[-1].content
    assert "4 candidates" in told and chosen["name"] in told and "approved" in told


async def test_expressions_need_an_approved_picture_and_say_so(narrative_env, setup):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    head = await with_character(client, headers, path, project)
    thread, proposal = await propose(
        client,
        factory,
        headers,
        path,
        head,
        {"op": "generate_expressions", "character": "mira", "expressions": ["happy", "angry"]},
    )
    # Pressed too early, it says why and the card stays.
    early = await press(client, headers, path, proposal)
    assert early.status_code == 409
    assert "Approve a picture of Mira" in early.json()["detail"]
    [still] = await actions(client, headers, path, proposal)
    assert still["status"] == "offered"
    # Started later by the dispatcher, the reason stays on the card instead.
    await queue(factory, headers, project, proposal)
    assert await dispatch_actions(factory, settings=settings, store=store) == 0
    [blocked] = await actions(client, headers, path, proposal)
    assert blocked["status"] == "blocked"
    assert blocked["error_code"] == "needs-approved-picture"
    assert "Approve a picture of Mira" in blocked["detail"]
    assert blocked["quote"] is not None
    assert "action.blocked" in await log_kinds(client, headers, path, thread)
    # The blocked action does not retry on its own and burn work every second.
    assert await dispatch_actions(factory, settings=settings, store=store) == 0

    job, payload = await queue_job(client, headers, path, character="mira", count=1)
    assert (await run_job(factory, store, payload))["status"] == "completed"
    [picture] = (await client.get(f"{path}/image-jobs/{job['id']}", headers=headers)).json()[
        "assets"
    ]
    await client.post(f"{path}/assets/{picture['id']}/approve", headers=headers)

    retried = await client.post(f"{path}/assistant/proposals/{proposal}/actions/0", headers=headers)
    assert retried.status_code == 202, retried.text
    started = retried.json()
    assert started["status"] == "started"
    made = started["image_job"]
    assert (made["purpose"], made["base_asset_id"]) == ("character_expression", picture["id"])
    assert made["expressions"] == ["happy", "angry"]
    left, top, right, bottom = made["face_box"]
    assert 0 <= left < right <= picture["width"] and 0 <= top < bottom <= picture["height"]


async def test_a_cg_is_drawn_from_each_characters_approved_picture(narrative_env, setup):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    head = await with_character(client, headers, path, project)
    job, payload = await queue_job(client, headers, path, character="mira", count=1)
    await run_job(factory, store, payload)
    [picture] = (await client.get(f"{path}/image-jobs/{job['id']}", headers=headers)).json()[
        "assets"
    ]
    await client.post(f"{path}/assets/{picture['id']}/approve", headers=headers)
    _, proposal = await propose(
        client,
        factory,
        headers,
        path,
        head,
        {"op": "generate_cg", "characters": ["mira"], "description": "Mira rings the harbor bell"},
    )
    assert await dispatch_actions(factory, settings=settings, store=store) == 0
    started = (await press(client, headers, path, proposal)).json()
    made = started["image_job"]
    assert made["purpose"] == "scene_art"
    assert made["reference_assets"] == [{"character_id": "mira", "asset_id": picture["id"]}]
    assert made["appearance"] == "Mira rings the harbor bell"


async def test_a_voice_action_speaks_the_saved_lines_and_gives_a_silent_character_a_voice(
    narrative_env, setup
):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    head = await with_character(client, headers, path, project)
    _, proposal = await propose(
        client,
        factory,
        headers,
        path,
        head,
        {
            "op": "generate_voice",
            "character": "mira",
            "lines": ["hello", "sound"],
            "voice": "af_bella",
        },
    )
    assert await dispatch_actions(factory, settings=settings, store=store) == 0
    started = (await press(client, headers, path, proposal)).json()
    job = started["voice_job"]
    assert (job["character_id"], job["voice"], job["voice_model"]) == (
        "mira",
        "af_bella",
        "kokoro-82m",
    )
    assert [(i["node_id"], i["mode"], i["text"]) for i in job["items"]] == [
        ("hello", "full", "Good evening."),
        ("sound", "vocalization", "fufu"),
    ]
    profile = next(
        row
        for row in (await client.get(f"{path}/characters", headers=headers)).json()["profiles"]
        if row["character_id"] == "mira"
    )
    assert profile["voice"] == "af_bella"


async def test_a_voice_the_creator_chose_is_kept_and_a_made_up_one_is_ignored(narrative_env, setup):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    head = await with_character(client, headers, path, project, voice="bf_emma")
    action = {"op": "generate_voice", "character": "mira", "lines": ["hello"], "voice": "af_bella"}
    _, proposal = await propose(client, factory, headers, path, head, action)
    await press(client, headers, path, proposal)
    [kept] = await actions(client, headers, path, proposal)
    assert kept["voice_job"]["voice"] == "bf_emma"

    other_headers, other_project, other_path = await new_story(client, name="Other story")
    other_head = await with_character(client, other_headers, other_path, other_project)
    invented = {**action, "voice": "not_a_voice"}
    _, second = await propose(client, factory, other_headers, other_path, other_head, invented)
    await press(client, other_headers, other_path, second)
    [fallback] = await actions(client, other_headers, other_path, second)
    assert fallback["status"] == "started"
    assert fallback["voice_job"]["voice"] == "af_heart"


async def test_generation_that_is_off_on_this_server_blocks_with_a_reason(narrative_env, setup):
    client, factory, _ = narrative_env
    settings, store = setup
    off = settings.model_copy(update={"narrative_image_generation_enabled": False})
    headers, project, path = await new_story(client)
    _, proposal = await propose(
        client, factory, headers, path, project["head_revision_id"], BACKGROUND
    )
    await queue(factory, headers, project, proposal)
    assert await dispatch_actions(factory, settings=off, store=store) == 0
    [blocked] = await actions(client, headers, path, proposal)
    assert blocked["status"] == "blocked"
    assert blocked["error_code"] == "image-generation-unavailable"
    assert "not configured" in blocked["detail"]


async def test_running_out_of_credits_blocks_and_leaves_no_job(narrative_env, setup, monkeypatch):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    _, proposal = await propose(
        client, factory, headers, path, project["head_revision_id"], BACKGROUND
    )

    async def broke(*args, **kwargs):
        raise DomainError(402, "Out of credits", "You have run out of credits.", "out-of-credits")

    monkeypatch.setattr("flint_graph.application.services.narrative_images.charge_usage", broke)
    pressed = await press(client, headers, path, proposal)
    assert pressed.status_code == 402
    [still] = await actions(client, headers, path, proposal)
    assert (still["status"], still["image_job"]) == ("offered", None)
    await queue(factory, headers, project, proposal)
    assert await dispatch_actions(factory, settings=settings, store=store) == 0
    [blocked] = await actions(client, headers, path, proposal)
    assert (blocked["status"], blocked["error_code"]) == ("blocked", "out-of-credits")
    jobs = await client.get(f"{path}/assets/background-jobs", headers=headers)
    assert jobs.json()["jobs"] == []


async def test_actions_are_project_scoped(narrative_env, setup):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    _, proposal = await propose(
        client, factory, headers, path, project["head_revision_id"], BACKGROUND
    )
    other_headers, _, other = await new_story(client, name="Other story")
    foreign = f"{other}/assistant/proposals/{proposal}/actions"
    assert (await client.get(foreign, headers=other_headers)).status_code == 404
    assert (await client.post(f"{foreign}/0", headers=other_headers)).status_code == 404
    missing = f"{path}/assistant/proposals/{proposal}/actions/9"
    assert (await client.post(missing, headers=headers)).status_code == 404


async def test_a_reply_without_actions_creates_nothing_to_run(narrative_env, setup):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    turn = (await ask(client, headers, path, thread, project["head_revision_id"])).json()
    await work(factory, turn["id"], json.dumps({"reply": "Hello.", "proposal": None}))
    assert await dispatch_actions(factory, settings=settings, store=store) == 0
    assert await reconcile_actions(factory) == 0
