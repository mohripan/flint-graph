"""The creator attaches library items to a message, and the model is told about them (ADR 0062)."""

import json
from uuid import UUID, uuid4

import pytest
from test_narrative_assistant_actions import setup, with_character  # noqa: F401
from test_narrative_assistant_api import new_story, new_thread, work
from test_narrative_characters_api import queue_job, run_job

from flint_graph.application.services.narrative_assistant_log import read_thread_log
from flint_graph.narrative.assistant.log import conversation_from_log, fold_thread

pytestmark = pytest.mark.anyio

SILENT = json.dumps({"reply": "Sure.", "proposal": None})


async def post(client, headers, path, thread, base, attachments, *, request="Use these.", key=None):
    return await client.post(
        f"{path}/assistant/threads/{thread['id']}/turns",
        headers=headers,
        json={
            "request": request,
            "base_revision_id": base,
            "focus_node": None,
            "idempotency_key": key or str(uuid4()),
            "attachments": attachments,
        },
    )


async def picture(client, factory, store, headers, path, character="mira", approve=True):
    job, payload = await queue_job(client, headers, path, character=character, count=1)
    assert (await run_job(factory, store, payload))["status"] == "completed"
    response = await client.get(f"{path}/image-jobs/{job['id']}", headers=headers)
    [asset] = response.json()["assets"]
    if approve:
        approved = await client.post(f"{path}/assets/{asset['id']}/approve", headers=headers)
        assert approved.status_code == 200, approved.text
    return asset


async def test_an_attached_character_and_picture_reach_the_model_with_their_details(
    narrative_env,
    setup,  # noqa: F811
):
    client, factory, _ = narrative_env
    _, store = setup
    headers, project, path = await new_story(client)
    head = await with_character(client, headers, path, project, voice="af_bella")
    asset = await picture(client, factory, store, headers, path)
    thread = await new_thread(client, headers, path)

    sent = await post(
        client,
        headers,
        path,
        thread,
        head,
        [{"kind": "character", "id": "mira"}, {"kind": "asset", "id": asset["id"]}],
    )
    assert sent.status_code == 202, sent.text
    # What was attached is frozen on the turn, with names, so the chat can show it.
    assert sent.json()["attachments"] == [
        {"kind": "character", "id": "mira", "name": "Mira", "asset_kind": None},
        {"kind": "asset", "id": asset["id"], "name": asset["name"], "asset_kind": asset["kind"]},
    ]

    claimed = await work(factory, sent.json()["id"], SILENT)
    joined = "\n".join(claimed.attached)
    assert 'character mira: "Mira"' in joined and "voice af_bella" in joined
    assert asset["name"] in joined and asset["kind"] in joined


async def test_an_attached_file_outside_the_usual_library_window_is_still_offered(
    narrative_env,
    setup,  # noqa: F811
):
    client, factory, _ = narrative_env
    _, store = setup
    headers, project, path = await new_story(client)
    head = await with_character(client, headers, path, project)
    asset = await picture(client, factory, store, headers, path)
    thread = await new_thread(client, headers, path)
    sent = await post(client, headers, path, thread, head, [{"kind": "asset", "id": asset["id"]}])
    claimed = await work(factory, sent.json()["id"], SILENT)
    assert claimed.library[0].sha256 == asset["sha256"], "attached files come first"


async def test_attaching_what_does_not_exist_or_is_not_approved_is_refused(
    narrative_env,
    setup,  # noqa: F811
):
    client, factory, _ = narrative_env
    _, store = setup
    headers, project, path = await new_story(client)
    head = await with_character(client, headers, path, project)
    thread = await new_thread(client, headers, path)

    unknown = await post(client, headers, path, thread, head, [{"kind": "character", "id": "nope"}])
    assert unknown.status_code == 422
    assert "nope" in unknown.json()["detail"]

    missing = await post(
        client, headers, path, thread, head, [{"kind": "asset", "id": str(uuid4())}]
    )
    assert missing.status_code == 422

    malformed = await post(client, headers, path, thread, head, [{"kind": "asset", "id": "x"}])
    assert malformed.status_code == 422

    candidate = await picture(client, factory, store, headers, path, approve=False)
    waiting = await post(
        client, headers, path, thread, head, [{"kind": "asset", "id": candidate["id"]}]
    )
    assert waiting.status_code == 422
    assert "Approve" in waiting.json()["detail"]

    # A refused message charges nothing and writes nothing.
    response = await client.get(f"{path}/assistant/threads/{thread['id']}/turns", headers=headers)
    assert response.json() == []


async def test_another_projects_file_cannot_be_attached(narrative_env, setup):  # noqa: F811
    client, factory, _ = narrative_env
    _, store = setup
    headers, project, path = await new_story(client)
    await with_character(client, headers, path, project)
    asset = await picture(client, factory, store, headers, path)
    other_headers, other_project, other = await new_story(client, name="Other story")
    other_thread = await new_thread(client, other_headers, other)
    stolen = await post(
        client,
        other_headers,
        other,
        other_thread,
        other_project["head_revision_id"],
        [{"kind": "asset", "id": asset["id"]}],
    )
    assert stolen.status_code == 422


async def test_there_is_a_limit_on_attachments_and_duplicates_collapse(
    narrative_env,
    setup,  # noqa: F811
):
    client, _, _ = narrative_env
    headers, project, path = await new_story(client)
    head = await with_character(client, headers, path, project)
    thread = await new_thread(client, headers, path)
    many = await post(
        client, headers, path, thread, head, [{"kind": "character", "id": "mira"}] * 13
    )
    assert many.status_code == 422
    twice = await post(
        client, headers, path, thread, head, [{"kind": "character", "id": "mira"}] * 2
    )
    assert twice.status_code == 202, twice.text
    assert len(twice.json()["attachments"]) == 1


async def test_a_replayed_message_keeps_its_key_only_for_the_same_attachments(
    narrative_env,
    setup,  # noqa: F811
):
    client, _, _ = narrative_env
    headers, project, path = await new_story(client)
    head = await with_character(client, headers, path, project)
    thread = await new_thread(client, headers, path)
    key = str(uuid4())
    character = [{"kind": "character", "id": "mira"}]
    first = await post(client, headers, path, thread, head, character, key=key)
    again = await post(client, headers, path, thread, head, character, key=key)
    assert first.status_code == again.status_code == 202
    assert first.json()["id"] == again.json()["id"]
    changed = await post(client, headers, path, thread, head, [], key=key)
    assert changed.status_code == 409


async def test_later_turns_remember_what_was_attached(narrative_env, setup):  # noqa: F811
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    head = await with_character(client, headers, path, project)
    thread = await new_thread(client, headers, path)
    sent = await post(
        client,
        headers,
        path,
        thread,
        head,
        [{"kind": "character", "id": "mira"}],
        request="Write her a scene.",
    )
    await work(factory, sent.json()["id"], SILENT)
    async with factory() as session:
        state = fold_thread(await read_thread_log(session, thread_id=UUID(thread["id"])))
    [asked, _answer] = conversation_from_log(state, before_turn=2).recent
    assert asked.content.startswith("Write her a scene.")
    assert "Attached: Mira" in asked.content


async def test_a_message_with_nothing_attached_is_unchanged(narrative_env, setup):  # noqa: F811
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    head = await with_character(client, headers, path, project)
    thread = await new_thread(client, headers, path)
    sent = await post(client, headers, path, thread, head, [])
    assert sent.status_code == 202 and sent.json()["attachments"] == []
    claimed = await work(factory, sent.json()["id"], SILENT)
    assert claimed.attached == ()
