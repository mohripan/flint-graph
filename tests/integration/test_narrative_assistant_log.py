"""The thread log is written in the same transaction as what it records (ADR 0060)."""

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_narrative_assistant_api import (
    ask,
    claim,
    new_story,
    new_thread,
    proposal,
    turns,
    work,
)

from flint_graph.application.services.narrative_assistant import fail_turn
from flint_graph.application.services.narrative_assistant_log import read_thread_log
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.db.models import NarrativeAssistantThread, NarrativeAssistantTurn
from flint_graph.infrastructure.db.narrative_assistant_models import (
    NarrativeAssistantThreadEvent,
)
from flint_graph.main import app
from flint_graph.narrative.assistant.log import fold_thread


@pytest.fixture
def assistant_settings(narrative_env):
    settings = Settings(env="test")
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


async def log_of(client, headers, path, thread, after=0):
    response = await client.get(
        f"{path}/assistant/threads/{thread['id']}/events",
        headers=headers,
        params={"after_sequence": after},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def state_of(factory, thread):
    async with factory() as session:
        return fold_thread(await read_thread_log(session, thread_id=UUID(thread["id"])))


@pytest.mark.anyio
async def test_each_step_of_a_conversation_lands_in_the_log(narrative_env, assistant_settings):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    queued = (await ask(client, headers, path, thread, project["head_revision_id"])).json()
    await work(factory, queued["id"], proposal())
    listed = await turns(client, headers, path, thread)
    proposal_id = listed[0]["proposal"]["id"]
    accepted = await client.post(
        f"{path}/assistant/proposals/{proposal_id}/accept",
        headers=headers,
        json={"idempotency_key": str(uuid4())},
    )
    assert accepted.status_code == 201

    events = await log_of(client, headers, path, thread)
    assert [event["kind"] for event in events] == [
        "thread.created",
        "turn.requested",
        "turn.completed",
        "proposal.created",
        "proposal.accepted",
    ]
    assert [event["sequence"] for event in events] == [1, 2, 3, 4, 5]
    assert events[1]["payload"]["request"] == "Add a storm."
    assert events[2]["payload"]["reply"].startswith("Here is a storm")
    assert events[4]["payload"]["revision_id"] == accepted.json()["id"]
    # Paging resumes from a cursor.
    assert [e["sequence"] for e in await log_of(client, headers, path, thread, after=3)] == [4, 5]


@pytest.mark.anyio
async def test_folding_the_log_agrees_with_the_rows(narrative_env, assistant_settings):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    head = project["head_revision_id"]

    first = (await ask(client, headers, path, thread, head, request="One")).json()
    await work(factory, first["id"], proposal())
    rejected_id = (await turns(client, headers, path, thread))[0]["proposal"]["id"]
    assert (
        await client.post(f"{path}/assistant/proposals/{rejected_id}/reject", headers=headers)
    ).status_code == 200

    second = (await ask(client, headers, path, thread, head, request="Two")).json()
    token = uuid4()
    await claim(factory, second["id"], token)
    async with factory() as session:
        await fail_turn(
            session,
            turn_id=UUID(second["id"]),
            execution_token=token,
            error_code="provider_timeout",
        )
        await session.commit()

    third = (await ask(client, headers, path, thread, head, request="Three")).json()
    assert (
        await client.post(
            f"{path}/assistant/threads/{thread['id']}/turns/{third['id']}/cancel", headers=headers
        )
    ).status_code == 200

    state = await state_of(factory, thread)
    rows = await turns(client, headers, path, thread)
    assert [turn.turn_id for turn in state.turns] == [row["id"] for row in rows]
    for folded, row in zip(state.turns, rows, strict=True):
        assert folded.request == row["request"]
        assert folded.status == row["status"]
        assert folded.reply == row["reply"]
        assert folded.error_code == row["error_code"]
        assert (folded.proposal.status if folded.proposal else None) == (
            row["proposal"]["status"] if row["proposal"] else None
        )


@pytest.mark.anyio
async def test_the_next_turn_hears_how_the_last_one_ended(narrative_env, assistant_settings):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    head = project["head_revision_id"]
    first = (await ask(client, headers, path, thread, head, request="Add a storm.")).json()
    await work(factory, first["id"], proposal())
    proposal_id = (await turns(client, headers, path, thread))[0]["proposal"]["id"]
    await client.post(f"{path}/assistant/proposals/{proposal_id}/reject", headers=headers)

    second = (await ask(client, headers, path, thread, head, request="Try something else.")).json()
    claimed = await work(factory, second["id"], json.dumps({"reply": "Sure.", "proposal": None}))
    assert [turn.role for turn in claimed.history] == ["user", "assistant"]
    assert claimed.history[0].content == "Add a storm."
    assert "rejected" in claimed.history[1].content
    assert "Add a storm scene" in claimed.history[1].content


@pytest.mark.anyio
async def test_replaying_idempotent_requests_does_not_duplicate_events(
    narrative_env, assistant_settings
):
    client, _, _ = narrative_env
    headers, project, path = await new_story(client)
    request = {"title": "Storm ideas", "idempotency_key": str(uuid4())}
    thread = (await client.post(f"{path}/assistant/threads", headers=headers, json=request)).json()
    await client.post(f"{path}/assistant/threads", headers=headers, json=request)
    key = str(uuid4())
    await ask(client, headers, path, thread, project["head_revision_id"], key=key)
    await ask(client, headers, path, thread, project["head_revision_id"], key=key)
    events = await log_of(client, headers, path, thread)
    assert [event["kind"] for event in events] == ["thread.created", "turn.requested"]


@pytest.mark.anyio
async def test_a_stale_execution_cannot_write_to_the_log(narrative_env, assistant_settings):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    turn = (await ask(client, headers, path, thread, project["head_revision_id"])).json()
    token = uuid4()
    await claim(factory, turn["id"], token)
    async with factory() as session:
        await fail_turn(session, turn_id=UUID(turn["id"]), execution_token=uuid4(), error_code="x")
        await session.commit()
    kinds = [event["kind"] for event in await log_of(client, headers, path, thread)]
    assert kinds == ["thread.created", "turn.requested"]


@pytest.mark.anyio
async def test_the_log_refuses_updates_and_deletes(narrative_env, assistant_settings):
    client, factory, _ = narrative_env
    headers, _, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    for change in (
        update(NarrativeAssistantThreadEvent).values(kind="turn.failed"),
        delete(NarrativeAssistantThreadEvent),
    ):
        async with factory() as session:
            with pytest.raises((DBAPIError, IntegrityError)):
                await session.execute(
                    change.where(NarrativeAssistantThreadEvent.thread_id == UUID(thread["id"]))
                )
    assert len(await log_of(client, headers, path, thread)) == 1


@pytest.mark.anyio
async def test_the_log_is_project_scoped(narrative_env, assistant_settings):
    client, _, _ = narrative_env
    headers, _, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    other_headers, _, other_path = await new_story(client, name="Other story")
    foreign = await client.get(
        f"{other_path}/assistant/threads/{thread['id']}/events", headers=other_headers
    )
    assert foreign.status_code == 404


@pytest.mark.anyio
async def test_sequences_stay_gapless_across_turns_and_threads(narrative_env, assistant_settings):
    client, factory, _ = narrative_env
    headers, project, path = await new_story(client)
    first, second = await new_thread(client, headers, path), await new_thread(client, headers, path)
    head = project["head_revision_id"]
    done = (await ask(client, headers, path, first, head)).json()
    await work(factory, done["id"], json.dumps({"reply": "Hello.", "proposal": None}))
    await ask(client, headers, path, second, head)
    for thread, expected in ((first, [1, 2, 3]), (second, [1, 2])):
        assert [e["sequence"] for e in await log_of(client, headers, path, thread)] == expected
    async with factory() as session:
        counters = {
            str(row.id): row.next_event_sequence
            for row in await session.scalars(select(NarrativeAssistantThread))
        }
        statuses = set(await session.scalars(select(NarrativeAssistantTurn.status)))
    assert counters == {first["id"]: 4, second["id"]: 3}
    assert statuses == {"completed", "queued"}


@pytest.mark.anyio
async def test_migration_backfills_existing_conversations_faithfully(
    narrative_env, assistant_settings
):
    """Conversations from before the log keep their past: the fold still agrees with the rows."""
    client, factory, _ = narrative_env
    engine = factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("Migrations run on PostgreSQL only.")
    headers, project, path = await new_story(client)
    thread = await new_thread(client, headers, path)
    head = project["head_revision_id"]
    first = (await ask(client, headers, path, thread, head, request="One")).json()
    await work(factory, first["id"], proposal())
    proposal_id = (await turns(client, headers, path, thread))[0]["proposal"]["id"]
    await client.post(f"{path}/assistant/proposals/{proposal_id}/reject", headers=headers)
    second = (await ask(client, headers, path, thread, head, request="Two")).json()
    await client.post(
        f"{path}/assistant/threads/{thread['id']}/turns/{second['id']}/cancel", headers=headers
    )
    written = [(e["sequence"], e["kind"]) for e in await log_of(client, headers, path, thread)]

    async with engine.begin() as connection:
        schema = (await connection.execute(text("SELECT current_schema()"))).scalar_one()

        def rebuild(sync_connection):
            config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
            config.set_main_option("script_location", str(Path(__file__).parents[2] / "migrations"))
            config.attributes["connection"] = sync_connection
            config.attributes["configure_logger"] = False
            config.attributes["version_table_schema"] = schema
            command.downgrade(config, "0044_access_credits")
            command.upgrade(config, "0045_assistant_thread_log")

        await connection.run_sync(rebuild)

    assert [
        (e["sequence"], e["kind"]) for e in await log_of(client, headers, path, thread)
    ] == written
    state = await state_of(factory, thread)
    rows = await turns(client, headers, path, thread)
    assert [(t.turn_id, t.status, t.reply) for t in state.turns] == [
        (row["id"], row["status"], row["reply"]) for row in rows
    ]
    assert state.turns[0].proposal.status == "rejected"
    # New writes continue after the backfilled positions, with no gap or collision.
    third = await ask(client, headers, path, thread, head, request="Three")
    assert third.status_code == 202
    events = await log_of(client, headers, path, thread)
    assert [e["sequence"] for e in events] == list(range(1, len(written) + 2))
