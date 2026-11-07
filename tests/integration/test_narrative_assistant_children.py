"""Child sessions: a tree of conversations that know about each other (ADR 0063)."""

import json
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from test_narrative_assistant_actions import actions, propose, setup  # noqa: F401
from test_narrative_assistant_api import new_story, new_thread, turns, work

from flint_graph.application.services.narrative_assistant_actions import (
    dispatch_actions,
    reconcile_actions,
)
from flint_graph.infrastructure.db.narrative_assistant_models import NarrativeAssistantThread

pytestmark = pytest.mark.anyio

SILENT = json.dumps({"reply": "Done.", "proposal": None})
CHILD = {"op": "start_child_session", "title": "Create the cast", "task": "Add three characters."}


async def child_of(client, headers, path, parent, title="Side quest", task="Write a side quest."):
    response = await client.post(
        f"{path}/assistant/threads",
        headers=headers,
        json={
            "title": title,
            "idempotency_key": str(uuid4()),
            "parent_thread_id": parent["id"],
            "task": task,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def listed(client, headers, path):
    response = await client.get(f"{path}/assistant/threads", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def events(client, headers, path, thread):
    response = await client.get(f"{path}/assistant/threads/{thread['id']}/events", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def ask_in(client, headers, path, thread, head, request="Go on."):
    response = await client.post(
        f"{path}/assistant/threads/{thread['id']}/turns",
        headers=headers,
        json={
            "request": request,
            "base_revision_id": head,
            "focus_node": None,
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


async def test_a_child_session_sits_under_its_parent(narrative_env, setup):  # noqa: F811
    client, _, _ = narrative_env
    headers, _, path = await new_story(client)
    parent = await new_thread(client, headers, path)
    child = await child_of(client, headers, path, parent)
    assert child["parent_thread_id"] == parent["id"]
    assert (child["task"], child["origin"]) == ("Write a side quest.", "creator")

    roots = await listed(client, headers, path)
    assert [row["id"] for row in roots] == [parent["id"]], "children are not listed as roots"
    assert [row["id"] for row in roots[0]["children"]] == [child["id"]]
    assert roots[0]["parent_thread_id"] is None

    # A link straight to a child still opens it, and says where it belongs.
    direct = await client.get(f"{path}/assistant/threads/{child['id']}", headers=headers)
    assert direct.status_code == 200
    assert direct.json()["parent_thread_id"] == parent["id"]


async def test_children_are_listed_oldest_first(narrative_env, setup):  # noqa: F811
    client, factory, _ = narrative_env
    headers, _, path = await new_story(client)
    parent = await new_thread(client, headers, path)
    first = await child_of(client, headers, path, parent, title="First")
    second = await child_of(client, headers, path, parent, title="Second")
    async with factory() as session:  # SQLite timestamps have no sub-second part.
        row = await session.get(NarrativeAssistantThread, UUID(first["id"]))
        row.created_at -= timedelta(minutes=1)
        await session.commit()
    [root] = await listed(client, headers, path)
    assert [row["id"] for row in root["children"]] == [first["id"], second["id"]]


async def test_only_one_level_of_nesting(narrative_env, setup):  # noqa: F811
    client, _, _ = narrative_env
    headers, _, path = await new_story(client)
    parent = await new_thread(client, headers, path)
    child = await child_of(client, headers, path, parent)
    deeper = await client.post(
        f"{path}/assistant/threads",
        headers=headers,
        json={
            "title": "Too deep",
            "idempotency_key": str(uuid4()),
            "parent_thread_id": child["id"],
        },
    )
    assert deeper.status_code == 409


async def test_a_parent_must_be_in_this_project(narrative_env, setup):  # noqa: F811
    client, _, _ = narrative_env
    headers, _, path = await new_story(client)
    other_headers, _, other = await new_story(client, name="Other story")
    foreign = await new_thread(client, other_headers, other)
    stolen = await client.post(
        f"{path}/assistant/threads",
        headers=headers,
        json={"title": "Mine", "idempotency_key": str(uuid4()), "parent_thread_id": foreign["id"]},
    )
    assert stolen.status_code == 404


async def test_replaying_a_creation_key_returns_the_same_child(narrative_env, setup):  # noqa: F811
    client, _, _ = narrative_env
    headers, _, path = await new_story(client)
    parent = await new_thread(client, headers, path)
    body = {
        "title": "Side quest",
        "idempotency_key": str(uuid4()),
        "parent_thread_id": parent["id"],
    }
    first = await client.post(f"{path}/assistant/threads", headers=headers, json=body)
    again = await client.post(f"{path}/assistant/threads", headers=headers, json=body)
    assert first.json()["id"] == again.json()["id"]
    kinds = [event["kind"] for event in await events(client, headers, path, parent)]
    assert kinds.count("child.started") == 1


async def test_a_child_is_told_its_task_and_what_its_parent_has_done(
    narrative_env,
    setup,  # noqa: F811
):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    head = project["head_revision_id"]
    parent = await new_thread(client, headers, path)
    first = await ask_in(client, headers, path, parent, head, request="Plan the first chapter.")
    await work(factory, first["id"], SILENT)

    child = await child_of(client, headers, path, parent, title="Chapter two")
    turn = await ask_in(client, headers, path, child, head)
    claimed = await work(factory, turn["id"], SILENT)
    assert claimed.child_session is True
    lines = "\n".join(claimed.earlier)
    assert 'child session of "Storm ideas"' in lines
    assert "Write a side quest." in lines
    assert "Plan the first chapter." in lines


async def test_a_parent_hears_what_its_children_did(narrative_env, setup):  # noqa: F811
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    head = project["head_revision_id"]
    parent = await new_thread(client, headers, path)
    child = await child_of(client, headers, path, parent, title="Chapter two")
    turn = await ask_in(client, headers, path, child, head)
    await work(factory, turn["id"], SILENT)

    log = await events(client, headers, path, parent)
    kinds = [event["kind"] for event in log]
    assert kinds == ["thread.created", "child.started", "child.updated"]
    assert log[-1]["payload"]["child_thread_id"] == child["id"]
    assert log[-1]["payload"]["what"] == "replied"

    next_turn = await ask_in(client, headers, path, parent, head)
    claimed = await work(factory, next_turn["id"], SILENT)
    lines = "\n".join(claimed.earlier)
    assert 'Child session "Chapter two"' in lines and "replied" in lines


async def test_accepting_in_a_child_reaches_the_parents_log(narrative_env, setup):  # noqa: F811
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    head = project["head_revision_id"]
    parent = await new_thread(client, headers, path)
    child = await child_of(client, headers, path, parent, title="Chapter two")
    _, proposal = await propose(
        client,
        factory,
        headers,
        path,
        head,
        {"op": "upsert_character", "id": "ren", "name": "Ren"},
        thread=child,
    )
    accepted = await client.post(
        f"{path}/assistant/proposals/{proposal}/accept",
        headers=headers,
        json={"idempotency_key": str(uuid4())},
    )
    assert accepted.status_code == 201
    last = (await events(client, headers, path, parent))[-1]
    assert (last["kind"], last["payload"]["what"]) == ("child.updated", "accepted")
    assert last["payload"]["summary"] == "Generate things"


async def test_the_assistant_can_start_a_child_session_that_runs_by_itself(
    narrative_env,
    setup,  # noqa: F811
):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    thread, proposal = await propose(
        client, factory, headers, path, project["head_revision_id"], CHILD
    )
    # It waits for the creator, like everything else that spends credits.
    assert await dispatch_actions(factory, settings=settings, store=store) == 0
    url = f"{path}/assistant/proposals/{proposal}/actions/0"
    pressed = [await client.post(url, headers=headers) for _ in range(2)]
    assert pressed[0].json()["child_thread"]["id"] == pressed[1].json()["child_thread"]["id"]

    [root] = await listed(client, headers, path)
    [child] = root["children"]
    assert (child["title"], child["task"], child["origin"]) == (
        "Create the cast",
        "Add three characters.",
        "assistant",
    )
    [action] = await actions(client, headers, path, proposal)
    assert action["status"] == "started"
    assert action["child_thread"]["id"] == child["id"]

    [first] = await turns(client, headers, path, child)
    assert first["request"] == "Add three characters."
    assert first["auto_generate"] is False, "what it suggests waits for a press too"
    assert first["status"] == "queued"

    await work(factory, first["id"], SILENT)
    assert await reconcile_actions(factory) == 1
    [done] = await actions(client, headers, path, proposal)
    assert done["status"] == "finished"
    assert "child.started" in [e["kind"] for e in await events(client, headers, path, thread)]


async def test_a_busy_assistant_makes_child_sessions_wait_their_turn(
    narrative_env,
    setup,  # noqa: F811
):
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    other = {"op": "start_child_session", "title": "Write the map", "task": "Draw routes."}
    _, proposal = await propose(
        client, factory, headers, path, project["head_revision_id"], CHILD, other
    )
    # One active reply at a time: the first child's turn fills the only slot.
    for index in (0, 1):
        url = f"{path}/assistant/proposals/{proposal}/actions/{index}"
        assert (await client.post(url, headers=headers)).status_code == 202
    first, second = await actions(client, headers, path, proposal)
    assert (first["status"], second["status"]) == ("started", "pending")
    [child] = (await listed(client, headers, path))[0]["children"]
    [turn] = await turns(client, headers, path, child)
    await work(factory, turn["id"], SILENT)
    assert await dispatch_actions(factory, settings=settings, store=store) == 1
    _, second = await actions(client, headers, path, proposal)
    assert second["status"] == "started"


async def test_a_child_session_alongside_story_edits_waits_for_accept(
    narrative_env,
    setup,  # noqa: F811
):
    """It works from the saved story, which must have what the proposal adds."""
    client, factory, _ = narrative_env
    settings, store = setup
    headers, project, path = await new_story(client)
    _, proposal = await propose(
        client,
        factory,
        headers,
        path,
        project["head_revision_id"],
        {"op": "upsert_character", "id": "ren", "name": "Ren"},
        CHILD,
    )
    [waiting] = await actions(client, headers, path, proposal)
    assert (waiting["status"], waiting["needs_accept"]) == ("offered", True)
    url = f"{path}/assistant/proposals/{proposal}/actions/1"
    assert (await client.post(url, headers=headers)).status_code == 409
    await client.post(
        f"{path}/assistant/proposals/{proposal}/accept",
        headers=headers,
        json={"idempotency_key": str(uuid4())},
    )
    assert await dispatch_actions(factory, settings=settings, store=store) == 0
    assert (await client.post(url, headers=headers)).json()["status"] == "started"


async def test_a_thread_says_when_it_is_working(narrative_env, setup):  # noqa: F811
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    head = project["head_revision_id"]
    parent = await new_thread(client, headers, path)
    child = await child_of(client, headers, path, parent)
    turn = await ask_in(client, headers, path, child, head)
    [root] = await listed(client, headers, path)
    assert root["active"] is False and root["children"][0]["active"] is True
    await work(factory, turn["id"], SILENT)
    [root] = await listed(client, headers, path)
    assert root["children"][0]["active"] is False


async def test_a_conversation_without_children_is_unchanged(narrative_env, setup):  # noqa: F811
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    turn = await ask_in(client, headers, path, thread, project["head_revision_id"])
    claimed = await work(factory, turn["id"], SILENT)
    assert claimed.earlier == ()
    [root] = await listed(client, headers, path)
    assert root["children"] == []
    assert UUID(root["id"])
